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
