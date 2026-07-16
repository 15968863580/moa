"""kaka_moa - 工具调用执行器（SKILL / MCP / 内置 builtin）"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .builtin_tools import builtin_registry
from .mcp_client import mcp_client
from .models import MCPServerConfig, ToolDefinition

logger = logging.getLogger(__name__)


class ToolExecutor:
    """执行模型发起的工具调用。

    工具类型:
      - builtin__*: 进程内直接执行（web_search/exec/web_fetch/read_file 等）
      - mcp__{server}__{tool}: 真实转发到对应 MCP server
      - skill__*: 占位（由宿主环境执行）
    """

    def __init__(self):
        self._mcp_tools: Dict[str, Dict[str, Any]] = {}
        self._allowed_tools: Dict[str, ToolDefinition] = {}
        self._mcp_servers: Dict[str, MCPServerConfig] = {}

    def configure_mcp_servers(self, servers: Optional[Dict[str, MCPServerConfig]]) -> None:
        """注入全局 MCP server 配置（由 main.py 在启动/reload 时调用）。"""
        self._mcp_servers = servers or {}
        logger.info(
            f"ToolExecutor configured with {len(self._mcp_servers)} MCP servers: "
            f"{list(self._mcp_servers.keys())}"
        )

    def load_definitions(
        self,
        tools: Optional[List[ToolDefinition]],
        skill_dir: Optional[str] = None,
        mcp_dir: Optional[str] = None,
        builtin_tools: Optional[List[str]] = None,
    ) -> List[ToolDefinition]:
        allowed_tools = self._load_allowed_tools(skill_dir, mcp_dir, builtin_tools)

        if tools:
            requested_names = {tool.function.name for tool in tools if tool.type == "function"}
            filtered_tools = [tool for tool in allowed_tools if tool.function.name in requested_names]
        else:
            filtered_tools = allowed_tools

        self._allowed_tools = {tool.function.name: tool for tool in filtered_tools}
        self._mcp_tools = {
            tool.function.name: tool.function.model_dump()
            for tool in filtered_tools
            if tool.function.name.startswith("mcp__")
        }
        return filtered_tools

    def build_tool_schemas(self, tools: Optional[List[ToolDefinition]]) -> List[Dict[str, Any]]:
        if not tools:
            return []

        schemas: List[Dict[str, Any]] = []
        for tool in tools:
            if tool.type != "function":
                continue
            function_def = tool.function
            schemas.append({
                "type": "function",
                "function": {
                    "name": function_def.name,
                    "description": function_def.description,
                    "parameters": function_def.parameters or {
                        "type": "object",
                        "properties": {}
                    }
                }
            })
        return schemas

    async def execute_tool_call(self, name: str, arguments: str) -> str:
        if name not in self._allowed_tools:
            raise ValueError(f"Tool '{name}' is not allowed for current MOA")

        parsed_arguments = self._parse_arguments(arguments)

        if name.startswith("builtin__"):
            return await builtin_registry.execute(name, parsed_arguments)

        if name.startswith("skill__"):
            return self._execute_skill(name, parsed_arguments)

        if name in self._mcp_tools:
            return await self._execute_mcp(name, parsed_arguments)

        raise ValueError(f"Unsupported tool: {name}")

    def _load_allowed_tools(
        self,
        skill_dir: Optional[str],
        mcp_dir: Optional[str],
        builtin_tools: Optional[List[str]],
    ) -> List[ToolDefinition]:
        tools: List[ToolDefinition] = []
        tools.extend(self._load_tools_from_dir(skill_dir, expected_prefix="skill__"))
        tools.extend(self._load_tools_from_dir(mcp_dir, expected_prefix="mcp__"))
        if builtin_tools:
            tools.extend(builtin_registry.get_definitions(builtin_tools))
        return tools

    def _load_tools_from_dir(self, directory: Optional[str], expected_prefix: str) -> List[ToolDefinition]:
        if not directory:
            return []

        base_dir = Path(directory)
        if not base_dir.exists() or not base_dir.is_dir():
            logger.warning(f"Tool directory not found or not a directory: {directory}")
            return []

        tools: List[ToolDefinition] = []
        for file_path in sorted(base_dir.glob("*.json")):
            with open(file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)

            tool = ToolDefinition.model_validate(raw)
            tool_name = tool.function.name
            if not tool_name.startswith(expected_prefix):
                raise ValueError(
                    f"Tool '{tool_name}' in {file_path} must start with prefix '{expected_prefix}'"
                )
            tools.append(tool)
        return tools

    def _execute_skill(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        result = {
            "ok": True,
            "type": "skill",
            "tool": tool_name,
            "arguments": arguments,
            "message": f"已请求调用 SKILL: {tool_name}。请在后续流程中由宿主环境实际执行。"
        }
        return json.dumps(result, ensure_ascii=False)

    async def _execute_mcp(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        # 工具名格式: mcp__{server}__{remote_tool}
        parts = tool_name.split("__", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid mcp tool name: {tool_name}")
        _, server_name, remote_tool = parts

        config = self._mcp_servers.get(server_name)
        if not config:
            raise ValueError(
                f"MCP server '{server_name}' not configured (tool={tool_name})"
            )

        logger.info(
            f"Forwarding MCP call: server={server_name} tool={remote_tool} args={arguments}"
        )
        return await mcp_client.call_tool(config, remote_tool, arguments)

    def _parse_arguments(self, arguments: str) -> Dict[str, Any]:
        if not arguments:
            return {}
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid tool arguments: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must be a JSON object")
        return parsed


tool_executor = ToolExecutor()
