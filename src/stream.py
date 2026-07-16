"""kaka_moa - 流式响应处理"""

import json
import time
import uuid
from typing import AsyncIterator

from .models import ChatCompletionStreamResponse, ChatCompletionStreamChoice


class StreamHandler:
    """流式响应处理器 - 将 Aggregator 流转换为 OpenAI 格式"""
    
    @staticmethod
    async def stream_response(
        aggregator_stream: AsyncIterator[str],
        preset_name: str
    ) -> AsyncIterator[str]:
        """
        将 Aggregator 的流式输出转换为 OpenAI Chat Completion 流式格式
        
        Args:
            aggregator_stream: Aggregator 模型的流式输出
            preset_name: MOA 预设名称
        
        Yields:
            SSE 格式的流式响应
        """
        chunk_id = f"chatcmpl-moa-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        
        try:
            # 发送第一个 chunk（包含 role）
            first_chunk = ChatCompletionStreamResponse(
                id=chunk_id,
                created=created,
                model=preset_name,
                choices=[
                    ChatCompletionStreamChoice(
                        index=0,
                        delta={"role": "assistant", "content": ""},
                        finish_reason=None
                    )
                ]
            )
            yield f"data: {first_chunk.model_dump_json()}\n\n"
            
            # 流式输出内容
            async for content in aggregator_stream:
                chunk = ChatCompletionStreamResponse(
                    id=chunk_id,
                    created=created,
                    model=preset_name,
                    choices=[
                        ChatCompletionStreamChoice(
                            index=0,
                            delta={"content": content},
                            finish_reason=None
                        )
                    ]
                )
                yield f"data: {chunk.model_dump_json()}\n\n"
            
            # 发送结束标记
            final_chunk = ChatCompletionStreamResponse(
                id=chunk_id,
                created=created,
                model=preset_name,
                choices=[
                    ChatCompletionStreamChoice(
                        index=0,
                        delta={},
                        finish_reason="stop"
                    )
                ]
            )
            yield f"data: {final_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        
        except Exception as e:
            # 发送错误信息
            error_chunk = {
                "error": {
                    "message": str(e),
                    "type": "server_error",
                    "code": "stream_error"
                }
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            yield "data: [DONE]\n\n"

    @staticmethod
    async def stream_text(
        text: str,
        preset_name: str,
        chunk_size: int = 20
    ) -> AsyncIterator[str]:
        """将一段完整文本按块切分，模拟 OpenAI 流式输出。

        用于流式请求中工具循环跑完后的最终内容回放（工具调用需先非流式拿到完整结果）。
        """
        chunk_id = f"chatcmpl-moa-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        first_chunk = ChatCompletionStreamResponse(
            id=chunk_id,
            created=created,
            model=preset_name,
            choices=[
                ChatCompletionStreamChoice(
                    index=0,
                    delta={"role": "assistant", "content": ""},
                    finish_reason=None
                )
            ]
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        for i in range(0, len(text), chunk_size):
            piece = text[i:i + chunk_size]
            chunk = ChatCompletionStreamResponse(
                id=chunk_id,
                created=created,
                model=preset_name,
                choices=[
                    ChatCompletionStreamChoice(
                        index=0,
                        delta={"content": piece},
                        finish_reason=None
                    )
                ]
            )
            yield f"data: {chunk.model_dump_json()}\n\n"

        final_chunk = ChatCompletionStreamResponse(
            id=chunk_id,
            created=created,
            model=preset_name,
            choices=[
                ChatCompletionStreamChoice(
                    index=0,
                    delta={},
                    finish_reason="stop"
                )
            ]
        )
        yield f"data: {final_chunk.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"


class ClaudeStreamHandler:
    """Claude (Anthropic) 流式响应处理器 - 将文本转换为 Claude SSE 格式"""

    @staticmethod
    def _sse(event: str, data: dict) -> str:
        """生成 Claude SSE 格式的事件"""
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    async def stream_text(
        text: str,
        preset_name: str,
        input_tokens: int = 0,
        chunk_size: int = 20
    ) -> AsyncIterator[str]:
        """将一段完整文本按块切分，模拟 Claude Messages API 流式输出。

        Claude SSE 事件序列:
        1. message_start - 消息开始（含 usage）
        2. content_block_start - 内容块开始
        3. content_block_delta - 内容块增量（多次）
        4. content_block_stop - 内容块结束
        5. message_delta - 消息结束（含 stop_reason 和最终 usage）
        6. message_stop - 消息停止
        """
        message_id = f"msg_moa-{uuid.uuid4().hex[:12]}"
        output_tokens = max(1, len(text) // 4)  # 粗略估算

        # 1. message_start
        yield ClaudeStreamHandler._sse("message_start", {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": preset_name,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": 1
                }
            }
        })

        # 2. content_block_start
        yield ClaudeStreamHandler._sse("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "text",
                "text": ""
            }
        })

        # 3. content_block_delta (多次)
        for i in range(0, len(text), chunk_size):
            piece = text[i:i + chunk_size]
            yield ClaudeStreamHandler._sse("content_block_delta", {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "text_delta",
                    "text": piece
                }
            })

        # 4. content_block_stop
        yield ClaudeStreamHandler._sse("content_block_stop", {
            "type": "content_block_stop",
            "index": 0
        })

        # 5. message_delta
        yield ClaudeStreamHandler._sse("message_delta", {
            "type": "message_delta",
            "delta": {
                "stop_reason": "end_turn",
                "stop_sequence": None
            },
            "usage": {
                "output_tokens": output_tokens
            }
        })

        # 6. message_stop
        yield ClaudeStreamHandler._sse("message_stop", {
            "type": "message_stop"
        })
