# MOA 独立服务

**Mixture of Agents** - 多模型协作代理服务，兼容 OpenAI API 格式。

## 简介

MOA 服务通过并行调用多个 LLM 模型（Reference Models），然后使用一个 Aggregator 模型汇总这些回答，生成更高质量的最终响应。

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

服务将在 `http://localhost:8000` 启动。

### 5. 测试调用

```bash
curl http://localhost:8000/v1/chat/completions \
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
  - name: "moa-gpt4-claude"
    description: "GPT-4 + Claude 组合"
    
    # Reference 模型（并行调用）
    references:
      - provider: "openai"
        model: "gpt-4-turbo-preview"
        api_key: "${OPENAI_API_KEY}"
        temperature: 0.7
        max_tokens: 2000
      
      - provider: "anthropic"
        model: "claude-3-sonnet-20240229"
        api_key: "${ANTHROPIC_API_KEY}"
        temperature: 0.7
        max_tokens: 2000
    
    # Aggregator 模型（汇总）
    aggregator:
      provider: "openai"
      model: "gpt-4-turbo-preview"
      api_key: "${OPENAI_API_KEY}"
      temperature: 0.3
      max_tokens: 3000
    
    # 汇总提示词模板
    aggregator_prompt: |
      你是一个专业的回答汇总助手。以下是多个 AI 助手的独立回答：
      
      {reference_responses}
      
      请综合分析，生成更全面、准确的最终回答。
```

### 环境变量

在 `.env` 文件中配置 API Key：

```bash
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
MOA_API_KEY=your-moa-service-key
```

## API 文档

### Chat Completions

**POST** `/v1/chat/completions`

请求参数（与 OpenAI 完全兼容）：

```json
{
  "model": "moa-gpt4-claude",
  "messages": [
    {"role": "user", "content": "你好"}
  ],
  "temperature": 0.7,
  "max_tokens": 2000,
  "stream": false
}
```

### 获取模型列表

**GET** `/v1/models`

返回所有可用的 MOA 预设。

### 健康检查

**GET** `/health`

检查服务状态。

### 热重载配置

**POST** `/admin/reload`

重新加载配置文件，无需重启服务。

## 架构设计

```
┌─────────────────────────────────────────────────────┐
│                  MOA Service                         │
│                                                      │
│  ┌──────────────┐                                   │
│  │  FastAPI     │  OpenAI 兼容 API                  │
│  └──────┬───────┘                                   │
│         │                                            │
│  ┌──────▼───────────────────────────────────────┐  │
│  │         MOA Orchestrator                      │  │
│  │                                               │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐      │  │
│  │  │ Ref 1   │  │ Ref 2   │  │ Ref N   │      │  │
│  │  │ (并行)  │  │ (并行)  │  │ (并行)  │      │  │
│  │  └────┬────┘  └────┬────┘  └────┬────┘      │  │
│  │       └────────────┼────────────┘            │  │
│  │                    │                          │  │
│  │           ┌────────▼────────┐                │  │
│  │           │   Aggregator    │                │  │
│  │           │   (汇总模型)    │                │  │
│  │           └────────┬────────┘                │  │
│  │                    │                          │  │
│  └────────────────────┼──────────────────────────┘  │
│                       │                              │
└───────────────────────┼──────────────────────────────┘
                        │
                        ▼
                  最终响应返回
```

## 支持的 LLM 提供商

- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude 3)
- DeepSeek
- 本地模型（Ollama, vLLM, 任何 OpenAI 兼容接口）

## 项目结构

```
moa/
├── src/
│   ├── main.py           # FastAPI 应用入口
│   ├── orchestrator.py   # MOA 编排引擎
│   ├── caller.py         # 统一模型调用器
│   ├── config.py         # 配置管理
│   ├── models.py         # 数据模型
│   └── stream.py         # 流式响应处理
├── docs/
│   ├── API.md            # API 详细文档
│   ├── CONFIG.md         # 配置说明
│   └── DEPLOY.md         # 部署指南
├── tests/                # 测试文件
├── moa-config.yaml       # MOA 配置
├── requirements.txt      # Python 依赖
├── Dockerfile           # Docker 镜像
├── docker-compose.yml   # Docker Compose
└── README.md            # 项目说明
```

## 开发

### 运行测试

```bash
pytest tests/
```

### 代码格式化

```bash
black src/
isort src/
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

如有问题，请提交 Issue 或联系开发者。
