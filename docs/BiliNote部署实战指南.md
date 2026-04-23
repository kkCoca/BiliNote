# BiliNote 部署实战：7 个坑，一份能跑通的记录

> **懒人方法：** 把这篇文章丢给 AI 编程助手（OpenCode CLI、Claude Code 都行），它会自动帮你装好。读文档、跑命令、改配置、启服务，不用你动手。

这是我们在 Linux 上装 BiliNote 的完整过程。踩了 7 个坑，都记下来了。你可以照着做，也可以直接把文档给 AI 工具让它自己装。

---

## 先看效果

装完后打开 `http://你的IP:3015`，粘贴视频链接：

```
https://www.bilibili.com/video/BV1hAcUzzETk/
```

等几分钟就出笔记了。下面是一份真实输出：

```markdown
> 来源链接：https://www.bilibili.com/video/BV1hAcUzzETk/

## 1. 港口概况：宁波舟山港  
- 全球货物吞吐量第一大港；  
- 日均吞吐量达 12 万个标准集装箱（TEU）；  
- 港区航道平均水深 22.5 米，相当于约 10 个西湖深度；  
- 满载集装箱船吃水可达 16–17 米，对水深要求极高；  
- 每日进出货轮约 300 艘，单次靠泊/离泊最快仅需 40 分钟。

## 2. 核心装卸设备与操作  
- 桥吊（Quay Crane）：价值超 5000 万元，用于集装箱吊装；  
- 桥吊司机需在 50 米高空、强风晃动中，凭肉眼完成精准定位；  
- 熟练司机（吴师傅）日均装卸 400+ 个集装箱；  
- 实际操作采用"惯性抛物线轨迹"而非直上直下，效率更高；  
- 类比：等效于将夹娃娃机放大数千倍，且悬于高空剧烈摆动。

## 3. 引航系统：海上"空中交通管制"  
- 引航员是船舶进港的唯一法定指挥者；  
- 全国持证引航员仅 2500 余人，少于大熊猫数量；  
- 需协同拖轮完成微操靠泊：  
  - 船无刹车，依赖拖轮缆绳拉拽与顶推；  
  - 雾天能见度低至 2–3 米；  
  - 上船方式类似"空间站对接"：引航艇保持同速贴近，攀软梯登轮；  
- 海上浪高动态变化，瞬时失衡容易出事故。

## 4. 集装箱与货物规模  
- 最大集装箱船载箱量：24,000 TEU；  
- 按均价 30 万元/TEU 计算，单船货值约 72 亿元；  
- 单个集装箱原材料可支撑一家内裤厂全年生产；  
- 港口货物覆盖极广：零食、内衣、汽车、电视、冰箱、跑车（曾吊运整车超跑），乃至航母部件。

## 5. 智能化与技术创新  
- 无人集卡：已投入堆场作业，取消驾驶室，保留"福"字垫子等细节；  
- 水下机器人 + 空化射流清洗技术：  
  - 源自潜艇维护，利用空化气泡破裂产生微射流冲击，清除藤壶等顽固附着物；  
- 方太 V18 MAX 洗碗机应用了同样的原理，实测可清除红油、焦糊、锅底包浆、多年重油污等顽固污渍。

## 6. 运作模式：24 小时不间断  
- 白天以人工桥吊为主，夜间转向远控与自动化设备；  
- 全流程体现"贸易实体化"：全球需求 → 货物汇聚 → 高效分发。
```

转录花了 11 秒，笔记生成约 1 分钟。视频长度约 5 分钟。

---

## 准备什么

假设你：

- 会用 Linux 命令行
- 知道 Docker 和 Docker Compose 是什么
- 有一个 LLM API Key（我们用阿里云百炼）

硬件：

| 项目 | 要求 |
|------|------|
| 内存 | 8GB |
| 存储 | 10GB |
| 系统 | Ubuntu 22.04 或类似发行版 |

你需要提前准备好：

1. LLM API Key（阿里云百炼、DeepSeek 都行，下面用阿里云举例）
2. 代理（可选，用 Groq 或 OpenAI 才需要）

---

## 开始装

### 1. 配 Docker 镜像源

国内直接拉 Docker Hub 会失败。先改镜像源：

```bash
sudo tee /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ]
}
EOF

sudo systemctl restart docker
```

验证一下：

```bash
docker info | grep -A 3 "Registry Mirrors"
```

应该能看到你配的镜像地址。

---

### 2. 拉代码，生成前端依赖

```bash
git clone https://github.com/kkCoca/BiliNote.git
cd BiliNote
```

**坑 1：** 直接 `docker compose up` 会报错 `pnpm-lock.yaml not found`。项目没带 lockfile。

**修法：** 手动跑一次：

```bash
npm install -g pnpm

cd BillNote_frontend
pnpm install
cd ..
```

---

### 3. 改前端 Dockerfile

**坑 2：** 前端构建报错 `Cannot find native binding. @tailwindcss/oxide error`。原 Dockerfile 用的 Alpine 镜像，缺少编译工具链，tailwindcss 的原生模块编译不过。

