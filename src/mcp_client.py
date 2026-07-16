"""kaka_moa - MCP 工具真实转发客户端

基于官方 mcp SDK（>=1.0），支持三种 transport:
  - stdio: 本地子进程（command + args + env）
  - streamable_http: MCP Streamable HTTP
  - sse: MCP SSE

工具名 mcp__{server}__{tool} 会被 ToolExecutor 路由到对应 server 的 call_tool。
"""

import asyncio
import json
import logging
from typing import Any, Dict

from .models import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPClient:
    """MCP 工具调用客户端。

    当前实现为每次调用新建会话（保证正确性优先）；
    对于 stdio 会反复拉起子进程，后续可优化为连接池复用。
    """

    async def call_tool(
        self,
        config: MCPServerConfig,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        try:
            return await asyncio.wait_for(
                self._call_tool_inner(config, tool_name, arguments),
                timeout=config.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"MCP tool '{tool_name}' timed out after {config.timeout}s"
            ) from exc

    async def _call_tool_inner(
        self,
        config: MCPServerConfig,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        transport = config.transport
        if transport == "stdio":
            return await self._call_stdio(config, tool_name, arguments)
        if transport == "streamable_http":
            return await self._call_streamable_http(config, tool_name, arguments)
        if transport == "sse":
            return await self._call_sse(config, tool_name, arguments)
        raise ValueError(f"Unsupported MCP transport: {transport}")

    async def _run_session(self, read, write, tool_name: str, arguments: Dict[str, Any]) -> str:
        from mcp import ClientSession

        async with ClientSession(read, write) as session:
            await session.initialize()
            logger.info(f"MCP call_tool: {tool_name}, args={arguments}")
            result = await session.call_tool(tool_name, arguments)
            return self._format_result(result, tool_name)

    def _format_result(self, result: Any, tool_name: str) -> str:
        content = getattr(result, "content", None) or []
        texts = []
        for block in content:
            text = getattr(block, "text", None)
            if text is not None:
                texts.append(text)
            elif hasattr(block, "model_dump"):
                texts.append(json.dumps(block.model_dump(), ensure_ascii=False, default=str))
            else:
                texts.append(str(block))
        output = "\n".join(texts) if texts else "(empty result)"
        is_error = getattr(result, "is_error", False)
        if is_error:
            return f"[MCP tool '{tool_name}' returned error]\n{output}"
        return output

    async def _call_stdio(self, config: MCPServerConfig, tool_name: str, arguments: Dict[str, Any]) -> str:
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        if not config.command:
            raise ValueError("stdio transport requires 'command'")
        params = StdioServerParameters(
            command=config.command,
            args=list(config.args),
            env=dict(config.env) if config.env else None,
        )
        logger.info(f"MCP stdio server: {config.command} {' '.join(config.args)}")
        async with stdio_client(params) as (read, write, _):
            return await self._run_session(read, write, tool_name, arguments)

    async def _call_streamable_http(self, config: MCPServerConfig, tool_name: str, arguments: Dict[str, Any]) -> str:
        from mcp.client.streamable_http import streamablehttp_client

        if not config.url:
            raise ValueError("streamable_http transport requires 'url'")
        logger.info(f"MCP streamable_http: {config.url} tool={tool_name}")
        async with streamablehttp_client(
            url=config.url,
            headers=dict(config.headers) if config.headers else None,
        ) as (read, write, _):
            return await self._run_session(read, write, tool_name, arguments)

    async def _call_sse(self, config: MCPServerConfig, tool_name: str, arguments: Dict[str, Any]) -> str:
        from mcp.client.sse import sse_client

        if not config.url:
            raise ValueError("sse transport requires 'url'")
        logger.info(f"MCP sse: {config.url} tool={tool_name}")
        async with sse_client(
            url=config.url,
            headers=dict(config.headers) if config.headers else None,
        ) as (read, write):
            return await self._run_session(read, write, tool_name, arguments)


mcp_client = MCPClient()
