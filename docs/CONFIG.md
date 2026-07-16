# kaka_moa 服务配置说明

## 配置文件结构

kaka_moa 服务使用 `moa-config.yaml` 作为主配置文件，支持环境变量替换。

### 完整配置示例

```yaml
# 服务器配置
server:
  host: "0.0.0.0"          # 监听地址
  port: 7890                # 监听端口
  api_key: "${MOA_API_KEY}" # 客户端访问 API Key
  rate_limit: 100           # 每分钟最大请求数

# MOA 预设配置
moa_presets:
  - name: "preset-name"
    description: "预设描述"
    skill_dir: "./tools/preset-name/skills"
    mcp_dir: "./tools/preset-name/mcps"
    references: [...]
    aggregator: {...}
    aggregator_prompt: "..."
```

## 服务器配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| host | string | "0.0.0.0" | 监听地址 |
| port | int | 7890 | 监听端口 |
| api_key | string | "" | 客户端访问 API Key（为空则不验证） |
| rate_limit | int | 100 | 每分钟最大请求数 |

## MOA 预设配置

每个预设定义了一组 Reference 模型、Aggregator 模型，以及该预设独享的工具目录。

### 预设参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 预设名称（客户端通过 model 参数指定） |
| description | string | 否 | 预设描述 |
| skill_dir | string | 否 | 当前 MOA 可用的 SKILL 定义目录 |
| mcp_dir | string | 否 | 当前 MOA 可用的 MCP 定义目录 |
| references | array | 是 | Reference 模型列表 |
| aggregator | object | 是 | Aggregator 模型配置 |
| aggregator_prompt | string | 否 | 汇总提示词模板 |

### 工具目录隔离

`skill_dir` 和 `mcp_dir` 用于按 MOA 名称隔离工具权限。

规则如下：

1. 每个 MOA preset 只能加载自己配置的 `skill_dir` 和 `mcp_dir`
2. 不同 MOA 之间的工具目录互相隔离，不能互相调用
3. 如果请求体中传入了不属于当前 preset 目录的工具名，这些工具会被自动过滤
4. 工具定义文件使用 JSON 格式，每个文件定义一个工具
5. 相对路径会基于 `moa-config.yaml` 所在目录解析为绝对路径

### 工具目录示例

```text
tools/
  moa-test/
    skills/
      skill__pdf.json
      skill__xlsx.json
    mcps/
      mcp__github__create_issue.json
      mcp__github__list_issues.json
  moa-prod/
    skills/
      skill__security_review.json
    mcps/
      mcp__github__merge_pull_request.json
```

### 工具命名规则

- `skill_dir` 下的工具名必须以 `skill__` 开头
- `mcp_dir` 下的工具名必须以 `mcp__` 开头

如果命名不符合规则，加载配置后的工具执行阶段会报错。

### 工具定义格式

每个工具文件都是一个 JSON，格式如下：

```json
{
  "type": "function",
  "function": {
    "name": "skill__pdf",
    "description": "调用 PDF 处理 SKILL",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "PDF 文件路径"
        }
      },
      "required": ["path"]
    }
  }
}
```

### 示例：带工具隔离的双 MOA 配置

```yaml
moa_presets:
  - name: "moa-test"
    description: "测试环境 MOA"
    skill_dir: "./tools/moa-test/skills"
    mcp_dir: "./tools/moa-test/mcps"

    references:
      - provider: "openai_compatible"
        model: "qwen3.7-plus"
        api_key: "${ONEAPI_API_KEY}"
        base_url: "${ONEAPI_BASE_URL}"
        temperature: 0.7
        max_tokens: 65536
        timeout: 300

    aggregator:
      provider: "openai_compatible"
      model: "qwen3.7-plus"
      api_key: "${ONEAPI_API_KEY}"
      base_url: "${ONEAPI_BASE_URL}"
      temperature: 0.3
      max_tokens: 65536
      timeout: 300

    aggregator_prompt: |
      你是测试环境助手，可以调用当前 MOA 的工具完成任务。

  - name: "moa-prod"
    description: "生产环境 MOA"
    skill_dir: "./tools/moa-prod/skills"
    mcp_dir: "./tools/moa-prod/mcps"

    references:
      - provider: "openai_compatible"
        model: "qwen3.7-plus"
        api_key: "${ONEAPI_API_KEY}"
        base_url: "${ONEAPI_BASE_URL}"
        temperature: 0.4
        max_tokens: 65536
        timeout: 300

    aggregator:
      provider: "openai_compatible"
      model: "qwen3.7-plus"
      api_key: "${ONEAPI_API_KEY}"
      base_url: "${ONEAPI_BASE_URL}"
      temperature: 0.2
      max_tokens: 65536
      timeout: 300

    aggregator_prompt: |
      你是生产环境助手，只能使用当前 MOA 已授权的工具。
```

## 模型配置

Reference 和 Aggregator 都使用相同的模型配置格式：

```yaml
- provider: "openai"           # LLM 提供商
  model: "gpt-4-turbo-preview" # 模型名称
  api_key: "${OPENAI_API_KEY}" # API Key（支持环境变量）
  base_url: "https://api.openai.com/v1"  # API 地址（可选）
  temperature: 0.7             # 温度参数
  max_tokens: 2000             # 最大生成 token
  timeout: 60                  # 超时时间（秒）
```

