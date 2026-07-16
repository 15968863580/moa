"""kaka_moa - FastAPI 应用入口"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Dict, Optional

from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, Request, Body, Header
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from . import __version__
from .config import ConfigManager
from .logging_config import setup_logging
from .models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelListResponse,
    ModelInfo,
    HealthResponse,
    StatsResponse,
    ClaudeMessageRequest,
    ClaudeMessageResponse,
    ClaudeContentBlock,
    ClaudeUsage,
    ChatMessage,
)
from .orchestrator import orchestrator
from .stream import ClaudeStreamHandler

# 配置日志：控制台 + 按天滚动文件（全量 logs/moa.log + 错误 logs/error.log）
setup_logging()
logger = logging.getLogger(__name__)

# 全局配置管理器
config_manager = ConfigManager()

# 管理 UI 页面路径
UI_PATH = Path(__file__).parent.parent / "static" / "admin.html"

# 统计信息
stats: Dict[str, int] = {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "total_tokens": 0,
    "total_latency_ms": 0.0
}

# 认证
security = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"kaka_moa v{__version__} starting...")
    logger.info(f"Loaded {len(config_manager.list_presets())} MOA presets")
    for name in config_manager.list_presets():
        preset = config_manager.get_preset(name)
        logger.info(f"  - {name}: {len(preset.references)} refs + 1 agg")
    yield
    logger.info("kaka_moa shutting down...")


app = FastAPI(
    title="kaka_moa",
    description="Mixture of Agents - 多模型协作代理服务",
    version=__version__,
    lifespan=lifespan
)


# ============================================================================
# 认证中间件
# ============================================================================

async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """验证 API Key"""
    expected_key = config_manager.server_config.api_key
    
    # 如果未配置 API Key，跳过认证
    if not expected_key:
        return
    
    if not credentials or credentials.credentials != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


async def verify_api_key_flexible(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key")
):
    """验证 API Key - 同时兼容 OpenAI (Authorization: Bearer) 和 Claude (x-api-key) 认证方式"""
    expected_key = config_manager.server_config.api_key

    # 如果未配置 API Key，跳过认证
    if not expected_key:
        return

    # 优先检查 x-api-key (Claude 风格)
    if x_api_key:
        if x_api_key == expected_key:
            return
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 检查 Authorization: Bearer (OpenAI 风格)
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            if parts[1] == expected_key:
                return
        raise HTTPException(status_code=401, detail="Invalid API key")

    raise HTTPException(status_code=401, detail="Missing API key")


# ============================================================================
# API 路由
# ============================================================================

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    _: None = Depends(verify_api_key)
):
    """
    Chat Completions API - OpenAI 兼容
    
    客户端通过 model 参数选择 MOA 预设
    """
    start_time = time.time()
    stats["total_requests"] += 1
    
    # 检查预设是否存在
    preset = config_manager.get_preset(request.model)
    if not preset:
        stats["failed_requests"] += 1
        available = config_manager.list_presets()
        raise HTTPException(
            status_code=404,
            detail=f"Model '{request.model}' not found. Available models: {available}"
        )
    
    try:
        if request.stream:
            # 流式响应
            async def generate():
                try:
                    async for chunk in orchestrator.execute_stream(request, preset):
                        yield chunk
                    stats["successful_requests"] += 1
                except Exception as e:
                    stats["failed_requests"] += 1
                    logger.error(f"Stream error: {e}", exc_info=True)
                    raise
            
            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # 非流式响应
            response = await orchestrator.execute(request, preset)
            
            # 更新统计
            stats["successful_requests"] += 1
            stats["total_tokens"] += response.usage.total_tokens
            elapsed_ms = (time.time() - start_time) * 1000
            stats["total_latency_ms"] += elapsed_ms
            
            return response
    
    except Exception as e:
        stats["failed_requests"] += 1
        logger.error(f"Execution error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Claude (Anthropic) 兼容 API 路由
# ============================================================================

def _claude_to_openai_request(claude_request: ClaudeMessageRequest) -> ChatCompletionRequest:
    """将 Claude Messages API 请求转换为内部 OpenAI 格式请求"""
    messages = []

    # Claude 的 system 是顶层参数，转换为 OpenAI 的 system 消息
    if claude_request.system:
        system_content = claude_request.system
        if isinstance(system_content, list):
            # 如果是 content block 列表，拼接文本
            system_content = " ".join(
                block.text for block in system_content if block.text
            )
        messages.append(ChatMessage(role="system", content=system_content))

    # 转换消息列表
    for msg in claude_request.messages:
        content = msg.content
        if isinstance(content, list):
            # content block 列表拼接为文本
            content = " ".join(block.text for block in content if block.text)
        messages.append(ChatMessage(role=msg.role, content=content or ""))

    # 转换 stop_sequences -> stop
    stop = claude_request.stop_sequences

    return ChatCompletionRequest(
        model=claude_request.model,
        messages=messages,
        temperature=claude_request.temperature,
        max_tokens=claude_request.max_tokens,
        stream=claude_request.stream,
        top_p=claude_request.top_p,
        stop=stop,
        # Claude API 不支持 frequency_penalty / presence_penalty，留空
        frequency_penalty=None,
        presence_penalty=None,
    )


def _openai_response_to_claude(response: ChatCompletionResponse) -> ClaudeMessageResponse:
    """将内部 OpenAI 格式响应转换为 Claude Messages API 响应"""
    # 提取 assistant 消息内容
    content_text = ""
    if response.choices and response.choices[0].message:
        content_text = response.choices[0].message.content or ""

    # 转换 finish_reason -> stop_reason
    finish_reason = response.choices[0].finish_reason if response.choices else "stop"
    stop_reason_map = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
    }
    stop_reason = stop_reason_map.get(finish_reason, "end_turn")

    # 转换 usage
    usage = ClaudeUsage(
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )

    return ClaudeMessageResponse(
        model=response.model,
        content=[ClaudeContentBlock(type="text", text=content_text)],
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=usage,
    )


@app.post("/v1/messages", response_model=ClaudeMessageResponse)
async def claude_messages(
    request: ClaudeMessageRequest,
    _: None = Depends(verify_api_key_flexible)
):
    """
    Claude Messages API - Anthropic 兼容

    客户端通过 model 参数选择 MOA 预设。
    支持 x-api-key 和 Authorization: Bearer 两种认证方式。
    """
    start_time = time.time()
    stats["total_requests"] += 1

    # 检查预设是否存在
    preset = config_manager.get_preset(request.model)
    if not preset:
        stats["failed_requests"] += 1
        available = config_manager.list_presets()
        raise HTTPException(
            status_code=404,
            detail=f"Model '{request.model}' not found. Available models: {available}"
        )

    try:
        # 转换为内部 OpenAI 格式请求
        openai_request = _claude_to_openai_request(request)

        if request.stream:
            # Claude 流式响应
            async def generate():
                try:
                    # 先用非流式跑完 MOA 流程（工具调用需完整结果）
                    response = await orchestrator.execute(openai_request, preset)
                    content = response.choices[0].message.content or ""
                    input_tokens = response.usage.prompt_tokens
                    stats["successful_requests"] += 1
                    async for chunk in ClaudeStreamHandler.stream_text(
                        content, preset.name, input_tokens=input_tokens
                    ):
                        yield chunk
                except Exception as e:
                    stats["failed_requests"] += 1
                    logger.error(f"Claude stream error: {e}", exc_info=True)
                    raise

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # 非流式响应
            response = await orchestrator.execute(openai_request, preset)
            claude_response = _openai_response_to_claude(response)

            # 更新统计
            stats["successful_requests"] += 1
            stats["total_tokens"] += response.usage.total_tokens
            elapsed_ms = (time.time() - start_time) * 1000
            stats["total_latency_ms"] += elapsed_ms

            return claude_response

    except Exception as e:
        stats["failed_requests"] += 1
        logger.error(f"Claude execution error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/models")
async def list_models(_: None = Depends(verify_api_key)):
    """获取可用模型列表"""
    presets = config_manager.list_presets()
    models = [
        ModelInfo(
            id=name,
            owned_by="moa-service"
        )
        for name in presets
    ]
    return ModelListResponse(data=models)


@app.get("/health")
async def health_check():
    """健康检查"""
    return HealthResponse(
        status="ok",
        version=__version__,
        presets_count=len(config_manager.list_presets())
    )


@app.get("/stats")
async def get_stats(_: None = Depends(verify_api_key)):
    """获取调用统计"""
    total = stats["total_requests"]
    avg_latency = (
        stats["total_latency_ms"] / stats["successful_requests"]
        if stats["successful_requests"] > 0 else 0.0
    )
    
    return StatsResponse(
        total_requests=stats["total_requests"],
        successful_requests=stats["successful_requests"],
        failed_requests=stats["failed_requests"],
        total_tokens=stats["total_tokens"],
        avg_latency_ms=round(avg_latency, 2)
    )


@app.post("/admin/reload")
async def reload_config(_: None = Depends(verify_api_key)):
    """热重载配置文件"""
    try:
        config_manager.reload()
        return {"status": "ok", "message": "Config reloaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/ui")
async def admin_ui():
    """管理控制台 UI 页面"""
    if not UI_PATH.exists():
        raise HTTPException(status_code=404, detail="UI file not found")
    return FileResponse(UI_PATH)


@app.get("/admin/config")
async def get_config_file(_: None = Depends(verify_api_key)):
    """获取配置文件原文"""
    try:
        content = config_manager.config_path.read_text(encoding='utf-8')
        return {"content": content, "path": str(config_manager.config_path)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")


@app.post("/admin/config")
async def save_config_file(
    content: str = Body(..., embed=True),
    _: None = Depends(verify_api_key)
):
    """保存配置文件（校验 YAML 语法，不自动重载）"""
    try:
        config_manager.save_config(content)
        return {"status": "ok", "message": "Config saved. Call /admin/reload to apply."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/restart")
async def restart_service(_: None = Depends(verify_api_key)):
    """重启服务（需以 reload 模式或进程管理器运行才能自动恢复）"""
    import threading
    import os

    def _do_restart():
        time.sleep(1.5)
        logger.info("Restarting service by admin request...")
        os._exit(0)

    threading.Thread(target=_do_restart, daemon=True).start()
    return {"status": "restarting", "message": "Service is restarting, please wait ~5s..."}


# ============================================================================
# 入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    server_config = config_manager.server_config
    uvicorn.run(
        "src.main:app",
        host=server_config.host,
        port=server_config.port,
        reload=True
    )
