"""kaka_moa - 数据模型定义"""

from typing import List, Optional, Dict, Any, Literal, Union
from pydantic import BaseModel, Field
import time
import uuid


# ============================================================================
# OpenAI 兼容的请求/响应模型
# ============================================================================

class ChatMessageToolCallFunction(BaseModel):
    """工具调用函数定义"""
    name: str
    arguments: str


class ChatMessageToolCall(BaseModel):
    """工具调用信息"""
    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
    type: Literal["function"] = "function"
    function: ChatMessageToolCallFunction


class ChatMessage(BaseModel):
    """聊天消息"""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[ChatMessageToolCall]] = None


class ToolFunctionDefinition(BaseModel):
    """函数工具定义"""
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class ToolDefinition(BaseModel):
    """工具定义"""
    type: Literal["function"] = "function"
    function: ToolFunctionDefinition


class ToolChoiceFunction(BaseModel):
    """指定工具函数"""
    name: str


class ToolChoiceObject(BaseModel):
    """工具选择对象"""
    type: Literal["function"] = "function"
    function: ToolChoiceFunction


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
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[Literal["none", "auto", "required"], ToolChoiceObject]] = None


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
# Claude (Anthropic) 兼容的请求/响应模型
# ============================================================================

class ClaudeContentBlock(BaseModel):
    """Claude 内容块"""
    type: Literal["text", "tool_use", "tool_result"] = "text"
    text: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    tool_use_id: Optional[str] = None
    content: Optional[Union[str, List["ClaudeContentBlock"]]] = None


class ClaudeMessage(BaseModel):
    """Claude 聊天消息"""
    role: Literal["user", "assistant"]
    content: Union[str, List[ClaudeContentBlock]]


class ClaudeToolChoice(BaseModel):
    """Claude 工具选择对象"""
    type: Literal["auto", "any", "tool"] = "auto"
    name: Optional[str] = None


class ClaudeMessageRequest(BaseModel):
    """Claude Messages API 请求"""
    model: str
    messages: List[ClaudeMessage]
    max_tokens: int
    system: Optional[Union[str, List[ClaudeContentBlock]]] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[List[str]] = None
    stream: Optional[bool] = False
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[Literal["auto", "any"], ClaudeToolChoice]] = None
    metadata: Optional[Dict[str, Any]] = None


class ClaudeUsage(BaseModel):
    """Claude Token 使用统计"""
    input_tokens: int = 0
    output_tokens: int = 0


class ClaudeMessageResponse(BaseModel):
    """Claude Messages API 响应"""
    id: str = Field(default_factory=lambda: f"msg_moa-{uuid.uuid4().hex[:12]}")
    type: str = "message"
    role: str = "assistant"
    model: str
    content: List[ClaudeContentBlock]
    stop_reason: Optional[str] = "end_turn"
    stop_sequence: Optional[str] = None
    usage: ClaudeUsage = Field(default_factory=ClaudeUsage)


# 重建前向引用（ClaudeContentBlock 的 content 字段引用了自身）
ClaudeContentBlock.model_rebuild()


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


class MCPServerConfig(BaseModel):
    """单个 MCP Server 配置（用于 mcp__ 真实转发）

    工具名形如 mcp__{server}__{tool}，会路由到对应 server。
    transport 支持:
      - stdio: 本地子进程（command + args + env）
      - streamable_http: MCP Streamable HTTP transport
      - sse: MCP SSE transport
    """
    transport: Literal["stdio", "streamable_http", "sse"] = "stdio"
    command: Optional[str] = None  # stdio: 可执行命令
    args: List[str] = Field(default_factory=list)  # stdio: 命令参数
    env: Dict[str, str] = Field(default_factory=dict)  # stdio: 子进程环境变量
    url: Optional[str] = None  # streamable_http / sse: 服务地址
    headers: Dict[str, str] = Field(default_factory=dict)  # http 类: 请求头
    timeout: int = 60  # 单次工具调用超时（秒）


class MOAPreset(BaseModel):
    """MOA 预设配置"""
    name: str
    description: str = ""
    references: List[ModelConfig]
    aggregator: ModelConfig
    aggregator_prompt: str = """你是一个专业的回答汇总助手。以下是多个 AI 助手对同一问题的独立回答：

{reference_responses}

请综合分析以上回答，提取最有价值的信息，生成一个更全面、准确、有用的最终回答。"""
    skill_dir: Optional[str] = None
    mcp_dir: Optional[str] = None
    builtin_tools: List[str] = Field(default_factory=list)


class ServerConfig(BaseModel):
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 7890
    api_key: str = ""
    rate_limit: int = 100


class AppConfig(BaseModel):
    """应用配置"""
    server: ServerConfig = Field(default_factory=ServerConfig)
    moa_presets: List[MOAPreset] = Field(default_factory=list)
    # 全局共享的 MCP Server 配置，工具名 mcp__{server}__{tool} 会路由到这里
    mcp_servers: Dict[str, MCPServerConfig] = Field(default_factory=dict)


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
