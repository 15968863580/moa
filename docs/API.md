# MOA 服务 API 文档

## 基础信息

- **Base URL**: `http://localhost:8000`
- **认证方式**: Bearer Token（通过 `Authorization: Bearer <api-key>` 头）
- **API Key**: 在 `.env` 文件中配置 `MOA_API_KEY`

## 端点列表

### 1. Chat Completions

**POST** `/v1/chat/completions`

与 OpenAI Chat Completions API 完全兼容。

#### 请求参数

```json
{
  "model": "moa-gpt4-claude",
  "messages": [
    {"role": "system", "content": "你是一个有帮助的助手"},
    {"role": "user", "content": "你好"}
  ],
  "temperature": 0.7,
  "max_tokens": 2000,
  "stream": false,
  "top_p": 1.0,
  "frequency_penalty": 0.0,
  "presence_penalty": 0.0,
  "stop": ["\n\n"]
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model | string | 是 | MOA 预设名称（如 `moa-gpt4-claude`） |
| messages | array | 是 | 消息列表 |
| temperature | float | 否 | 温度参数（0-2），默认 0.7 |
| max_tokens | int | 否 | 最大生成 token 数 |
| stream | bool | 否 | 是否流式输出，默认 false |
| top_p | float | 否 | Top-p 采样，默认 1.0 |
| frequency_penalty | float | 否 | 频率惩罚，默认 0.0 |
| presence_penalty | float | 否 | 存在惩罚，默认 0.0 |
| stop | array | 否 | 停止词列表 |

#### 非流式响应

```json
{
  "id": "chatcmpl-moa-abc123",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "moa-gpt4-claude",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好！有什么可以帮助你的吗？"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 20,
    "total_tokens": 30
  }
}
```

#### 流式响应

设置 `stream: true`，返回 SSE 格式：

```
data: {"id":"chatcmpl-moa-abc123","object":"chat.completion.chunk","created":1234567890,"model":"moa-gpt4-claude","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-moa-abc123","object":"chat.completion.chunk","created":1234567890,"model":"moa-gpt4-claude","choices":[{"index":0,"delta":{"content":"你好"},"finish_reason":null}]}

data: {"id":"chatcmpl-moa-abc123","object":"chat.completion.chunk","created":1234567890,"model":"moa-gpt4-claude","choices":[{"index":0,"delta":{"content":"！"},"finish_reason":null}]}

data: {"id":"chatcmpl-moa-abc123","object":"chat.completion.chunk","created":1234567890,"model":"moa-gpt4-claude","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### 2. 获取模型列表

**GET** `/v1/models`

返回所有可用的 MOA 预设。

#### 响应

```json
{
  "object": "list",
  "data": [
    {
      "id": "moa-gpt4-claude",
      "object": "model",
      "created": 1234567890,
      "owned_by": "moa-service"
    },
    {
      "id": "moa-local-ensemble",
      "object": "model",
      "created": 1234567890,
      "owned_by": "moa-service"
    }
  ]
}
```

### 3. 健康检查

**GET** `/health`

检查服务状态，无需认证。

#### 响应

```json
{
  "status": "ok",
  "version": "1.0.0",
  "presets_count": 2
}
```

### 4. 获取统计信息

**GET** `/stats`

获取服务调用统计。

#### 响应

```json
{
  "total_requests": 100,
  "successful_requests": 95,
  "failed_requests": 5,
  "total_tokens": 50000,
  "avg_latency_ms": 2500.5
}
```

### 5. 热重载配置

**POST** `/admin/reload`

重新加载 `moa-config.yaml` 配置文件，无需重启服务。

#### 响应

```json
{
  "status": "ok",
  "message": "Config reloaded successfully"
}
```

## 错误处理

### 错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

### 常见错误码

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 401 | API Key 无效或缺失 |
| 404 | 模型不存在 |
| 500 | 服务器内部错误 |

## 使用示例

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-moa-api-key"
)

response = client.chat.completions.create(
    model="moa-gpt4-claude",
    messages=[
        {"role": "user", "content": "你好"}
    ],
    temperature=0.7
)

print(response.choices[0].message.content)
```

### Python (流式)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-moa-api-key"
)

stream = client.chat.completions.create(
    model="moa-gpt4-claude",
    messages=[
        {"role": "user", "content": "你好"}
    ],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### cURL

```bash
# 非流式
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-moa-api-key" \
  -d '{
    "model": "moa-gpt4-claude",
    "messages": [{"role": "user", "content": "你好"}]
  }'

# 流式
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-moa-api-key" \
  -d '{
    "model": "moa-gpt4-claude",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

### JavaScript (Fetch)

```javascript
const response = await fetch('http://localhost:8000/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer your-moa-api-key'
  },
  body: JSON.stringify({
    model: 'moa-gpt4-claude',
    messages: [
      { role: 'user', content: '你好' }
    ]
  })
});

const data = await response.json();
console.log(data.choices[0].message.content);
```
