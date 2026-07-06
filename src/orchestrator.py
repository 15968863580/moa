"""MOA 独立服务 - MOA 编排引擎（核心逻辑）"""

import asyncio
import logging
import time
from typing import List, Dict, Any, Optional, Union

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

logger = logging.getLogger(__name__)


class MOAOrchestrator:
    """MOA 编排引擎 - 协调 Reference 和 Aggregator 模型"""
    
    async def execute(
        self,
        request: ChatCompletionRequest,
        preset: MOAPreset
    ) -> ChatCompletionResponse:
        """
        执行 MOA 流程（非流式）
        
        Args:
            request: 客户端请求
            preset: MOA 预设配置
        
        Returns:
            最终的 ChatCompletionResponse
        """
        start_time = time.time()
        request_id = f"req-{int(time.time() * 1000)}"
        
        logger.info(
            f"[{request_id}] Starting MOA execution for preset: {preset.name}, "
            f"references: {len(preset.references)}"
        )
        
        # 转换消息格式
        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        
        # 1. 并行调用所有 Reference 模型
        reference_tasks = [
            self._call_reference_model(ref_config, messages, request_id, i)
            for i, ref_config in enumerate(preset.references)
        ]
        
        reference_results = await asyncio.gather(*reference_tasks, return_exceptions=True)
        
        # 2. 处理结果，过滤失败的响应
        successful_responses = []
        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
        
        for i, result in enumerate(reference_results):
            if isinstance(result, Exception):
                logger.error(f"[{request_id}] Reference model {i} failed: {result}")
                # 降级策略：跳过失败的模型，继续处理其他成功的响应
            else:
                successful_responses.append(result["content"])
                # 累计 token 使用
                for key in total_usage:
                    total_usage[key] += result["usage"].get(key, 0)
        
        if not successful_responses:
            raise Exception("All reference models failed")
        
        logger.info(
            f"[{request_id}] {len(successful_responses)}/{len(preset.references)} "
            f"reference models succeeded"
        )
        
        # 3. 构造 Aggregator Prompt
        aggregator_messages = self._build_aggregator_prompt(
            original_messages=messages,
            reference_responses=successful_responses,
            template=preset.aggregator_prompt
        )
        
        # 4. 调用 Aggregator 模型
        logger.info(f"[{request_id}] Calling aggregator model")
        aggregator_result = await model_caller.call(
            preset.aggregator,
            aggregator_messages,
            stream=False
        )
        
        # 累计 Aggregator 的 token 使用
        for key in total_usage:
            total_usage[key] += aggregator_result["usage"].get(key, 0)
        
        # 5. 构造最终响应
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"[{request_id}] MOA execution completed in {elapsed_ms:.2f}ms")
        
        return ChatCompletionResponse(
            model=preset.name,
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=aggregator_result["content"]
                    ),
                    finish_reason="stop"
                )
            ],
            usage=UsageInfo(**total_usage)
        )
    
    async def execute_stream(
        self,
        request: ChatCompletionRequest,
        preset: MOAPreset
    ):
        """
        执行 MOA 流程（流式）
        
        Args:
            request: 客户端请求
            preset: MOA 预设配置
        
        Yields:
            SSE 格式的流式响应
        """
        start_time = time.time()
        request_id = f"req-{int(time.time() * 1000)}"
        
        logger.info(
            f"[{request_id}] Starting MOA stream execution for preset: {preset.name}"
        )
        
        # 转换消息格式
        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        
        # 1. 并行调用所有 Reference 模型（非流式）
        reference_tasks = [
            self._call_reference_model(ref_config, messages, request_id, i)
            for i, ref_config in enumerate(preset.references)
        ]
        
        reference_results = await asyncio.gather(*reference_tasks, return_exceptions=True)
        
        # 2. 处理结果
        successful_responses = []
        for i, result in enumerate(reference_results):
            if isinstance(result, Exception):
                logger.error(f"[{request_id}] Reference model {i} failed: {result}")
            else:
                successful_responses.append(result["content"])
        
        if not successful_responses:
            raise Exception("All reference models failed")
        
        logger.info(
            f"[{request_id}] {len(successful_responses)}/{len(preset.references)} "
            f"reference models succeeded"
        )
        
        # 3. 构造 Aggregator Prompt
        aggregator_messages = self._build_aggregator_prompt(
            original_messages=messages,
            reference_responses=successful_responses,
            template=preset.aggregator_prompt
        )
        
        # 4. 调用 Aggregator 模型（流式）
        logger.info(f"[{request_id}] Calling aggregator model (stream)")
        aggregator_stream = await model_caller.call(
            preset.aggregator,
            aggregator_messages,
            stream=True
        )
        
        # 5. 转换为 OpenAI 格式并流式输出
        async for chunk in StreamHandler.stream_response(aggregator_stream, preset.name):
            yield chunk
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"[{request_id}] MOA stream execution completed in {elapsed_ms:.2f}ms")
    
    async def _call_reference_model(
        self,
        config: ModelConfig,
        messages: List[Dict[str, str]],
        request_id: str,
        index: int
    ) -> Dict[str, Any]:
        """调用单个 Reference 模型"""
        logger.debug(f"[{request_id}] Calling reference model {index}: {config.model}")
        
        result = await model_caller.call(
            config,
            messages,
            stream=False
        )
        
        logger.debug(
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
        """
        构造 Aggregator 的输入消息
        
        将多个 Reference 响应格式化后，与原始对话历史一起传给 Aggregator
        """
        # 格式化 Reference 响应
        formatted_responses = "\n\n".join([
            f"【回答 {i+1}】\n{resp}"
            for i, resp in enumerate(reference_responses)
        ])
        
        # 填充模板
        system_prompt = template.format(reference_responses=formatted_responses)
        
        # 构造消息列表：系统提示 + 原始对话历史
        aggregator_messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # 保留原始对话历史（排除 system message，避免重复）
        for msg in original_messages:
            if msg["role"] != "system":
                aggregator_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        
        return aggregator_messages


# 全局单例
orchestrator = MOAOrchestrator()