#### 支持的 Provider

| Provider | 说明 | 示例 |
|----------|------|------|
| openai | OpenAI 官方 API | gpt-4, gpt-3.5-turbo |
| anthropic | Anthropic Claude | claude-3-sonnet, claude-3-opus |
| openai_compatible | 兼容 OpenAI 格式的本地模型 | ollama, vllm, localai |
| deepseek | DeepSeek | deepseek-chat, deepseek-coder |
| azure | Azure OpenAI | 需要额外配置 |
| ollama | Ollama 本地模型 | llama2, mistral |

## 环境变量

使用 `${VAR_NAME}` 语法引用环境变量：

```yaml
api_key: "${OPENAI_API_KEY}"
base_url: "${LOCAL_MODEL_BASE_URL}"
```

在 `.env` 文件中定义：

```bash
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
MOA_API_KEY=your-moa-service-key
LOCAL_MODEL_BASE_URL=http://localhost:11434/v1
```

## Aggregator Prompt 模板

使用 `{reference_responses}` 占位符引用 Reference 模型的响应：

```yaml
aggregator_prompt: |
  你是一个专业的回答汇总助手。以下是多个 AI 助手对同一问题的独立回答：

  {reference_responses}

  请综合分析以上回答，提取最有价值的信息，生成一个更全面、准确、有用的最终回答。
  要求：
  1. 保留各回答中的正确信息
  2. 如果有冲突，选择最可靠的答案
  3. 补充遗漏的重要细节
  4. 用清晰的结构组织答案
```

## 配置示例

### 示例 1: GPT-4 + Claude 组合

```yaml
moa_presets:
  - name: "moa-gpt4-claude"
    description: "GPT-4 + Claude 3 Sonnet 组合（高质量）"

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

    aggregator:
      provider: "openai"
      model: "gpt-4-turbo-preview"
      api_key: "${OPENAI_API_KEY}"
      temperature: 0.3
      max_tokens: 3000

    aggregator_prompt: |
      你是一个专业的回答汇总助手。以下是多个 AI 助手的独立回答：

      {reference_responses}

      请综合分析，生成更全面、准确的最终回答。
```

### 示例 2: 本地模型组合

```yaml
moa_presets:
  - name: "moa-local-ensemble"
    description: "本地模型组合（低成本）"

    references:
      - provider: "openai_compatible"
        model: "qwen2.5-72b"
        base_url: "${LOCAL_MODEL_BASE_URL}"
        api_key: "ollama"
        temperature: 0.7
        max_tokens: 2000

      - provider: "openai_compatible"
        model: "llama3.1-70b"
        base_url: "${LOCAL_MODEL_BASE_URL}"
        api_key: "ollama"
        temperature: 0.7
        max_tokens: 2000

    aggregator:
      provider: "openai_compatible"
      model: "qwen2.5-72b"
      base_url: "${LOCAL_MODEL_BASE_URL}"
      api_key: "ollama"
      temperature: 0.3
      max_tokens: 3000

    aggregator_prompt: |
      你是一个专业的回答汇总助手。以下是多个 AI 助手的独立回答：

      {reference_responses}

      请综合分析，生成更全面、准确的最终回答。
```

### 示例 3: 混合模式（云端 + 本地）

```yaml
moa_presets:
  - name: "moa-hybrid"
    description: "云端 + 本地混合模式"

    references:
      - provider: "openai"
        model: "gpt-4-turbo-preview"
        api_key: "${OPENAI_API_KEY}"
        temperature: 0.7
        max_tokens: 2000

      - provider: "openai_compatible"
        model: "llama3.1-70b"
        base_url: "${LOCAL_MODEL_BASE_URL}"
        api_key: "ollama"
        temperature: 0.7
        max_tokens: 2000

    aggregator:
      provider: "openai"
      model: "gpt-4-turbo-preview"
      api_key: "${OPENAI_API_KEY}"
      temperature: 0.3
      max_tokens: 3000

    aggregator_prompt: |
      你是一个专业的回答汇总助手。以下是多个 AI 助手的独立回答：

      {reference_responses}

      请综合分析，生成更全面、准确的最终回答。
```

## 热重载配置

修改配置文件后，无需重启服务：

```bash
curl -X POST http://localhost:7890/admin/reload \
  -H "Authorization: Bearer your-moa-api-key"
```

## 配置验证

启动服务时会验证配置文件，如有错误会输出详细错误信息：

```text
ERROR: Invalid config: Missing required field 'name' in preset
```

## 最佳实践

1. **使用环境变量管理 API Key** - 避免硬编码敏感信息
2. **按场景拆分不同 MOA preset** - 如测试环境、生产环境、高风险操作环境
3. **对高权限工具单独隔离目录** - 不要让普通 MOA 共享生产工具
4. **合理设置 temperature** - Reference 模型用较高温度（0.7），Aggregator 用较低温度（0.3）
5. **设置合适的 timeout** - 本地模型可能需要更长的超时时间
6. **新增工具时保持命名规范** - `skill__*` / `mcp__*`
7. **调整配置后执行热重载** - 使新工具目录立即生效
