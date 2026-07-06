"""kaka_moa 服务测试 - 配置管理测试"""

import pytest
import tempfile
import os
from pathlib import Path

from src.config import ConfigManager


@pytest.fixture
def temp_config_file():
    """创建临时配置文件"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        f.write("""
server:
  host: "0.0.0.0"
  port: 8000
  api_key: "test-key"
  rate_limit: 100

moa_presets:
  - name: "test-preset"
    description: "Test preset"
    references:
      - provider: "openai"
        model: "gpt-3.5-turbo"
        api_key: "test-openai-key"
        temperature: 0.7
        max_tokens: 100
    aggregator:
      provider: "openai"
      model: "gpt-4"
      api_key: "test-openai-key"
      temperature: 0.3
      max_tokens: 200
    aggregator_prompt: "汇总：{reference_responses}"
""")
        config_path = f.name

    yield config_path

    # 清理
    os.unlink(config_path)


def test_load_config(temp_config_file):
    """测试加载配置"""
    config_manager = ConfigManager(temp_config_file)

    assert config_manager.server_config.host == "0.0.0.0"
    assert config_manager.server_config.port == 8000
    assert config_manager.server_config.api_key == "test-key"

    presets = config_manager.list_presets()
    assert len(presets) == 1
    assert "test-preset" in presets


def test_get_preset(temp_config_file):
    """测试获取预设"""
    config_manager = ConfigManager(temp_config_file)

    preset = config_manager.get_preset("test-preset")
    assert preset is not None
    assert preset.name == "test-preset"
    assert len(preset.references) == 1
    assert preset.references[0].model == "gpt-3.5-turbo"


def test_has_preset(temp_config_file):
    """测试检查预设是否存在"""
    config_manager = ConfigManager(temp_config_file)

    assert config_manager.has_preset("test-preset") is True
    assert config_manager.has_preset("non-existent") is False


def test_env_var_resolution():
    """测试环境变量解析"""
    # 设置环境变量
    os.environ['TEST_API_KEY'] = 'resolved-key'

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        f.write("""
server:
  api_key: "${TEST_API_KEY}"
moa_presets: []
""")
        config_path = f.name

    try:
        config_manager = ConfigManager(config_path)
        assert config_manager.server_config.api_key == "resolved-key"
    finally:
        os.unlink(config_path)
        del os.environ['TEST_API_KEY']


def test_reload_config(temp_config_file):
    """测试热重载配置"""
    config_manager = ConfigManager(temp_config_file)

    # 修改配置文件
    with open(temp_config_file, 'w', encoding='utf-8') as f:
        f.write("""
server:
  host: "127.0.0.1"
  port: 9000
  api_key: "new-key"
moa_presets: []
""")

    # 重新加载
    config_manager.reload()

    assert config_manager.server_config.host == "127.0.0.1"
    assert config_manager.server_config.port == 9000
    assert config_manager.server_config.api_key == "new-key"


def test_missing_config_file():
    """测试配置文件不存在的情况"""
    config_manager = ConfigManager("/non/existent/path.yaml")

    # 应该使用默认配置
    assert config_manager.server_config.host == "0.0.0.0"
    assert config_manager.server_config.port == 8000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
