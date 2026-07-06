"""kaka_moa 服务测试 - 编排引擎测试"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.orchestrator import MOAOrchestrator
from src.models import ChatCompletionRequest, ChatMessage, MOAPreset, ModelConfig


@pytest.fixture
def orchestrator():
    """编排器实例"""
    return MOAOrchestrator()


@pytest.fixture
def sample_request():
    """示例请求"""
    return ChatCompletionRequest(
        model="test-preset",
        messages=[
            ChatMessage(role="user", content="你好")
        ]
    )


@pytest.fixture
def sample_preset():
    """示例预设"""
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


@pytest.mark.asyncio
async def test_execute_success(orchestrator, sample_request, sample_preset):
    """测试成功执行 MOA 流程"""
    with patch('src.orchestrator.model_caller') as mock_caller:
        # 模拟 Reference 模型调用
        mock_caller.call = AsyncMock(side_effect=[
            {
                "content": "回答1",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                "model": "gpt-3.5-turbo",
                "latency_ms": 100
            },
            {
                "content": "回答2",
                "usage": {"prompt_tokens": 10, "completion_tokens": 25, "total_tokens": 35},
                "model": "gpt-3.5-turbo",
                "latency_ms": 120
            },
            # Aggregator 调用
            {
                "content": "最终回答",
                "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
                "model": "gpt-4",
                "latency_ms": 200
            }
        ])
        
        response = await orchestrator.execute(sample_request, sample_preset)
        
        assert response.model == "test-preset"
        assert len(response.choices) == 1
        assert response.choices[0].message.content == "最终回答"
        assert response.usage.total_tokens == 145  # 30 + 35 + 80


@pytest.mark.asyncio
async def test_execute_partial_failure(orchestrator, sample_request, sample_preset):
    """测试部分 Reference 模型失败的情况"""
    with patch('src.orchestrator.model_caller') as mock_caller:
        # 第一个 Reference 成功，第二个失败
        mock_caller.call = AsyncMock(side_effect=[
            {
                "content": "回答1",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                "model": "gpt-3.5-turbo",
                "latency_ms": 100
            },
            Exception("Model timeout"),
            # Aggregator 调用
            {
                "content": "最终回答",
                "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
                "model": "gpt-4",
                "latency_ms": 200
            }
        ])
        
        response = await orchestrator.execute(sample_request, sample_preset)
        
        # 应该仍然成功（降级策略）
        assert response.choices[0].message.content == "最终回答"


@pytest.mark.asyncio
async def test_execute_all_references_fail(orchestrator, sample_request, sample_preset):
    """测试所有 Reference 模型都失败"""
    with patch('src.orchestrator.model_caller') as mock_caller:
        mock_caller.call = AsyncMock(side_effect=[
            Exception("Model 1 failed"),
            Exception("Model 2 failed")
        ])
        
        with pytest.raises(Exception, match="All reference models failed"):
            await orchestrator.execute(sample_request, sample_preset)


def test_build_aggregator_prompt(orchestrator):
    """测试构建 Aggregator Prompt"""
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
    
    # 应该包含系统提示
    assert result[0]["role"] == "system"
    assert "回答1：晴天" in result[0]["content"]
    assert "回答2：多云" in result[0]["content"]
    
    # 应该保留原始对话历史（排除 system）
    assert len(result) == 4  # 1 system + 3 original messages
    assert result[1]["role"] == "user"
    assert result[1]["content"] == "你好"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
