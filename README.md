# kaka_moa

**Mixture of Agents** - 多模型协作代理服务，兼容 OpenAI API 格式。

## 简介

kaka_moa 服务通过并行调用多个 LLM 模型（Reference Models），然后使用一个 Aggregator 模型汇总这些回答，生成更高质量的最终响应。

### 核心特性

- ✅ **OpenAI API 兼容** - 无缝对接现有客户端
- ✅ **多模型协作** - 并行调用多个 LLM，综合优势
- ✅ **流式响应** - 支持 SSE 流式输出
- ✅ **灵活配置** - YAML 配置 + 环境变量
- ✅ **热重载** - 修改配置无需重启服务
- ✅ **降级容错** - 单个模型失败不影响整体

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/15968863580/moa.git
cd moa
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 启动服务

```bash
python -m src.main
```

服务将在 `http://localhost:7890` 启动。

### 5. 测试调用

```bash
curl http://localhost:7890/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-moa-api-key" \
  -d '{
    "model": "moa-gpt4-claude",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

## 使用 Docker

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

## 配置说明

### MOA 预设配置

编辑 `moa-config.yaml` 定义 MOA 预设：

```yaml
moa_presets:
  - name: "your-preset-name"
    description: "你的预设描述"

    references:
      - provider: "openai"
        model: "gpt-4"
        api_key: "${OPENAI_API_KEY}"
        temperature: 0.7
        max_tokens: 2000

      - provider: "anthropic"
        model: "claude-3-sonnet"
        api_key: "${ANTHROPIC_API_KEY}"
        temperature: 0.7
        max_tokens: 2000

    aggregator:
      provider: "openai"
      model: "gpt-4"
      api_key: "${OPENAI_API_KEY}"
      temperature: 0.3
      max_tokens: 3000

    aggregator_prompt: |
      你是一个专业的回答汇总助手。以下是多个 AI 助手的回答：

      {reference_responses}

      请综合分析，生成更全面、准确的最终回答。
```

更多配置选项请参考 [docs/CONFIG.md](file:///d:/desktop/moa/moa/docs/CONFIG.md)。

## API 接口

### 聊天补全

**请求：**

```bash
POST /v1/chat/completions
```

**请求体：**

```json
{
  "model": "moa-gpt4-claude",
  "messages": [
    {"role": "user", "content": "解释一下量子计算"}
  ],
  "temperature": 0.7,
  "stream": false
}
```

**响应：**

```json
{
  "id": "chatcmpl-moa-abc123",
  "object": "chat.completion",
  "created": 1704067200,
  "model": "moa-gpt4-claude",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "量子计算是..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 300,
    "total_tokens": 450
  }
}
```

### 流式响应

设置 `stream: true` 即可获得 SSE 流式输出。

### 模型列表

```bash
GET /v1/models
```

### 健康检查

```bash
GET /health
```

### 统计信息

```bash
GET /stats
```

## 管理接口

### 热重载配置

```bash
POST /admin/reload
```

### 获取配置

```bash
GET /admin/config
```

### 保存配置

```bash
POST /admin/config
```

## 开发

### 运行测试

```bash
pytest tests/ -v
```

### 项目结构

```text
moa/
├── src/
│   ├── main.py          # FastAPI 入口
│   ├── orchestrator.py  # MOA 编排引擎
│   ├── caller.py        # 统一模型调用器
│   ├── config.py        # 配置管理
│   ├── models.py        # 数据模型
│   └── stream.py        # 流式响应处理
├── tests/               # 测试文件
├── docs/                # 文档
├── moa-config.yaml      # 配置文件
└── requirements.txt     # Python 依赖
```

## 许可证

MIT