**修法：** 把构建镜像改成 Debian Slim。

改 `BillNote_frontend/Dockerfile`：

```dockerfile
# === 前端构建 ===
FROM node:18-slim AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

COPY ./BillNote_frontend/package.json ./BillNote_frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY ./BillNote_frontend/ ./
RUN pnpm run build

# === 生产 ===
FROM nginx:1.25-alpine

RUN rm -rf /etc/nginx/conf.d/default.conf
COPY ./BillNote_frontend/deploy/default.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html
```

生产阶段可以保持 Alpine，只放静态文件，不用再编译。

---

### 4. 改后端转录器导入

**坑 3：** 后端启动报错：

```
ImportError: libctranslate2-xxx.so: cannot enable executable stack
```

faster-whisper 依赖 ctranslate2，这个库需要 executable stack，Docker 默认不允许。

**修法：** 让转录器延迟导入。启动时不加载 faster-whisper，选的时候才加载。

改 `backend/app/transcriber/transcriber_provider.py`：

把原来的：

```python
from app.transcriber.whisper import WhisperTranscriber
from app.transcriber.groq import GroqTranscriber
from app.transcriber.bcut import BcutTranscriber
from app.transcriber.kuaishou import KuaishouTranscriber
```

替换成：

```python
import os
import platform
from enum import Enum

from app.utils.logger import get_logger

logger = get_logger(__name__)

class TranscriberType(str, Enum):
    FAST_WHISPER = "fast-whisper"
    MLX_WHISPER = "mlx-whisper"
    BCUT = "bcut"
    KUAISHOU = "kuaishou"
    GROQ = "groq"

# Apple 平台尝试导入 MLX Whisper
MLX_WHISPER_AVAILABLE = False
if platform.system() == "Darwin":
    try:
        from app.transcriber.mlx_whisper_transcriber import MLXWhisperTranscriber
        MLX_WHISPER_AVAILABLE = True
        logger.info("MLX Whisper 可用")
    except ImportError:
        logger.warning("MLX Whisper 导入失败")

# 转录器单例缓存
_transcribers = {}

def _init_transcriber(key, module_name, class_name, *args, **kwargs):
    if _transcribers.get(key) is None:
        logger.info(f'创建 {class_name}')
        module = __import__(f'app.transcriber.{module_name}', fromlist=[class_name])
        cls = getattr(module, class_name)
        _transcribers[key] = cls(*args, **kwargs)
    return _transcribers[key]

def get_whisper_transcriber(model_size="base", device="cuda"):
    return _init_transcriber(
        TranscriberType.FAST_WHISPER,
        'whisper', 'WhisperTranscriber',
        model_size=model_size, device=device
    )

def get_groq_transcriber():
    return _init_transcriber(TranscriberType.GROQ, 'groq', 'GroqTranscriber')

def get_bcut_transcriber():
    return _init_transcriber(TranscriberType.BCUT, 'bcut', 'BcutTranscriber')

def get_kuaishou_transcriber():
    return _init_transcriber(TranscriberType.KUAISHOU, 'kuaishou', 'KuaishouTranscriber')

def get_mlx_whisper_transcriber(model_size="base"):
    if not MLX_WHISPER_AVAILABLE:
        raise ImportError("MLX Whisper 不可用")
    return _init_transcriber(
        TranscriberType.MLX_WHISPER,
        'mlx_whisper_transcriber', 'MLXWhisperTranscriber',
        model_size=model_size
    )
```

这样 bcut、kuaishou 这些不需要 ctranslate2 的转录器可以正常用。选 fast-whisper 时才会加载相关库。

---

### 5. 配环境变量

```bash
cp .env.example .env
```

**坑 4：** `.env` 里端口值如果有空格，服务会出问题。

```ini
# 对的
BACKEND_PORT=8483
APP_PORT=3015

# 错的（等号后面有空格）
BACKEND_PORT= 8483
APP_PORT= 3015
```

---

### 6. 启动

```bash
docker compose up -d
```

首次构建要等 5-10 分钟。

检查：

```bash
docker ps
# 应该看到 3 个容器：bilinote-backend, bilinote-frontend, bilinote-nginx

curl http://localhost:3015/api/sys_health
# 返回 {"code":0,"msg":"success","data":null} 就对了
```

---

## 配 LLM

### 界面配（推荐）

打开 `http://你的IP:3015` → 设置 → 模型供应商 → 添加。填好 API Key 和地址就行。

### 命令行配

我们用阿里云百炼：

```bash
# 加供应商
curl -X POST http://localhost:8483/api/add_provider \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Qwen-Bailian",
    "api_key": "sk-你的API Key",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "logo": "Qwen",
    "type": "custom"
  }'
```

会返回一个 provider_id，记下来。然后加模型：

```bash
curl -X POST http://localhost:8483/api/models \
  -H "Content-Type: application/json" \
  -d '{
    "provider_id": "你拿到的provider_id",
    "model_name": "qwen-plus"
  }'
```

其他供应商的地址：

