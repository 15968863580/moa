"""kaka_moa - 内置工具框架（builtin__ 前缀）

在 moa 进程内直接执行的工具，无需外部 MCP/SKILL。
通过 preset 的 builtin_tools 列表控制启用哪些工具（短名，如 "web_search"）。
exec 默认建议不启用，确需时显式列入 builtin_tools。
"""

import asyncio
import json
import logging
import os
import shlex
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from .models import ToolDefinition, ToolFunctionDefinition

logger = logging.getLogger(__name__)

BUILTIN_TOOL_PREFIX = "builtin__"
_MAX_OUTPUT = 20000


class BuiltinToolRegistry:
    """内置工具注册表。"""

    def __init__(self):
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[str]]] = {}
        self._definitions: Dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[[Dict[str, Any]], Awaitable[str]],
    ) -> None:
        full_name = BUILTIN_TOOL_PREFIX + name
        self._definitions[full_name] = ToolDefinition(
            type="function",
            function=ToolFunctionDefinition(
                name=full_name,
                description=description,
                parameters=parameters,
            ),
        )
        self._handlers[full_name] = handler
        logger.debug(f"Registered builtin tool: {full_name}")

    def get_definitions(self, names: Optional[List[str]] = None) -> List[ToolDefinition]:
        if names is None:
            return list(self._definitions.values())
        result: List[ToolDefinition] = []
        for n in names:
            full = BUILTIN_TOOL_PREFIX + n
            if full in self._definitions:
                result.append(self._definitions[full])
            else:
                logger.warning(f"Unknown builtin tool requested: {n}")
        return result

    def has(self, full_name: str) -> bool:
        return full_name in self._handlers

    async def execute(self, full_name: str, arguments: Dict[str, Any]) -> str:
        handler = self._handlers.get(full_name)
        if not handler:
            raise ValueError(f"Unknown builtin tool: {full_name}")
        return await handler(arguments)


builtin_registry = BuiltinToolRegistry()


# ============================================================================
# 内置工具实现
# ============================================================================

async def _web_search(arguments: Dict[str, Any]) -> str:
    query = arguments.get("query")
    if not query:
        raise ValueError("web_search: 'query' is required")
    num = int(arguments.get("num", 5))
    base_url = os.getenv("WEB_SEARCH_API_BASE_URL")
    api_key = os.getenv("WEB_SEARCH_API_KEY")
    if not base_url:
        raise RuntimeError(
            "web_search 不可用：未配置环境变量 WEB_SEARCH_API_BASE_URL"
        )

    params: Dict[str, Any] = {"q": query, "num": num}
    headers: Dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(base_url, params=params, headers=headers)
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            text = resp.text[:_MAX_OUTPUT]
            return f"web_search query={query}\n(non-json response)\n{text}"

    formatted = _extract_search_items(data, num)
    if formatted:
        return f"web_search query={query}\n\n{formatted}"
    raw = json.dumps(data, ensure_ascii=False, default=str)[:_MAX_OUTPUT]
    return f"web_search query={query}\n\n{raw}"


def _extract_search_items(data: Any, num: int) -> Optional[str]:
    items = None
    if isinstance(data, dict):
        for key in ("results", "organic", "organic_results", "items", "web", "web_results"):
            v = data.get(key)
            if isinstance(v, list):
                items = v
                break
    elif isinstance(data, list):
        items = data
    if not items:
        return None
    lines = []
    for i, it in enumerate(items[:num], 1):
        if not isinstance(it, dict):
            continue
        title = it.get("title") or it.get("name") or ""
        url = it.get("url") or it.get("link") or it.get("href") or ""
        snippet = (it.get("content") or it.get("snippet")
                   or it.get("description") or it.get("body") or "")
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
    return "\n\n".join(lines) if lines else None


async def _web_fetch(arguments: Dict[str, Any]) -> str:
    url = arguments.get("url")
    if not url:
        raise ValueError("web_fetch: 'url' is required")
    max_chars = int(arguments.get("max_chars", 8000))
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        text = resp.text
    body = text[:max_chars]
    return (
        f"url: {url}\n"
        f"content_type: {content_type}\n"
        f"length: {len(text)}\n\n"
        f"{body}"
    )


async def _exec(arguments: Dict[str, Any]) -> str:
    command = arguments.get("command")
    if not command:
        raise ValueError("exec: 'command' is required")
    work_dir = os.getenv("EXEC_WORK_DIR") or None
    timeout = int(arguments.get("timeout", os.getenv("EXEC_TIMEOUT", "30")))
    use_shell = bool(arguments.get("shell", True))

    try:
        if use_shell:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            if os.name == "nt":
                args_list = shlex.split(command, posix=False)
            else:
                args_list = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *args_list,
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": f"failed to start command: {exc}"},
            ensure_ascii=False,
        )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        await proc.wait()
        return json.dumps(
            {"ok": False, "error": f"command timed out after {timeout}s", "exit_code": -1},
            ensure_ascii=False,
        )

    exit_code = proc.returncode
    stdout = stdout_b.decode(errors="replace")[:_MAX_OUTPUT] if stdout_b else ""
    stderr = stderr_b.decode(errors="replace")[:_MAX_OUTPUT] if stderr_b else ""
    return json.dumps(
        {"ok": exit_code == 0, "exit_code": exit_code, "stdout": stdout, "stderr": stderr},
        ensure_ascii=False,
    )


async def _read_file(arguments: Dict[str, Any]) -> str:
    path = arguments.get("path")
    if not path:
        raise ValueError("read_file: 'path' is required")
    p = Path(path)
    if not p.is_absolute():
        work_dir = os.getenv("EXEC_WORK_DIR")
        if work_dir:
            p = Path(work_dir) / p
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    if not p.is_file():
        raise ValueError(f"path is not a file: {p}")
    max_chars = int(arguments.get("max_chars", 20000))
    text = p.read_text(encoding="utf-8", errors="replace")
    return text[:max_chars]


# ============================================================================
# 注册内置工具（配置里使用短名：web_search / web_fetch / exec / read_file）
# ============================================================================

builtin_registry.register(
    name="web_search",
    description="联网搜索。返回与关键词相关的网页结果（标题/URL/摘要）。需服务端配置 WEB_SEARCH_API_BASE_URL。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "num": {"type": "integer", "description": "返回结果数量", "default": 5},
        },
        "required": ["query"],
    },
    handler=_web_search,
)

builtin_registry.register(
    name="web_fetch",
    description="抓取指定 URL 的网页/接口内容并返回文本。",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的 URL"},
            "max_chars": {"type": "integer", "description": "返回内容最大字符数", "default": 8000},
        },
        "required": ["url"],
    },
    handler=_web_fetch,
)

builtin_registry.register(
    name="exec",
    description="在服务端执行 shell 命令（高风险）。受 EXEC_WORK_DIR 工作目录与 timeout 限制。",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "timeout": {"type": "integer", "description": "超时秒数", "default": 30},
            "shell": {"type": "boolean", "description": "是否通过 shell 执行", "default": True},
        },
        "required": ["command"],
    },
    handler=_exec,
)

builtin_registry.register(
    name="read_file",
    description="读取服务端本地文件内容。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对路径基于 EXEC_WORK_DIR）"},
            "max_chars": {"type": "integer", "description": "返回内容最大字符数", "default": 20000},
        },
        "required": ["path"],
    },
    handler=_read_file,
)
