"""kaka_moa - 统一的模型调用器"""

import json
import logging
import time
from typing import List, Dict, Any, Optional, AsyncIterator

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .models import ModelConfig

logger = logging.getLogger(__name__)


class ModelCaller:
    """统一的模型调用接口 - 支持多种 LLM 提供商"""

    def __init__(self):
        # 配置 litellm
        litellm.suppress_debug_info = True

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((TimeoutError, ConnectionError, Exception)),
        reraise=True
    )
    async def call(
        self,
        config: ModelConfig,
        messages: List[Dict[str, Any]],
        stream: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        stop: Optional[List[str]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        **kwargs
    ):
        """
        调用指定模型

        Args:
            config: 模型配置
            messages: 消息列表
            stream: 是否流式输出
            temperature/max_tokens/top_p/frequency_penalty/presence_penalty/stop:
                客户端传入的采样参数，非 None 时优先于 config 中的默认值
            tools/tool_choice: 工具调用定义
            **kwargs: 额外参数

        Returns:
            非流式: 返回完整响应内容
            流式: 返回异步生成器
        """
        model = self._build_model_id(config)

        call_params = {
            "model": model,
            "messages": messages,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": stream,
        }

        if config.api_key:
            call_params["api_key"] = config.api_key
        if config.base_url:
            call_params["base_url"] = config.base_url
        if config.timeout:
            call_params["timeout"] = config.timeout

        if temperature is not None:
            call_params["temperature"] = temperature
        if max_tokens is not None:
            call_params["max_tokens"] = max_tokens
        if top_p is not None:
            call_params["top_p"] = top_p
        if frequency_penalty is not None:
            call_params["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            call_params["presence_penalty"] = presence_penalty
        if stop is not None:
            call_params["stop"] = stop
        if tools:
            call_params["tools"] = tools
        if tool_choice is not None:
            call_params["tool_choice"] = tool_choice

        call_params.update(kwargs)

        log_params = {k: v for k, v in call_params.items() if k != 'api_key'}
        logger.info(f"调用参数: {json.dumps(log_params, ensure_ascii=False, default=str)}")
        start_time = time.time()

        try:
            if stream:
                response = await litellm.acompletion(**call_params)
                elapsed = time.time() - start_time
                logger.info(f"Stream started for {model} in {elapsed:.2f}s")
                return self._handle_stream(response, model)

            response = await litellm.acompletion(**call_params)
            elapsed = time.time() - start_time

            message = response.choices[0].message
            content = getattr(message, "content", "") or ""
            tool_calls = self._extract_tool_calls(message)
            finish_reason = getattr(response.choices[0], "finish_reason", "stop") or "stop"
            usage = {
                "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0),
                "completion_tokens": getattr(response.usage, 'completion_tokens', 0),
                "total_tokens": getattr(response.usage, 'total_tokens', 0),
            }

            logger.info(
                f"Model {model} responded in {elapsed:.2f}s, "
                f"tokens: {usage['total_tokens']}"
            )
            logger.info(f"模型返回内容: {content}")
            if tool_calls:
                logger.info(f"模型返回工具调用: {json.dumps(tool_calls, ensure_ascii=False)}")

            return {
                "content": content,
                "tool_calls": tool_calls,
                "finish_reason": finish_reason,
                "usage": usage,
                "model": model,
                "latency_ms": elapsed * 1000
            }

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"Model {model} failed after {elapsed:.2f}s: {e}",
                exc_info=True
            )
            raise

    async def _handle_stream(self, response, model: str) -> AsyncIterator[str]:
        """处理流式响应"""
        accumulated = []
        try:
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    accumulated.append(content)
                    yield content
            logger.info(f"模型返回内容(流式): {''.join(accumulated)}")
        except Exception as e:
            logger.error(f"Stream error for {model}: {e}", exc_info=True)
            raise

    def _extract_tool_calls(self, message: Any) -> List[Dict[str, Any]]:
        tool_calls = getattr(message, "tool_calls", None) or []
        extracted: List[Dict[str, Any]] = []
        for tool_call in tool_calls:
            function = getattr(tool_call, "function", None)
            extracted.append({
                "id": getattr(tool_call, "id", ""),
                "type": getattr(tool_call, "type", "function"),
                "function": {
                    "name": getattr(function, "name", ""),
                    "arguments": getattr(function, "arguments", "")
                }
            })
        return extracted

    def _build_model_id(self, config: ModelConfig) -> str:
        """
        构造 litellm 模型标识

        litellm 格式: provider/model_name
        例如: openai/gpt-4, anthropic/claude-3, openai/qwen2.5-72b (自定义 base_url)
        """
        provider = config.provider.lower()

        provider_map = {
            "openai": "openai",
            "anthropic": "anthropic",
            "openai_compatible": "openai",
            "azure": "azure",
            "ollama": "ollama",
            "deepseek": "deepseek",
        }

        litellm_provider = provider_map.get(provider, provider)

        return f"{litellm_provider}/{config.model}"


model_caller = ModelCaller()
