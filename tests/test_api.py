"""kaka_moa 服务测试 - API 端点测试"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from src.main import app
from src.config import ConfigManager


@pytest.fixture
def client():
    """测试客户端"""
    return TestClient(app)


@pytest.fixture
def mock_config():
    """模拟配置"""
    with patch('src.main.config_manager') as mock:
        mock.server_config.api_key = "test-key"
        mock.list_presets.return_value = ["test-preset"]
        mock.get_preset.return_value = MagicMock(
            name="test-preset",
            description="Test preset",
            references=[MagicMock()],
            aggregator=MagicMock()
        )
        yield mock


def test_health_check(client):
    """测试健康检查端点"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_list_models(client, mock_config):
    """测试获取模型列表"""
    response = client.get("/v1/models", headers={"Authorization": "Bearer test-key"})
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert "data" in data
    assert len(data["data"]) > 0


def test_chat_completion_unauthorized(client, mock_config):
    """测试未认证的请求"""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-preset",
            "messages": [{"role": "user", "content": "test"}]
        }
    )
    # 未带 Authorization header，应被认证拦截
    assert response.status_code in [401, 403]


def test_chat_completion_missing_model(client, mock_config):
    """测试不存在的模型"""
    # 模拟预设不存在
    mock_config.get_preset.return_value = None
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "non-existent-model",
            "messages": [{"role": "user", "content": "test"}]
        }
    )
    assert response.status_code == 404


def test_chat_completion_invalid_request(client, mock_config):
    """测试无效请求"""
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "test-preset"
            # 缺少 messages 字段
        }
    )
    assert response.status_code == 422


# ============================================================================
# Claude (Anthropic) 兼容 API 测试
# ============================================================================

def test_claude_messages_unauthorized(client, mock_config):
    """测试未认证的 Claude 请求"""
    response = client.post(
        "/v1/messages",
        json={
            "model": "test-preset",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "test"}]
        }
    )
    # 未带任何认证 header，应被认证拦截
    assert response.status_code in [401, 403]


def test_claude_messages_x_api_key_auth(client, mock_config):
    """测试 x-api-key 认证方式"""
    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "test-key"},
        json={
            "model": "test-preset",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "test"}]
        }
    )
    # 认证通过但预设的 mock 不匹配，可能 500（mock_config 的 get_preset 返回 MagicMock）
    # 确保不是 401/403 即说明认证通过
    assert response.status_code not in [401, 403]


def test_claude_messages_bearer_auth(client, mock_config):
    """测试 Authorization: Bearer 认证方式（兼容）"""
    response = client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "test-preset",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "test"}]
        }
    )
    assert response.status_code not in [401, 403]


def test_claude_messages_missing_model(client, mock_config):
    """测试 Claude 请求中不存在的模型"""
    mock_config.get_preset.return_value = None
    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "test-key"},
        json={
            "model": "non-existent-model",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "test"}]
        }
    )
    assert response.status_code == 404


def test_claude_messages_invalid_request(client, mock_config):
    """测试 Claude 无效请求（缺少必填字段）"""
    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "test-key"},
        json={
            "model": "test-preset"
            # 缺少 max_tokens 和 messages
        }
    )
    assert response.status_code == 422


def test_stats_endpoint(client, mock_config):
    """测试统计端点"""
    response = client.get("/stats", headers={"Authorization": "Bearer test-key"})
    assert response.status_code == 200
    data = response.json()
    assert "total_requests" in data
    assert "successful_requests" in data
    assert "failed_requests" in data


def test_reload_config(client, mock_config):
    """测试热重载配置"""
    with patch.object(mock_config, 'reload') as mock_reload:
        response = client.post(
            "/admin/reload",
            headers={"Authorization": "Bearer test-key"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
