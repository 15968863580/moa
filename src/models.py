"""MOA 独立服务 - 数据模型定义"""

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
import time
import uuid


# ============================================================================
# OpenAI 兼容的请求/响应模型
# ============================================================================

class ChatMessage(BaseModel):
    """聊天消息"""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """OpenAI Chat Completion 请求"""
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop: Optional[List[str]] = None


class ChatCompletionResponseChoice(BaseModel):
    """响应选项"""
    index: int
    message: ChatMessage
    finish_reason: str = "stop"


class UsageInfo(BaseModel):
    """Token 使用统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    """OpenAI Chat Completion 响应"""
    id: str = Field(default_factory=lambda: f"chatcmpl-moa-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatCompletionResponseChoice]
    usage: UsageInfo = Field(default_factory=UsageInfo)


class ChatCompletionStreamChoice(BaseModel):
    """流式响应选项"""
    index: int
    delta: Dict[str, Any]
    finish_reason: Optional[str] = None


class ChatCompletionStreamResponse(BaseModel):
    """OpenAI Chat Completion 流式响应"""
    id: str = Field(default_factory=lambda: f"chatcmpl-moa-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatCompletionStreamChoice]


# ============================================================================
# 配置模型
# ============================================================================

class ModelConfig(BaseModel):
    """单个模型配置"""
    provider: str  # openai, anthropic, openai_compatible 等
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2000
    timeout: int = 60


class MOAPreset(BaseModel):
    """MOA 预设配置"""
    name: str
    description: str = ""
    references: List[ModelConfig]
    aggregator: ModelConfig
    aggregator_prompt: str = """你是一个专业的回答汇总助手。以下是多个 AI 助手对同一问题的独立回答：

{reference_responses}

请综合分析以上回答，提取最有价值的信息，生成一个更全面、准确、有用的最终回答。"""


class ServerConfig(BaseModel):
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8000
    api_key: str = ""
    rate_limit: int = 100


class AppConfig(BaseModel):
    """应用配置"""
    server: ServerConfig = Field(default_factory=ServerConfig)
    moa_presets: List[MOAPreset] = Field(default_factory=list)


# ============================================================================
# 辅助模型
# ============================================================================

class ModelInfo(BaseModel):
    """模型信息（用于 /v1/models 接口）"""
    id: str
    object: str = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "moa-service"


class ModelListResponse(BaseModel):
    """模型列表响应"""
    object: str = "list"
    data: List[ModelInfo]


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "ok"
    version: str = "1.0.0"
    presets_count: int = 0


class StatsResponse(BaseModel):
    """统计信息响应"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_tokens: int = 0
    avg_latency_ms: float = 0.0
