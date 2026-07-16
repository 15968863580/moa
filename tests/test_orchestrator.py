"""kaka_moa 服务测试 - 编排引擎测试"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock

from src.orchestrator import MOAOrchestrator
from src.models import (
    ChatCompletionRequest,
    ChatMessage,
    MOAPreset,
    ModelConfig,
    ToolDefinition,
    ToolFunctionDefinition,
)


@pytest.fixture
def orchestrator():
    return MOAOrchestrator()


@pytest.fixture
def sample_request():
    return ChatCompletionRequest(
        model="test-preset",
        messages=[ChatMessage(role="user", content="你好")]
    )


@pytest.fixture
def sample_preset():
    return MOAPreset(
        name="test-preset",
        description="Test preset",
        references=[
            ModelConfig(
                provider="openai",
                model="gpt-3.5-turbo",
                api_key="test-key",
                temperature=0.7,
                max_tokens=100
            ),
            ModelConfig(
                provider="openai",
                model="gpt-3.5-turbo",
                api_key="test-key",
                temperature=0.7,
                max_tokens=100
            )
        ],
        aggregator=ModelConfig(
            provider="openai",
            model="gpt-4",
            api_key="test-key",
            temperature=0.3,
            max_tokens=200
        ),
        aggregator_prompt="汇总以下回答：\n{reference_responses}"
    )


def _ref_result(content: str, tokens: int = 30):
    return {
        "content": content,
        "tool_calls": [],
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": tokens},
        "model": "gpt-3.5-turbo",
        "latency_ms": 100
    }


def _agg_result(content: str, tool_calls=None, finish_reason="stop", tokens: int = 80):
    return {
        "content": content,
        "tool_calls": tool_calls or [],
        "finish_reason": finish_reason,
        "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": tokens},
        "model": "gpt-4",
        "latency_ms": 200
    }


@pytest.mark.asyncio
async def test_execute_success(orchestrator, sample_request, sample_preset):
    with patch('src.orchestrator.model_caller') as mock_caller:
        mock_caller.call = AsyncMock(side_effect=[
            _ref_result("回答1", 30),
            _ref_result("回答2", 35),
            _agg_result("最终回答", tokens=80)
        ])

        response = await orchestrator.execute(sample_request, sample_preset)

        assert response.model == "test-preset"
        assert len(response.choices) == 1
        assert response.choices[0].message.content == "最终回答"
        assert response.usage.total_tokens == 145


@pytest.mark.asyncio
async def test_execute_partial_failure(orchestrator, sample_request, sample_preset):
    with patch('src.orchestrator.model_caller') as mock_caller:
        mock_caller.call = AsyncMock(side_effect=[
            _ref_result("回答1", 30),
            Exception("Model timeout"),
            _agg_result("最终回答", tokens=80)
        ])

        response = await orchestrator.execute(sample_request, sample_preset)
        assert response.choices[0].message.content == "最终回答"


@pytest.mark.asyncio
async def test_execute_all_references_fail(orchestrator, sample_request, sample_preset):
    with patch('src.orchestrator.model_caller') as mock_caller:
        mock_caller.call = AsyncMock(side_effect=[
            Exception("Model 1 failed"),
            Exception("Model 2 failed")
        ])

        with pytest.raises(Exception, match="All reference models failed"):
            await orchestrator.execute(sample_request, sample_preset)


@pytest.mark.asyncio
async def test_execute_with_tool_calls(orchestrator, sample_preset):
    with tempfile.TemporaryDirectory() as temp_dir:
        skill_dir = Path(temp_dir) / "skills"
        skill_dir.mkdir()
        (skill_dir / "skill__pdf.json").write_text(
            json.dumps({
                "type": "function",
                "function": {
                    "name": "skill__pdf",
                    "description": "调用 PDF skill",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"}
                        }
                    }
                }
            }, ensure_ascii=False),
            encoding="utf-8"
        )
        sample_preset.skill_dir = str(skill_dir)

        request = ChatCompletionRequest(
            model="test-preset",
            messages=[ChatMessage(role="user", content="请调用 skill 工具")],
            tools=[
                ToolDefinition(
                    type="function",
                    function=ToolFunctionDefinition(
                        name="skill__pdf",
                        description="调用 SKILL 能力",
                        parameters={
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "文件路径"}
                            }
                        }
                    )
                )
            ]
        )

        tool_call = {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "skill__pdf", "arguments": '{"path": "a.pdf"}'}
        }

        with patch('src.orchestrator.model_caller') as mock_caller:
            mock_caller.call = AsyncMock(side_effect=[
                _ref_result("回答1"),
                _ref_result("回答2"),
                _agg_result("", tool_calls=[tool_call], finish_reason="tool_calls"),
                _agg_result("已调用 skill__pdf", tokens=60),
            ])

            response = await orchestrator.execute(request, sample_preset)

            assert response.choices[0].message.content == "已调用 skill__pdf"
            assert response.choices[0].finish_reason == "stop"
            assert mock_caller.call.await_count == 4


@pytest.mark.asyncio
async def test_preset_tool_isolation(orchestrator, sample_preset):
    with tempfile.TemporaryDirectory() as temp_dir:
        skill_dir_a = Path(temp_dir) / "a_skills"
        skill_dir_b = Path(temp_dir) / "b_skills"
        skill_dir_a.mkdir()
        skill_dir_b.mkdir()

        (skill_dir_a / "skill__alpha.json").write_text(
            json.dumps({
                "type": "function",
                "function": {"name": "skill__alpha", "description": "alpha", "parameters": {"type": "object", "properties": {}}}
            }, ensure_ascii=False),
            encoding="utf-8"
        )
        (skill_dir_b / "skill__beta.json").write_text(
            json.dumps({
                "type": "function",
                "function": {"name": "skill__beta", "description": "beta", "parameters": {"type": "object", "properties": {}}}
            }, ensure_ascii=False),
            encoding="utf-8"
        )

        sample_preset.skill_dir = str(skill_dir_a)
        request = ChatCompletionRequest(
            model="test-preset",
            messages=[ChatMessage(role="user", content="test")],
            tools=[
                ToolDefinition(type="function", function=ToolFunctionDefinition(name="skill__alpha")),
                ToolDefinition(type="function", function=ToolFunctionDefinition(name="skill__beta")),
            ]
        )

        with patch('src.orchestrator.model_caller') as mock_caller:
            mock_caller.call = AsyncMock(side_effect=[
                _ref_result("回答1"),
                _ref_result("回答2"),
                _agg_result("最终回答", tokens=80),
            ])

            await orchestrator.execute(request, sample_preset)

            last_call_kwargs = mock_caller.call.await_args_list[2].kwargs
            tool_names = [item["function"]["name"] for item in last_call_kwargs["tools"]]
            assert tool_names == ["skill__alpha"]
            assert "skill__beta" not in tool_names


def test_build_aggregator_prompt(orchestrator):
    original_messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！"},
        {"role": "user", "content": "天气怎么样？"}
    ]

    reference_responses = ["回答1：晴天", "回答2：多云"]
    template = "汇总以下回答：\n{reference_responses}"

    result = orchestrator._build_aggregator_prompt(
        original_messages,
        reference_responses,
        template
    )

    assert result[0]["role"] == "system"
    assert "回答1：晴天" in result[0]["content"]
    assert "回答2：多云" in result[0]["content"]
    assert len(result) == 4
    assert result[1]["role"] == "user"
    assert result[1]["content"] == "你好"


def test_message_to_dict_preserves_tool_calls(orchestrator):
    msg = ChatMessage(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "skill__pdf", "arguments": '{}'}
            }
        ]
    )
    data = orchestrator._message_to_dict(msg)
    assert data["role"] == "assistant"
    assert data["tool_calls"][0]["function"]["name"] == "skill__pdf"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
