# 批量笔记生成实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 BiliNote 支持从博主主页、合集等 URL 批量生成笔记

**架构：** URL 探测 → 视频预览 → 批量提交 → 进度追踪，新增 2 个 API 端点 + 前端批量进度组件

**Tech Stack：** Python yt-dlp, FastAPI, React + TypeScript, Zustand

---

### Task 1: 后端 URL 探测工具

**Files:**
- Create: `backend/app/utils/url_detector.py`
- Test: `backend/tests/test_url_detector.py`

**要点：**
```python
def detect_url(url: str) -> dict:
    # 用 yt-dlp flat 模式
    # 返回 {"type": "single"/"multi", "entries": [...]}
```

---

### Task 2: 后端批量 API 路由

**Files:**
- Create: `backend/app/routers/batch.py`
- Modify: `backend/app/main.py` (注册路由)

**新接口：**
```python
POST /api/detect_url          # 探测 URL
POST /api/generate_batch_note # 批量提交
GET  /api/batch_status/{batch_id}  # 查询进度
```

---

### Task 3: 后端批量状态管理

**Files:**
- Create: `backend/app/services/batch_manager.py`

**要点：**
- 创建 `batch_{batch_id}.json` 状态文件
- 批量任务完成后自动更新进度
- 支持失败重试

---

### Task 4: 前端批量 API 服务

**Files:**
- Create: `BillNote_frontend/src/services/batch.ts`

**API 客户端：**
```typescript
export const detectUrl = (url: string) => axios.post('/api/detect_url', { url })
export const generateBatchNote = (data) => axios.post('/api/generate_batch_note', data)
export const getBatchStatus = (batchId: string) => axios.get(`/api/batch_status/${batchId}`)
```

---

### Task 5: 前端视频预览面板

**Files:**
- Create: `BillNote_frontend/src/components/VideoPreview.tsx`
- Modify: `BillNote_frontend/src/pages/HomePage/components/NoteForm.tsx`

**要点：**
- 粘贴 URL 后自动调用 detect_url
- multi 类型时弹出预览
- 勾选/取消、搜索过滤

---

### Task 6: 前端批量进度组件

**Files:**
- Create: `BillNote_frontend/src/components/BatchProgress.tsx`
- Create: `BillNote_frontend/src/hooks/useBatchPolling.ts`
- Modify: `BillNote_frontend/src/store/taskStore.ts`

**要点：**
- 进度条 + 子任务列表
- 轮询 batch_status
- 失败重试

---

### Task 7: 测试验证

**Files:**
- `backend/tests/test_url_detector.py`
- `backend/tests/test_batch_routes.py`

**测试内容：**
- 单视频 URL → type=single
- 博主主页 → type=multi, entries > 0
- 批量提交 → n 个 task_id
- 进度更新

---

**总任务数：7 个**  
**预估时间：3-5 小时**
