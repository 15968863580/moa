"""MOA 独立服务 - 配置加载和管理"""

import os
import re
import yaml
import logging
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

from .models import AppConfig, ServerConfig, MOAPreset, ModelConfig

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
            raw_config = yaml.safe_load(f)
        
        # 解析环境变量
        raw_config = self._resolve_env_vars(raw_config)
        
        # 构建配置对象
        server_config = ServerConfig(**raw_config.get('server', {}))
        
        presets = []
        for preset_data in raw_config.get('moa_presets', []):
            references = [ModelConfig(**ref) for ref in preset_data.get('references', [])]
            aggregator = ModelConfig(**preset_data.get('aggregator', {}))
            
            preset = MOAPreset(
                name=preset_data['name'],
                description=preset_data.get('description', ''),
                references=references,
                aggregator=aggregator,
                aggregator_prompt=preset_data.get('aggregator_prompt', '')
            )
            presets.append(preset)
        
        self._config = AppConfig(server=server_config, moa_presets=presets)
        
        # 构建预设映射
        self._presets_map = {p.name: p for p in presets}
        
        logger.info(f"Config loaded: {len(presets)} presets")
        for preset in presets:
            logger.info(f"  - {preset.name}: {len(preset.references)} references + 1 aggregator")
    
    def _resolve_env_vars(self, obj):
        """递归解析配置中的环境变量 ${VAR_NAME}"""
        if isinstance(obj, str):
            # 匹配 ${VAR_NAME} 模式
            pattern = r'\$\{([^}]+)\}'
            
            def replace_var(match):
                var_name = match.group(1)
                value = os.getenv(var_name, '')
                if not value:
                    logger.warning(f"Environment variable not set: {var_name}")
                return value
            
            return re.sub(pattern, replace_var, obj)
        elif isinstance(obj, dict):
            return {k: self._resolve_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_env_vars(item) for item in obj]
        else:
            return obj
    
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
