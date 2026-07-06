# MOA 服务部署指南

## 部署方式

### 1. 本地部署（开发环境）

#### 安装依赖

```bash
pip install -r requirements.txt
```

#### 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 API Key
```

#### 启动服务

```bash
python -m src.main
```

服务将在 `http://localhost:8000` 启动。

### 2. Docker 部署（推荐）

#### 构建镜像

```bash
docker-compose build
```

#### 启动服务

```bash
docker-compose up -d
```

#### 查看日志

```bash
docker-compose logs -f
```

#### 停止服务

```bash
docker-compose down
```

### 3. 生产环境部署

#### 使用 Gunicorn + Uvicorn

```bash
# 安装 gunicorn
pip install gunicorn

# 启动服务（4 个 worker）
gunicorn src.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

#### Systemd 服务

创建 `/etc/systemd/system/moa.service`：

```ini
[Unit]
Description=MOA Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/moa
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/gunicorn src.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable moa
sudo systemctl start moa
sudo systemctl status moa
```

### 4. Kubernetes 部署

创建 `deployment.yaml`：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: moa-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: moa-service
  template:
    metadata:
      labels:
        app: moa-service
    spec:
      containers:
      - name: moa-service
        image: your-registry/moa-service:latest
        ports:
        - containerPort: 8000
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: moa-secrets
              key: openai-api-key
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: moa-secrets
              key: anthropic-api-key
        - name: MOA_API_KEY
          valueFrom:
            secretKeyRef:
              name: moa-secrets
              key: moa-api-key
        volumeMounts:
        - name: config
          mountPath: /app/moa-config.yaml
          subPath: moa-config.yaml
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
      volumes:
      - name: config
        configMap:
          name: moa-config
---
apiVersion: v1
kind: Service
metadata:
  name: moa-service
spec:
  selector:
    app: moa-service
  ports:
  - port: 8000
    targetPort: 8000
  type: ClusterIP
```

创建 ConfigMap 和 Secret：

```bash
kubectl create configmap moa-config --from-file=moa-config.yaml
kubectl create secret generic moa-secrets \
  --from-literal=openai-api-key=sk-xxx \
  --from-literal=anthropic-api-key=sk-ant-xxx \
  --from-literal=moa-api-key=your-moa-key
```

部署：

```bash
kubectl apply -f deployment.yaml
```

## 反向代理配置

### Nginx

```nginx
upstream moa_service {
    server localhost:8000;
}

server {
    listen 80;
    server_name moa.example.com;

    location / {
        proxy_pass http://moa_service;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # SSE 支持
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

### Caddy

```
moa.example.com {
    reverse_proxy localhost:8000
}
```

## 监控和日志

### 健康检查

```bash
curl http://localhost:8000/health
```

### 查看统计

```bash
curl http://localhost:8000/stats \
  -H "Authorization: Bearer your-moa-api-key"
```

### 日志级别

修改 `src/main.py` 中的日志级别：

```python
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG, INFO, WARNING, ERROR
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
```

## 性能优化

### 1. 调整 Worker 数量

```bash
# 建议：CPU 核心数 * 2 + 1
gunicorn src.main:app --workers 9
```

### 2. 启用连接池

在 `src/caller.py` 中配置 litellm 连接池：

```python
litellm.client_session = httpx.AsyncClient(
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
)
```

### 3. 缓存策略

对于相同请求，可以添加缓存层（如 Redis）：

```python
# 伪代码示例
cache_key = hash(messages)
cached_response = redis.get(cache_key)
if cached_response:
    return cached_response
```

### 4. 负载均衡

使用多个 MOA 实例 + 负载均衡器：

```yaml
# docker-compose.yml
services:
  moa-1:
    build: .
    ports:
      - "8001:8000"
  
  moa-2:
    build: .
    ports:
      - "8002:8000"
  
  nginx:
    image: nginx
    ports:
      - "8000:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
```

## 故障排查

### 问题 1: API Key 无效

**症状**: 返回 401 错误

**解决**:
- 检查 `.env` 文件中的 API Key 是否正确
- 确认环境变量已加载（重启服务）
- 验证 API Key 格式（OpenAI: `sk-xxx`, Anthropic: `sk-ant-xxx`）

### 问题 2: 模型调用超时

**症状**: 返回 500 错误，日志显示 timeout

**解决**:
- 增加模型配置中的 `timeout` 参数
- 检查网络连接
- 验证 API Key 是否有足够配额

### 问题 3: 流式响应中断

**症状**: 流式输出突然停止

**解决**:
- 检查反向代理配置（禁用 buffering）
- 增加 `proxy_read_timeout`
- 查看客户端是否正确处理 SSE

### 问题 4: 内存占用过高

**症状**: 内存持续增长

**解决**:
- 减少 worker 数量
- 检查是否有内存泄漏
- 添加请求大小限制

## 安全建议

1. **使用 HTTPS** - 通过反向代理启用 SSL/TLS
2. **限制 API Key 权限** - 为不同客户端创建不同的 API Key
3. **启用速率限制** - 防止滥用
4. **定期更新依赖** - `pip install --upgrade -r requirements.txt`
5. **监控异常请求** - 查看日志中的错误模式

## 备份和恢复

### 备份配置文件

```bash
tar -czf moa-backup-$(date +%Y%m%d).tar.gz \
  moa-config.yaml .env
```

### 恢复配置

```bash
tar -xzf moa-backup-20260706.tar.gz
# 重启服务
docker-compose restart
```

## 升级指南

### 1. 备份当前版本

```bash
docker-compose down
docker tag moa-service:latest moa-service:backup
```

### 2. 拉取新版本

```bash
git pull origin main
docker-compose build
```

### 3. 启动新版本

```bash
docker-compose up -d
```

### 4. 验证服务

```bash
curl http://localhost:8000/health
```
