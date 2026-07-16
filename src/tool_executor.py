"""kaka_moa - 工具调用执行器（SKILL / MCP）"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import ToolDefinition

logger = logging.getLogger(__name__)


class ToolExecutor:
    """执行模型发起的工具调用。"""

    def __init__(self):
        self._mcp_tools: Dict[str, Dict[str, Any]] = {}
        self._allowed_tools: Dict[str, ToolDefinition] = {}

    def load_definitions(
        self,
        tools: Optional[List[ToolDefinition]],
        skill_dir: Optional[str] = None,
        mcp_dir: Optional[str] = None
    ) -> List[ToolDefinition]:
        allowed_tools = self._load_allowed_tools(skill_dir, mcp_dir)

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

        if name.startswith("skill__"):
            return self._execute_skill(name, parsed_arguments)

        if name in self._mcp_tools:
            return self._execute_mcp(name, parsed_arguments)

        raise ValueError(f"Unsupported tool: {name}")

    def _load_allowed_tools(self, skill_dir: Optional[str], mcp_dir: Optional[str]) -> List[ToolDefinition]:
        tools: List[ToolDefinition] = []
        tools.extend(self._load_tools_from_dir(skill_dir, expected_prefix="skill__"))
        tools.extend(self._load_tools_from_dir(mcp_dir, expected_prefix="mcp__"))
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

    def _execute_mcp(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        result = {
            "ok": True,
            "type": "mcp",
            "tool": tool_name,
            "arguments": arguments,
            "message": f"已生成 MCP 调用请求: {tool_name}。请在后续流程中由宿主环境实际执行。"
        }
        return json.dumps(result, ensure_ascii=False)

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
