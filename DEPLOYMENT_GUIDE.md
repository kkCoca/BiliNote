# BiliNote 部署与配置指南

> 本文档记录了在 Linux 环境下部署 BiliNote 的完整过程，包含问题排查与解决方案。

---

## 目录

1. [系统概述](#系统概述)
2. [环境准备](#环境准备)
3. [部署流程](#部署流程)
4. [问题排查与解决](#问题排查与解决)
5. [模型供应商配置](#模型供应商配置)
6. [转录服务配置](#转录服务配置)
7. [代理配置](#代理配置)
8. [常见问题](#常见问题)

---

## 系统概述

**BiliNote** 是一款 AI 视频笔记生成工具，支持从多种视频平台（Bilibili、YouTube、抖音、快手等）提取内容并生成结构化 Markdown 笔记。

### 技术架构

| 层级 | 技术栈 | 说明 |
|------|--------|------|
| **前端** | React 19 + Vite + Tailwind + shadcn/ui | 响应式 UI，支持 Markdown 预览与思维导图 |
| **后端** | FastAPI + Python 3.11 | RESTful API，任务队列管理 |
| **转录引擎** | faster-whisper / bcut / kuaishou / groq | 多引擎支持，本地/云端可选 |
| **LLM 接口** | OpenAI SDK 兼容 | 支持自定义供应商 |
| **容器化** | Docker Compose + Nginx | 一键部署，生产就绪 |

### 核心工作流

```
用户提交 URL → 任务排队 → 视频下载 → 音频提取 → 
语音转录 → LLM 笔记生成 → 前端轮询展示
```

---

## 环境准备

### 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux (推荐 Ubuntu 22.04+) |
| Docker | 24.0+ |
| Docker Compose | 2.20+ |
| 内存 | ≥ 8GB（转录需要） |
| 存储 | ≥ 10GB（模型缓存） |
| FFmpeg | 系统依赖，视频处理必需 |

### 前置检查

```bash
# 检查 Docker 版本
docker --version
docker compose version

# 检查 FFmpeg
ffmpeg -version || sudo apt install ffmpeg
```

---

## 部署流程

### 步骤 1：获取代码

```bash
git clone <repository_url>
cd BiliNote
```

### 步骤 2：环境配置

```bash
# 复制环境模板
cp .env.example .env

# 编辑配置（关键参数）
vim .env
```

**`.env` 关键配置：**

```ini
# 端口配置
BACKEND_PORT=8483
APP_PORT=3015

# 转录引擎（可选：fast-whisper, bcut, kuaishou, groq）
TRANSCRIBER_TYPE=bcut

# 模型大小（whisper 系列生效）
WHISPER_MODEL_SIZE=medium
```

### 步骤 3：构建与启动

```bash
docker compose up -d
```

### 步骤 4：验证服务

```bash
# 检查容器状态
docker ps

# 健康检查
curl http://localhost:3015/api/sys_health

# 查看日志
docker logs bilinote-backend
```

---

## 问题排查与解决

### 问题 1：Docker 镜像拉取失败

**现象：**
```
Error: Get "https://registry-1.docker.io/v2/": connection refused
```

**原因：** 国内网络无法直接访问 Docker Hub。

**解决方案：配置镜像加速器**

```bash
# 创建/修改 Docker daemon 配置
sudo tee /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ]
}
EOF

# 重启 Docker 服务
sudo systemctl restart docker

# 验证配置
docker info | grep -A 5 "Registry Mirrors"
```

---

### 问题 2：前端构建失败 - pnpm-lock.yaml 缺失

**现象：**
```
failed to compute cache key: "/BillNote_frontend/pnpm-lock.yaml": not found
```

**原因：** 项目未包含 pnpm lockfile，Docker 构建缓存机制失效。

**解决方案：生成 lockfile**

```bash
# 安装 pnpm（如未安装）
npm install -g pnpm

# 进入前端目录生成依赖锁定文件
cd BillNote_frontend
pnpm install
cd ..
```

---

### 问题 3：前端构建失败 - 原生模块兼容性

**现象：**
```
Cannot find native binding. @tailwindcss/oxide native binding error
```

**原因：** Alpine Linux 基础镜像缺少原生模块编译所需的工具链。

**解决方案：更换基础镜像**

修改 `BillNote_frontend/Dockerfile`：

```dockerfile
# 原配置（Alpine）
# FROM node:18-alpine AS builder

# 新配置（Debian Slim，更好的原生模块支持）
FROM node:18-slim AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

COPY ./BillNote_frontend/package.json ./BillNote_frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY ./BillNote_frontend/ ./
RUN pnpm run build

# 生产阶段保持 Alpine（仅静态文件，无编译需求）
FROM nginx:1.25-alpine
...
```

---

### 问题 4：Backend 启动失败 - ctranslate2 Executable Stack

**现象：**
```
ImportError: libctranslate2-bc15bf3f.so.4.5.0: 
cannot enable executable stack as shared object requires: Invalid argument
```

**原因：** `faster-whisper` 依赖的 `ctranslate2` 库需要 executable stack，Docker 默认安全策略禁止。

**解决方案：延迟导入策略**

修改 `backend/app/transcriber/transcriber_provider.py`，将导入改为延迟加载：

```python
# 原代码（启动时立即导入）
from app.transcriber.whisper import WhisperTranscriber
from app.transcriber.groq import GroqTranscriber
...

# 新代码（按需延迟导入）
def _init_transcriber(key, module_name, class_name, *args, **kwargs):
    module = __import__(f'app.transcriber.{module_name}', fromlist=[class_name])
    cls = getattr(module, class_name)
    return cls(*args, **kwargs)

def get_whisper_transcriber(model_size="base", device="cuda"):
    return _init_transcriber(TranscriberType.FAST_WHISPER, 'whisper', 'WhisperTranscriber', model_size, device)
```

**原理：** 仅在用户实际选择 `fast-whisper` 转录时才加载相关模块，避免启动时的安全策略冲突。其他转录引擎（bcut、kuaishou、groq）无此问题。

---

### 问题 5：.env 端口配置格式错误

**现象：** 端口映射异常或服务无法访问。

**原因：** `.env` 文件中端口值含空格。

**解决方案：**

```bash
# 错误格式
APP_PORT= 3015

# 正确格式
APP_PORT=3015
```

---

## 模型供应商配置

BiliNote 采用 **OpenAI SDK 兼容接口**，支持任意符合该规范的 LLM 供应商。

### 配置方式

**方式一：Web UI 配置**

访问 `http://localhost:3015` → 设置 → 模型供应商管理

**方式二：API 配置**

```bash
# 添加供应商
curl -X POST http://localhost:8483/api/add_provider \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Qwen-Bailian",
    "api_key": "sk-xxxxxxxx",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "logo": "Qwen",
    "type": "custom"
  }'

# 添加模型
curl -X POST http://localhost:8483/api/models \
  -H "Content-Type: application/json" \
  -d '{"provider_id":"<provider_id>","model_name":"qwen-plus"}'
```

### 常用供应商配置参考

| 供应商 | Base URL | 模型示例 |
|--------|----------|----------|
| **阿里云百炼** | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen-plus, qwen-turbo, qwen-max |
| **DeepSeek** | `https://api.deepseek.com` | deepseek-chat, deepseek-coder |
| **Groq** | `https://api.groq.com/openai/v1` | llama-3.3-70b, mixtral-8x7b |
| **OpenAI** | `https://api.openai.com/v1` | gpt-4, gpt-3.5-turbo |
| **本地 Ollama** | `http://127.0.0.1:11434/v1` | 自定义模型 |

### 连通性测试

```bash
curl -X POST http://localhost:8483/api/connect_test \
  -H "Content-Type: application/json" \
  -d '{"id":"<provider_id>"}'
```

---

## 转录服务配置

BiliNote 支持多种转录引擎，可动态切换：

| 类型 | 说明 | 适用场景 |
|------|------|----------|
| **fast-whisper** | 本地 faster-whisper，需 GPU 加速 | 高性能本地环境 |
| **bcut** | B站必剪在线服务（免费） | B站视频，无需本地资源 **（本次部署实际使用）** |
| **kuaishou** | 快手在线服务（免费） | 通用视频 |
| **groq** | Groq Whisper API（免费额度） | 需代理访问，API Key 验证后可用 |
| **mlx-whisper** | Apple Silicon 专用 | macOS 本地 |

### 配置与切换

```bash
# 查询当前配置
curl http://localhost:8483/api/transcriber_config

# 切换转录引擎
curl -X POST http://localhost:8483/api/transcriber_config \
  -H "Content-Type: application/json" \
  -d '{"transcriber_type":"bcut"}'
```

### 转录引擎故障排查

**bcut 返回 "第三方服务异常"：**

B站转录服务可能临时过载，等待后重试或切换其他引擎。**注意：这是本次部署实际使用的转录引擎，成功完成了视频转录。**

**kuaishou 返回 "效果subtitle_generate禁用"：**

快手服务策略变更，建议切换 bcut 或 groq。

**groq 返回 403 Forbidden：**

1. 检查 API Key 是否有效（本次部署中 Groq Key 验证失败，最终使用 bcut 完成）
2. 确认代理配置正确（见下节）
3. 如 Groq 不可用，优先推荐 bcut（免费、无需本地资源）

---

## 代理配置

### 问题背景

部分服务（Groq、OpenAI 等）需要通过代理访问。Docker 容器默认无法使用宿主机代理。

**注：本次部署配置了代理，但 Groq API Key 验证失败（403 Forbidden），最终使用 bcut 完成转录。代理配置保留供后续使用其他需要代理的服务。**

### 解决方案

#### 步骤 1：配置 Clash 允许局域网访问

```bash
# 检查 Clash 监听状态
netstat -tlnp | grep 7897

# 若显示 127.0.0.1:7897，需修改配置
sed -i 's/allow-lan: false/allow-lan: true/' \
  ~/.local/share/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml

# 重载配置
pkill -HUP verge-mihomo

# 验证（应显示 :::7897）
netstat -tlnp | grep 7897
```

#### 步骤 2：配置 Docker Compose 使用代理

修改 `docker-compose.yml`：

```yaml
services:
  backend:
    environment:
      - HTTP_PROXY=http://host.docker.internal:7897
      - HTTPS_PROXY=http://host.docker.internal:7897
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

#### 步骤 3：重建容器

```bash
docker compose down && docker compose up -d
```

#### 步骤 4：验证代理

```bash
# 容器内测试代理连通性
docker exec bilinote-backend curl -v --proxy http://host.docker.internal:7897 https://www.google.com

# 测试 Groq API
docker exec bilinote-backend curl --proxy http://host.docker.internal:7897 \
  https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer <your_api_key>"
```

---

## 常见问题

### Q1：笔记生成长时间处于 DOWNLOADING 状态？

**排查：**
```bash
docker logs bilinote-backend | grep -E "download|Download"
```

可能原因：
- 视频源网络问题
- 平台限速（B站需 Cookie）

### Q2：转录结果为空或乱码？

**排查：**
1. 确认音频文件存在：`ls /app/data/data/*.mp3`
2. 检查转录引擎日志
3. 尝试切换其他转录引擎

### Q3：LLM 生成笔记失败？

**排查：**
```bash
# 检查模型配置
curl http://localhost:8483/api/model_list

# 测试供应商连通性
curl -X POST http://localhost:8483/api/connect_test -d '{"id":"<provider_id>"}'
```

### Q4：向量索引超时不影响笔记？

日志显示 `向量索引失败...The read operation timed out` 属于正常警告，向量索引用于 AI 问答功能，不影响笔记生成。

### Q5：如何持久化数据？

关键数据目录：
- `backend/app/db/bili_note.db` - SQLite 数据库（供应商、模型配置）
- `backend/note_results/` - 生成的笔记文件
- `backend/static/screenshots/` - 视频截图

建议配置 Docker Volume 挂载：

```yaml
volumes:
  - ./backend/data:/app/data
  - ./backend/note_results:/app/note_results
```

---

## 附录：完整部署清单

```bash
# 1. Docker 镜像加速
sudo tee /etc/docker/daemon.json << 'EOF'
{"registry-mirrors": ["https://docker.1ms.run"]}
EOF
sudo systemctl restart docker

# 2. 生成前端依赖锁定
cd BillNote_frontend && pnpm install && cd ..

# 3. 环境配置
cp .env.example .env
# 编辑 .env，确认 APP_PORT 无空格

# 4. Clash 代理（如需使用 Groq/OpenAI）
sed -i 's/allow-lan: false/allow-lan: true/' ~/.local/share/.../clash-verge.yaml
pkill -HUP verge-mihomo

# 5. 启动服务
docker compose up -d

# 6. 配置 LLM 供应商（示例：阿里云百炼）
curl -X POST http://localhost:8483/api/add_provider \
  -d '{"name":"Qwen","api_key":"sk-xxx","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","type":"custom"}'
curl -X POST http://localhost:8483/api/models \
  -d '{"provider_id":"<id>","model_name":"qwen-plus"}'

# 7. 配置转录引擎（本次使用 bcut，成功）
curl -X POST http://localhost:8483/api/transcriber_config \
  -d '{"transcriber_type":"bcut"}'

# 8. 验证
curl http://localhost:3015/api/sys_health
```

---

## 结语

本指南覆盖了 BiliNote 从环境准备到生产部署的完整流程，重点解决了国内网络环境下的常见问题。

**本次部署实际配置：**
- 转录引擎：bcut（B站必剪在线服务）
- LLM 供应商：阿里云百炼（qwen-plus）
- 代理：Clash（端口 7897），已配置但 Groq 未成功使用

如有其他问题，请查阅项目 CLAUDE.md 或提交 Issue。

---

*文档版本：2026-04-21*  
*适用版本：BiliNote v1.x*