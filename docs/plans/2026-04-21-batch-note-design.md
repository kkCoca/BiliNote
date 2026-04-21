# 批量笔记生成设计文档

> URL 探测 → 视频列表预览 → 批量提交 → 进度追踪，让 BiliNote 支持从博主主页、合集等 URL 批量生成笔记。

**创建日期：** 2026-04-21  
**状态：** 已确认

---

## TL;DR

用户粘贴任意 B站 URL（博主主页、合集、播放列表），系统先探测 URL 包含多少个视频，展示视频列表供筛选，勾选后批量生成笔记，全程可看到每个子任务进度。

## 架构

```
用户粘贴 URL
  → POST /api/detect_url
    → 判断 single / multi
      → single: 走现有 generate_note 流程
      → multi: 弹出预览面板 → 勾选 → POST /api/generate_batch_note
        → 创建 batch_id → 逐个提交到现有任务管道

状态文件:
  task_{task_id}.json     # 单个任务状态（复用现有）
  batch_{batch_id}.json   # 批次聚合状态（新增）
```

---

## URL 检测（后端）

### 接口

```
POST /api/detect_url
Body: {"url": "https://..."}
Response:
{
  "type": "single" | "multi",
  "entries": [
    {"video_id": "BVxxx", "title": "...", "duration": 300, "thumbnail": "http://..."},
    ...
  ]
}
```

### 实现

```python
# backend/app/utils/url_detector.py

import yt_dlp
from typing import List, Dict, Any

class UrlDetector:
    def detect(self, url: str) -> Dict[str, Any]:
        opts = {
            'flat': True,
            'extract_flat': True,
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': {'skip': ['dash']}},
        }

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = []
        for e in info.get('entries', []):
            video_id = e.get('id', '')
            title = e.get('title', '未知')
            duration = e.get('duration', 0)
            thumbnail = e.get('thumbnail', '')
            entries.append({
                'video_id': video_id,
                'title': title,
                'duration': duration,
                'thumbnail': thumbnail,
            })

        if len(entries) <= 1:
            return {'type': 'single', 'entries': entries}
        return {'type': 'multi', 'entries': entries}
```

### 边界情况

| 情况 | 处理 |
|------|------|
| 单视频 URL | entries 为空或只有 1 项，type=single |
| 博主主页 | 返回所有公开视频 |
| 合集/列表 | 返回列表内视频 |
| 搜索结果 | 支持 ytsearch: 格式 |
| 404 / 无效 | 抛出异常，前端提示 |

---

## 批量任务追踪（后端）

### 接口

```
POST /api/generate_batch_note
Body: {
  "video_ids": ["BV1", "BV2", ...],
  "platform": "bilibili",
  "quality": "medium",
  "model_name": "qwen-plus",
  "provider_id": "xxx"
}
Response: {
  "batch_id": "uuid",
  "task_map": [{"video_id": "BV1", "task_id": "uuid"}, ...]
}

GET /api/batch_status/{batch_id}
Response: {
  "batch_id": "uuid",
  "total": 25,
  "completed": 12,
  "failed": 1,
  "tasks": {
    "task_id_1": {"video_id": "BV1", "status": "success"},
    "task_id_2": {"video_id": "BV2", "status": "failed", "error": "..."},
  },
  "created_at": "2026-04-21T..."
}
```

### 状态文件

```json
{
  "batch_id": "uuid",
  "total": 25,
  "completed": 12,
  "failed": 1,
  "tasks": {
    "task_id_xxx": {"video_id": "BV1", "status": "success"},
    "task_id_yyy": {"video_id": "BV2", "status": "failed", "error": "转录失败"}
  },
  "created_at": "...",
  "updated_at": "..."
}
```

### 进度更新

- 每个子任务完成时，更新 `batch_{batch_id}.json`
- `completed` = status=success 的数量
- `failed` = status=failed 的数量

---

## 前端组件

### 新增文件

| 文件 | 作用 |
|------|------|
| `src/components/BatchProgress.tsx` | 批量进度展示组件 |
| `src/hooks/useBatchPolling.ts` | 批量任务轮询 hook |
| `src/services/batch.ts` | 批量 API 客户端 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `src/pages/HomePage/components/NoteForm.tsx` | 加 detect 调用 + 预览面板 |
| `src/store/taskStore.ts` | 加 batch 状态追踪 |
| `src/pages/HomePage/index.tsx` | 批量进度展示区域 |

### NoteForm 改动要点

```typescript
// 伪代码

// 用户粘贴 URL 后自动探测
const handleUrlDetect = async (url: string) => {
  const result = await detectUrl({ url })
  if (result.type === 'multi') {
    setShowPreview(true)
    setVideoEntries(result.entries)
  } else {
    // 单视频，直接提交
    handleSubmit()
  }
}

// 预览面板
// - 列表展示视频（标题、时长、缩略图）
// - 全选/取消按钮
// - 搜索过滤
// - 确认后调用 generateBatchNote
```