| 供应商 | Base URL | 模型 |
|--------|----------|------|
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen-plus, qwen-turbo, qwen-max |
| DeepSeek | `https://api.deepseek.com` | deepseek-chat |
| OpenAI | `https://api.openai.com/v1` | gpt-4o, gpt-3.5-turbo |
| Groq | `https://api.groq.com/openai/v1` | llama-3.3-70b |

---

## 选转录引擎

BiliNote 有几个转录引擎可选：

| 类型 | 说明 | 适合谁 |
|------|------|--------|
| bcut | B站必剪，在线服务 | 国内首选，免费 |
| kuaishou | 快手，在线服务 | 通用，免费 |
| groq | Groq Whisper API | 要代理，有免费额度 |
| fast-whisper | 本地 Whisper | 有 GPU 的 |

我们用的 bcut。免费，国内不用代理，B站视频支持好。

```bash
curl -X POST http://localhost:8483/api/transcriber_config \
  -H "Content-Type: application/json" \
  -d '{"transcriber_type":"bcut"}'
```

**坑 5：** bcut 偶尔会返回"第三方服务异常"，是 B站那边的问题。等一会再试，或者换 kuaishou。

---

## 代理（给用 Groq 或 OpenAI 的人）

我们试了 Groq，API Key 报 403 没成功。下面是代理配置，如果你用的服务需要代理可以参考。

### 让 Clash 监听局域网

```bash
# 查看当前监听
netstat -tlnp | grep 7897

# 如果显示 127.0.0.1:7897，说明只监听本机

# 改成允许局域网
sed -i 's/allow-lan: false/allow-lan: true/' \
  ~/.local/share/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml

# 重载
pkill -HUP verge-mihomo

# 再看，应该显示 :::7897
netstat -tlnp | grep 7897
```

### 给 Docker 容器配代理

改 `docker-compose.yml`，在 `backend` 服务加几行：

```yaml
backend:
  environment:
    - HTTP_PROXY=http://host.docker.internal:7897
    - HTTPS_PROXY=http://host.docker.internal:7897
  extra_hosts:
    - "host.docker.internal:host-gateway"
```

然后重建：

```bash
docker compose down && docker compose up -d
```

验证：

```bash
docker exec bilinote-backend curl --proxy http://host.docker.internal:7897 https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer 你的APIKey"
```

---

## 完整命令清单

不想看上面的，直接跑这些：

```bash
# 1. Docker 镜像源
sudo tee /etc/docker/daemon.json << 'EOF'
{"registry-mirrors": ["https://docker.1ms.run"]}
EOF
sudo systemctl restart docker

# 2. 拉代码 + 前端依赖
git clone https://github.com/kkCoca/BiliNote.git && cd BiliNote
npm install -g pnpm
cd BillNote_frontend && pnpm install && cd ..

# 3. 修改 Dockerfile（见上文步骤3）
# 4. 修改转录器导入（见上文步骤4）

# 5. 环境变量
cp .env.example .env
# 确保 BACKEND_PORT 和 APP_PORT 等号后面没有空格

# 6. 启动
docker compose up -d

# 7. 配置 LLM（阿里云百炼）
curl -X POST http://localhost:8483/api/add_provider \
  -d '{"name":"Qwen","api_key":"sk-xxx","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","type":"custom"}'
curl -X POST http://localhost:8483/api/models \
  -d '{"provider_id":"拿到的id","model_name":"qwen-plus"}'

# 8. 配转录引擎
curl -X POST http://localhost:8483/api/transcriber_config \
  -d '{"transcriber_type":"bcut"}'

# 9. 完成
curl http://localhost:3015/api/sys_health
```

---

## 结果

测试视频：宁波舟山港介绍，BV1hAcUzzETk。

日志节选：

```
[BiliBili] BV1hAcUzzETk: Downloading audio...
[ExtractAudio] Destination: BV1hAcUzzETk.mp3
[INFO] app.transcriber.bcut - 申请上传成功, 11分片
[INFO] app.transcriber.bcut - 转录成功
transcript executed in 11.18 seconds
状态: TaskStatus.SUCCESS
```

生成的笔记有条理的章节、要点、数据。

遇到问题看日志：

```bash
docker logs bilinote-backend --tail 50
```

---

## 坑位速查

| 坑 | 怎么避 |
|----|--------|
| Docker 拉不下来 | 配镜像源 |
| pnpm-lock.yaml 缺 | 先跑 `pnpm install` |
| 前端构建报 native binding | Dockerfile 改 `node:18-slim` |
| ctranslate2 executable stack | 转录器延迟导入 |
| .env 端口有空格 | 检查等号后面 |
| bcut 报第三方服务异常 | 等一会或换引擎 |
| Groq 403 | 检查 Key，或用 bcut |

我们实际跑通的组合：

| 组件 | 用的什么 |
|------|----------|
| 转录 | bcut |
| LLM | 阿里云百炼 qwen-plus |
| 端口 | 3015 |
| 代理 | Clash 7897（备着，这次没用上） |

---

*2026-04-21*  
*BiliNote v1.x · Ubuntu 22.04 · Docker 24.0*
