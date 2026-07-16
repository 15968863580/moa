"""kaka_moa - MOA 编排引擎（核心逻辑）"""

import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Optional

from .models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionResponseChoice,
    ChatMessage,
    UsageInfo,
    MOAPreset,
    ModelConfig
)
from .caller import model_caller
from .stream import StreamHandler
from .tool_executor import tool_executor

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


class MOAOrchestrator:
    """MOA 编排引擎 - 协调 Reference 和 Aggregator 模型"""

    async def execute(
        self,
        request: ChatCompletionRequest,
        preset: MOAPreset
    ) -> ChatCompletionResponse:
        start_time = time.time()
        request_id = f"req-{int(time.time() * 1000)}"

        logger.info(
            f"[{request_id}] Starting MOA execution for preset: {preset.name}, "
            f"references: {len(preset.references)}"
        )

        messages = [self._message_to_dict(msg) for msg in request.messages]

        sampling_params = {
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "top_p": request.top_p,
            "frequency_penalty": request.frequency_penalty,
            "presence_penalty": request.presence_penalty,
            "stop": request.stop,
        }

        reference_tasks = [
            self._call_reference_model(ref_config, messages, request_id, i, **sampling_params)
            for i, ref_config in enumerate(preset.references)
        ]
        reference_results = await asyncio.gather(*reference_tasks, return_exceptions=True)

        successful_responses = []
        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }

        for i, result in enumerate(reference_results):
            if isinstance(result, Exception):
                logger.error(
                    f"[{request_id}] Reference model {i} failed: {result}",
                    exc_info=result
                )
            else:
                successful_responses.append(result["content"])
                for key in total_usage:
                    total_usage[key] += result["usage"].get(key, 0)

        if not successful_responses:
            raise Exception("All reference models failed")

        logger.info(
            f"[{request_id}] {len(successful_responses)}/{len(preset.references)} "
            f"reference models succeeded"
        )

        aggregator_messages = self._build_aggregator_prompt(
            original_messages=messages,
            reference_responses=successful_responses,
            template=preset.aggregator_prompt
        )

        logger.info(f"[{request_id}] Calling aggregator model")
        allowed_tools = tool_executor.load_definitions(
            request.tools,
            skill_dir=preset.skill_dir,
            mcp_dir=preset.mcp_dir
        )
        tools_param = tool_executor.build_tool_schemas(allowed_tools)

        aggregator_result = await self._call_with_tools(
            config=preset.aggregator,
            messages=aggregator_messages,
            tools=tools_param if tools_param else None,
            tool_choice=request.tool_choice,
            request_id=request_id,
            **sampling_params
        )

        for key in total_usage:
            total_usage[key] += aggregator_result["usage"].get(key, 0)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"[{request_id}] MOA execution completed in {elapsed_ms:.2f}ms")

        finish_reason = aggregator_result.get("finish_reason", "stop")
        tool_calls = aggregator_result.get("tool_calls") or []

        assistant_message = ChatMessage(
            role="assistant",
            content=aggregator_result["content"],
            tool_calls=tool_calls if tool_calls else None
        )

        return ChatCompletionResponse(
            model=preset.name,
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=assistant_message,
                    finish_reason=finish_reason
                )
            ],
            usage=UsageInfo(**total_usage)
        )

    async def execute_stream(
        self,
        request: ChatCompletionRequest,
        preset: MOAPreset
    ):
        start_time = time.time()
        request_id = f"req-{int(time.time() * 1000)}"

        logger.info(
            f"[{request_id}] Starting MOA stream execution for preset: {preset.name}"
        )

        messages = [self._message_to_dict(msg) for msg in request.messages]

        sampling_params = {
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "top_p": request.top_p,
            "frequency_penalty": request.frequency_penalty,
            "presence_penalty": request.presence_penalty,
            "stop": request.stop,
        }

        reference_tasks = [
            self._call_reference_model(ref_config, messages, request_id, i, **sampling_params)
            for i, ref_config in enumerate(preset.references)
        ]
        reference_results = await asyncio.gather(*reference_tasks, return_exceptions=True)

        successful_responses = []
        for i, result in enumerate(reference_results):
            if isinstance(result, Exception):
                logger.error(
                    f"[{request_id}] Reference model {i} failed: {result}",
                    exc_info=result
                )
            else:
                successful_responses.append(result["content"])

        if not successful_responses:
            raise Exception("All reference models failed")

        logger.info(
            f"[{request_id}] {len(successful_responses)}/{len(preset.references)} "
            f"reference models succeeded"
        )

        aggregator_messages = self._build_aggregator_prompt(
            original_messages=messages,
            reference_responses=successful_responses,
            template=preset.aggregator_prompt
        )

        logger.info(f"[{request_id}] Calling aggregator model (stream)")
        aggregator_stream = await model_caller.call(
            preset.aggregator,
            aggregator_messages,
            stream=True,
            **sampling_params
        )

        async for chunk in StreamHandler.stream_response(aggregator_stream, preset.name):
            yield chunk

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"[{request_id}] MOA stream execution completed in {elapsed_ms:.2f}ms")

    async def _call_with_tools(
        self,
        config: ModelConfig,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: Optional[Any],
        request_id: str,
        **sampling_params
    ) -> Dict[str, Any]:
        current_messages = list(messages)

        for round_idx in range(MAX_TOOL_ROUNDS):
            logger.info(f"[{request_id}] Aggregator round {round_idx + 1}")
            result = await model_caller.call(
                config,
                current_messages,
                stream=False,
                tools=tools,
                tool_choice=tool_choice,
                **sampling_params
            )

            tool_calls = result.get("tool_calls") or []
            if not tool_calls:
                logger.info(f"[{request_id}] Aggregator finished at round {round_idx + 1}")
                return result

            current_messages.append({
                "role": "assistant",
                "content": result.get("content", "") or "",
                "tool_calls": tool_calls
            })

            for tc in tool_calls:
                tc_id = tc.get("id", "")
                fn = tc.get("function", {})
                name = fn.get("name", "")
                arguments = fn.get("arguments", "")

                logger.info(f"[{request_id}] Executing tool call: {name}, args={arguments}")

                try:
                    tool_result = await tool_executor.execute_tool_call(name, arguments)
                except Exception as exc:
                    logger.error(
                        f"[{request_id}] Tool {name} failed: {exc}",
                        exc_info=True
                    )
                    tool_result = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

                current_messages.append({
                    "role": "tool",
                    "content": tool_result,
                    "tool_call_id": tc_id,
                    "name": name
                })

        logger.warning(
            f"[{request_id}] Reached max tool rounds ({MAX_TOOL_ROUNDS}), "
            f"returning last aggregator response"
        )
        return result

    async def _call_reference_model(
        self,
        config: ModelConfig,
        messages: List[Dict[str, str]],
        request_id: str,
        index: int,
        **sampling_params
    ) -> Dict[str, Any]:
        logger.info(f"[{request_id}] Calling reference model {index}: {config.model}")

        result = await model_caller.call(
            config,
            messages,
            stream=False,
            **sampling_params
        )

        logger.info(
            f"[{request_id}] Reference model {index} completed, "
            f"tokens: {result['usage']['total_tokens']}"
        )

        return result  # type: ignore

    def _build_aggregator_prompt(
        self,
        original_messages: List[Dict[str, str]],
        reference_responses: List[str],
        template: str
    ) -> List[Dict[str, str]]:
        formatted_responses = "\n\n".join([
            f"【回答 {i+1}】\n{resp}"
            for i, resp in enumerate(reference_responses)
        ])
        system_prompt = template.format(reference_responses=formatted_responses)

        aggregator_messages = [
            {"role": "system", "content": system_prompt}
        ]

        for msg in original_messages:
            if msg["role"] != "system":
                aggregator_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        return aggregator_messages

    def _message_to_dict(self, msg: ChatMessage) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "role": msg.role,
            "content": msg.content,
        }
        if msg.name:
            data["name"] = msg.name
        if msg.tool_call_id:
            data["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            data["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in msg.tool_calls
            ]
        return data


orchestrator = MOAOrchestrator()
