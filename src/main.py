"""kaka_moa - FastAPI 应用入口"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from . import __version__
from .config import ConfigManager
from .models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelListResponse,
    ModelInfo,
    HealthResponse,
    StatsResponse
)
from .orchestrator import orchestrator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# 全局配置管理器
config_manager = ConfigManager()

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
                    logger.error(f"Stream error: {e}")
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