### BatchProgress 组件要点

```typescript
// 进度条：completed / total * 100%
// 子任务列表：
//   [✓] 视频标题 → 链接到笔记
//   [✗] 视频标题 → 失败原因
//   [..] 视频标题 → 正在处理中
// 全部完成后的操作：
//   查看全部笔记
//   重试失败的视频
```

---

## 错误处理

| 场景 | 行为 |
|------|------|
| 某个视频转录失败 | 标记失败，继续下一个 |
| LLM API 限流 | 延迟重试，记录重试次数 |
| url_detect 超时 | 前端提示"探测超时，请重试" |
| 网络断开 | 任务中断，下次可从 batch_status 恢复 |
| 无效 URL | 前端提示，不提交 |

---

## 新增文件清单

### 后端

```
backend/app/utils/url_detector.py          # URL 探测工具
backend/app/routers/batch.py               # 批量任务路由
backend/app/services/batch_manager.py      # 批量状态管理
backend/app/models/batch.py                # 批量数据模型
```

### 前端

```
src/components/BatchProgress.tsx           # 批量进度组件
src/components/VideoPreview.tsx            # 视频预览选择面板
src/hooks/useBatchPolling.ts               # 批量轮询 hook
src/services/batch.ts                      # 批量 API 客户端
src/store/batchStore.ts                    # 批量状态 store (Zustand)
```

---

## 接口清单

### 后端 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/detect_url` | 探测 URL 类型和视频列表 |
| POST | `/api/generate_batch_note` | 批量提交笔记生成 |
| GET | `/api/batch_status/{batch_id}` | 查询批量任务进度 |
| POST | `/api/batch_retry/{batch_id}` | 重试失败的子任务 |

### 前端 API 客户端

```typescript
// src/services/batch.ts

export const detectUrl = (data: DetectRequest) => axios.post('/api/detect_url', data)
export const generateBatchNote = (data: BatchRequest) => axios.post('/api/generate_batch_note', data)
export const getBatchStatus = (batchId: string) => axios.get(`/api/batch_status/${batchId}`)
export const batchRetry = (batchId: string, failedVideoIds: string[]) =>
  axios.post(`/api/batch_retry/${batchId}`, { video_ids: failedVideoIds })
```

---

## 任务执行流程

```
detect_url → [预览] → generate_batch_note
  ↓
创建 batch_id → batch_{batch_id}.json
  ↓
循环每个 video_id:
  ↓
  生成 task_id → 提交到现有 task_serial_executor
  ↓
  每个 task 完成 → 更新 batch_status.json
  ↓
前端轮询 batch_status → 显示进度
```

---

## 测试策略

**测试文件：**

| 文件 | 内容 |
|------|------|
| `tests/test_url_detector.py` | URL 检测逻辑 |
| `tests/test_batch_manager.py` | 批次状态管理 |
| `tests/test_batch_route.py` | API 路由 |
| `tests/test_batch_polling.tsx` | 前端轮询 |
| `tests/test_batch_progress.tsx` | UI 渲染 |

**关键测试用例：**

1. 单视频 URL → type=single → 走现有流程
2. 博主主页 → type=multi → entries > 0
3. 批量提交 → 每个 video_id 对应一个 task_id
4. 批次进度 → 子任务完成实时更新
5. 部分失败 → completed + failed = 已处理数
6. 重试失败 → 只重跑失败的子任务

---

## UI 草图

```
┌─────────────────────────────────────────────┐
│  视频链接                                  │
│  ┌──────────────────────────────────────┐   │
│  │ https://space.bilibili.com/312...    │   │
│  └──────────────────────────────────────┘   │
│                                               │
│  [模型选择] [转录方式] [生成按钮]              │
│                                               │
│  ───────── 自动检测 ─────────                 │
│  检测到 25 个视频                              │
│                                               │
│  ┌── 视频预览 ───────────────────────────┐   │
│  │ [☑] 全部选择                          │   │
│  │ ┌──────┬──────────────────────┬─────┐  │   │
│  │ │ 缩略图 │ 标题1          15:32 │ [☑] │  │   │
│  │ │ 缩略图 │ 标题2          12:05 │ [☑] │  │   │
│  │ │ 缩略图 │ 标题3           8:30 │ [☐] │  │   │
│  │ └──────┴──────────────────────┴─────┘  │   │
│  │ 已选 23/25                              │   │
│  └───────────────────────────────────────┘   │
│                                               │
│            [生成笔记 (23个视频)]                │
└─────────────────────────────────────────────┘

批量进度：
┌─────────────────────────────────────────────┐
│ ████████████░░░░░░░░░░░  12/25 已完成        │
│                                              │
│ ✓ 视频1  [查看笔记]     ✓ 视频7              │
│ ✓ 视频2                 ✗ 视频8 重试失败    │
│ ⋯ 视频3  处理中          ✓ 视频9              │
└─────────────────────────────────────────────┘
```

---

*2026-04-21 · BiliNote v1.x · 方案 A+B 结合*