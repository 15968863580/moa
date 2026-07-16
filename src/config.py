"""kaka_moa - 配置加载和管理"""

import os
import re
import yaml
import logging
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

from .models import AppConfig, ServerConfig, MOAPreset, ModelConfig, MCPServerConfig

logger = logging.getLogger(__name__)


class ConfigManager:
    """配置管理器 - 加载、解析、热更新配置"""

    def __init__(self, config_path: str = "moa-config.yaml"):
        self.config_path = Path(config_path)
        self._config: Optional[AppConfig] = None
        self._presets_map: Dict[str, MOAPreset] = {}

        # 加载环境变量
        load_dotenv()

        # 初始加载配置
        self.reload()

    def reload(self):
        """重新加载配置文件"""
        logger.info(f"Loading config from {self.config_path}")

        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}, using defaults")
            self._config = AppConfig()
            self._presets_map = {}
            return

        with open(self.config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f) or {}

        # 解析环境变量
        raw_config = self._resolve_env_vars(raw_config)

        # 构建配置对象
        server_config = ServerConfig(**raw_config.get('server', {}))

        config_dir = self.config_path.parent.resolve()
        presets = []
        for preset_data in raw_config.get('moa_presets', []):
            references = [ModelConfig(**ref) for ref in preset_data.get('references', [])]
            aggregator = ModelConfig(**preset_data.get('aggregator', {}))

            preset = MOAPreset(
                name=preset_data['name'],
                description=preset_data.get('description', ''),
                references=references,
                aggregator=aggregator,
                aggregator_prompt=preset_data.get('aggregator_prompt', ''),
                skill_dir=self._resolve_optional_path(preset_data.get('skill_dir'), config_dir),
                mcp_dir=self._resolve_optional_path(preset_data.get('mcp_dir'), config_dir),
                builtin_tools=preset_data.get('builtin_tools', []),
            )
            presets.append(preset)

        mcp_servers: Dict[str, MCPServerConfig] = {}
        for server_name, server_data in (raw_config.get('mcp_servers') or {}).items():
            mcp_servers[server_name] = MCPServerConfig(**server_data)

        self._config = AppConfig(
            server=server_config,
            moa_presets=presets,
            mcp_servers=mcp_servers
        )

        # 构建预设映射
        self._presets_map = {p.name: p for p in presets}

        logger.info(f"Config loaded: {len(presets)} presets, {len(mcp_servers)} mcp servers")
        for preset in presets:
            logger.info(
                f"  - {preset.name}: {len(preset.references)} references + 1 agg, "
                f"skill_dir={preset.skill_dir}, mcp_dir={preset.mcp_dir}, "
                f"builtin_tools={preset.builtin_tools}"
            )
        if mcp_servers:
            logger.info(f"  MCP servers: {list(mcp_servers.keys())}")

        # 同步 MCP server 配置到工具执行器（保证 reload 后立即生效）
        from .tool_executor import tool_executor
        tool_executor.configure_mcp_servers(self._config.mcp_servers)

    def _resolve_env_vars(self, obj):
        """递归解析配置中的环境变量 ${VAR_NAME}"""
        if isinstance(obj, str):
            pattern = r'\$\{([^}]+)\}'

            def replace_var(match):
                var_name = match.group(1)
                value = os.getenv(var_name, '')
                if not value:
                    logger.warning(f"Environment variable not set: {var_name}")
                return value

            return re.sub(pattern, replace_var, obj)
        if isinstance(obj, dict):
            return {k: self._resolve_env_vars(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._resolve_env_vars(item) for item in obj]
        return obj

    def _resolve_optional_path(self, raw_path: Optional[str], base_dir: Path) -> Optional[str]:
        """将可选目录解析为绝对路径"""
        if not raw_path:
            return None

        path = Path(raw_path)
        if not path.is_absolute():
            path = base_dir / path
        return str(path.resolve())

    @property
    def config(self) -> AppConfig:
        """获取当前配置"""
        if self._config is None:
            self.reload()
        return self._config

    @property
    def server_config(self) -> ServerConfig:
        """获取服务器配置"""
        return self.config.server

    def get_preset(self, name: str) -> Optional[MOAPreset]:
        """根据名称获取预设"""
        return self._presets_map.get(name)

    def list_presets(self) -> list:
        """获取所有预设名称"""
        return list(self._presets_map.keys())

    def has_preset(self, name: str) -> bool:
        """检查预设是否存在"""
        return name in self._presets_map

    def save_config(self, raw_content: str):
        """保存配置文件原文（会先校验 YAML 语法）"""
        try:
            yaml.safe_load(raw_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML syntax: {e}")

        with open(self.config_path, 'w', encoding='utf-8', newline='') as f:
            f.write(raw_content)
        logger.info(f"Config saved to {self.config_path}")
