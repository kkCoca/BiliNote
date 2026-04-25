# 视频合集笔记历史分组 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将视频合集链接生成的多个子视频笔记在历史列表中按合集分组展示，并支持合集级查看、删除和子视频级查看、删除。

**Architecture:** 复用现有 batch JSON 作为合集父级存储，不新增 course 表。后端补齐 batch 列表、batch 详情、合集删除和子任务删除能力；前端在历史列表中把普通单视频任务平铺展示，把带 `batchId` 的任务聚合到合集父项下。

**Tech Stack:** FastAPI + Pydantic + JSON file persistence + SQLAlchemy DAO；React 19 + TypeScript + Zustand + Vite + shadcn/ui。

---

## Guardrails

- 用户已确认设计文档：`docs/plans/2026-04-25-batch-course-history-design.md`。
- 用户选择暂不提交设计文档，所以执行时不要自动提交当前设计文档，除非用户再次明确要求。
- 当前工作区已有大量未提交改动；执行前必须先运行 `git status --short`，只修改本计划列出的文件，避免覆盖无关工作。
- 删除接口必须由后端负责清理 DB 与文件；前端只在接口成功后更新本地状态。
- 单视频任务不能因为这次改造改变展示、查看和删除行为。

---

### Task 1: Backend batch summary and single child deletion

**Files:**
- Modify: `backend/app/services/batch_manager.py`
- Test: `backend/tests/test_batch_manager.py`

**Step 1: Write failing tests for listing batches**

Add this test method to `TestBatchManager` in `backend/tests/test_batch_manager.py`:

```python
def test_list_batches_returns_course_summaries(self):
    _reset_app_modules()
    from app.services.batch_manager import BatchManager

    with tempfile.TemporaryDirectory() as td:
        mgr = BatchManager(output_dir=td)
        entries = [
            {'video_url': 'u1', 'video_id': 'BV1', 'title': '第一节', 'thumbnail': 'thumb1', 'duration': 10, 'order': 0},
            {'video_url': 'u2', 'video_id': 'BV2', 'title': '第二节', 'thumbnail': 'thumb2', 'duration': 20, 'order': 1},
        ]
        batch_id = mgr.create_batch(entries, source_url='https://space.bilibili.com/1/upload/video', title='测试课程')
        mgr.register_task(batch_id, 'task-1', entries[0])
        mgr.register_task(batch_id, 'task-2', entries[1])

        with open(f'{td}/task-1.status.json', 'w', encoding='utf-8') as f:
            json.dump({'status': 'SUCCESS', 'message': ''}, f)
        with open(f'{td}/task-2.status.json', 'w', encoding='utf-8') as f:
            json.dump({'status': 'PENDING', 'message': ''}, f)

        summaries = mgr.list_batches()

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]['batch_id'], batch_id)
        self.assertEqual(summaries[0]['title'], '测试课程')
        self.assertEqual(summaries[0]['total'], 2)
        self.assertEqual(summaries[0]['completed'], 1)
        self.assertEqual(summaries[0]['failed'], 0)
        self.assertEqual(summaries[0]['running'], 1)
        self.assertEqual(summaries[0]['status'], 'RUNNING')
        self.assertEqual(summaries[0]['cover_url'], 'thumb1')
```

**Step 2: Write failing tests for deleting one child task**

Add this test method to `TestBatchManager`:

```python
def test_delete_task_from_batch_removes_child_and_updates_stats(self):
    with tempfile.TemporaryDirectory() as td:
        db_path = pathlib.Path(td) / 'test.db'
        old_output_dir = os.environ.get('NOTE_OUTPUT_DIR')
        old_database_url = os.environ.get('DATABASE_URL')
        os.environ['NOTE_OUTPUT_DIR'] = td
        os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'

        try:
            _reset_app_modules()
            from app.db.init_db import init_db
            from app.db.video_task_dao import get_task_by_video, insert_video_task
            from app.services.batch_manager import BatchManager

            init_db()

            mgr = BatchManager(output_dir=td)
            entries = [
                {'video_url': 'u1', 'video_id': 'BV1', 'title': '第一节', 'thumbnail': 'thumb1', 'duration': 10, 'order': 0},
                {'video_url': 'u2', 'video_id': 'BV2', 'title': '第二节', 'thumbnail': 'thumb2', 'duration': 20, 'order': 1},
            ]
            batch_id = mgr.create_batch(entries, source_url='source', title='测试课程')
            mgr.register_task(batch_id, 'task-1', entries[0])
            mgr.register_task(batch_id, 'task-2', entries[1])

            for task_id, video_id in [('task-1', 'BV1'), ('task-2', 'BV2')]:
                with open(f'{td}/{task_id}.status.json', 'w', encoding='utf-8') as f:
                    json.dump({'status': 'SUCCESS', 'message': ''}, f)
                with open(f'{td}/{task_id}.json', 'w', encoding='utf-8') as f:
                    json.dump({'markdown': f'# {video_id}', 'audio_meta': {'title': video_id}}, f)
                insert_video_task(video_id, 'bilibili', task_id)

            deleted = mgr.delete_task_from_batch(batch_id, 'task-1')
            data = mgr.build_course_view(batch_id)

            self.assertEqual(deleted['batch_id'], batch_id)
            self.assertEqual(deleted['deleted_task_id'], 'task-1')
            self.assertFalse(pathlib.Path(td, 'task-1.json').exists())
            self.assertFalse(pathlib.Path(td, 'task-1.status.json').exists())
            self.assertIsNone(get_task_by_video('BV1', 'bilibili'))
            self.assertEqual([item['task_id'] for item in data['items']], ['task-2'])
            self.assertEqual(data['total'], 1)
            self.assertEqual(data['completed'], 1)
        finally:
            if old_output_dir is None:
                os.environ.pop('NOTE_OUTPUT_DIR', None)
            else:
                os.environ['NOTE_OUTPUT_DIR'] = old_output_dir

            if old_database_url is None:
                os.environ.pop('DATABASE_URL', None)
            else:
                os.environ['DATABASE_URL'] = old_database_url
```

**Step 3: Run tests and verify they fail**

Run:

```bash
python -m pytest backend/tests/test_batch_manager.py::TestBatchManager::test_list_batches_returns_course_summaries backend/tests/test_batch_manager.py::TestBatchManager::test_delete_task_from_batch_removes_child_and_updates_stats -v
```

Expected: FAIL because `BatchManager.list_batches` and `BatchManager.delete_task_from_batch` do not exist.

**Step 4: Implement batch summaries and child deletion**

Modify `backend/app/services/batch_manager.py`:

1. Add imports:

```python
from glob import glob
```

2. Add helper methods inside `BatchManager`:

```python
def _delete_task_artifacts(self, task_id: str) -> None:
    for path in self._task_artifact_paths(task_id):
        if os.path.exists(path):
            os.remove(path)

def _summary_from_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
    tasks = data.get('tasks', {}) or {}
    total = len(tasks)
    completed = int(data.get('completed', 0) or 0)
    failed = int(data.get('failed', 0) or 0)
    running = max(0, total - completed - failed)

    status = 'SUCCESS'
    if failed > 0 and completed + failed == total:
        status = 'FAILED'
    elif running > 0:
        status = 'RUNNING'
    elif total == 0:
        status = 'EMPTY'

    cover_url = data.get('cover_url', '') or ''
    if not cover_url:
        ordered_tasks = sorted(tasks.values(), key=lambda item: (item.get('order', 0), item.get('title', '')))
        cover_url = next((item.get('thumbnail', '') for item in ordered_tasks if item.get('thumbnail')), '')

    return {
        'batch_id': data.get('batch_id', ''),
        'title': data.get('title') or '视频合集',
        'source_url': data.get('source_url', '') or '',
        'cover_url': cover_url,
        'total': total,
        'completed': completed,
        'failed': failed,
        'running': running,
        'status': status,
        'created_at': data.get('created_at', '') or '',
        'updated_at': data.get('updated_at', '') or '',
    }
```

3. Add public methods:

```python
def list_batches(self) -> list[Dict[str, Any]]:
    summaries: list[Dict[str, Any]] = []
    for path in glob(os.path.join(self.output_dir, 'batch_*.json')):
        batch_id = os.path.basename(path)[len('batch_'):-len('.json')]
        try:
            data = self.refresh_from_task_status(batch_id)
            summaries.append(self._summary_from_data(data))
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.warning(f'Failed to summarize batch {batch_id}: {e}')

    summaries.sort(key=lambda item: item.get('updated_at') or item.get('created_at') or '', reverse=True)
    return summaries

def delete_task_from_batch(self, batch_id: str, task_id: str) -> Dict[str, Any]:
    data = self.refresh_from_task_status(batch_id)
    tasks = data.get('tasks', {}) or {}
    if task_id not in tasks:
        raise FileNotFoundError(task_id)

    delete_tasks_by_task_ids([task_id])
    self._delete_task_artifacts(task_id)
    tasks.pop(task_id, None)

    data['total'] = len(tasks)
    data['updated_at'] = _now_iso()
    self._recount(data)

    if tasks:
        self._write(batch_id, data)
        remaining_task_ids = sorted(tasks.keys(), key=lambda tid: (tasks[tid].get('order', 0), tid))
    else:
        batch_path = self._batch_path(batch_id)
        if os.path.exists(batch_path):
            os.remove(batch_path)
        remaining_task_ids = []

    return {
        'batch_id': batch_id,
        'deleted_task_id': task_id,
        'remaining_task_ids': remaining_task_ids,
    }
```

4. Update `build_course_view` return value to include summary fields while preserving existing fields:

```python
summary = self._summary_from_data(data)
return {
    **summary,
    'current_task_id': current_task_id,
    'items': items,
}
```

5. Replace duplicate artifact removal in `delete_batch`:

```python
for task_id in task_ids:
    self._delete_task_artifacts(task_id)
```

**Step 5: Run tests and verify they pass**

Run:

```bash
python -m pytest backend/tests/test_batch_manager.py -v
```

Expected: all tests in `test_batch_manager.py` PASS.

**Step 6: Commit**

Only commit if the user explicitly asks to commit this implementation. If committing, use:

```bash
git add backend/app/services/batch_manager.py backend/tests/test_batch_manager.py
git commit -m "feat(batch): add course batch summaries

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Backend batch history and child delete routes

**Files:**
- Modify: `backend/app/routers/batch.py`
- Test: `backend/tests/test_batch_routes.py`

**Step 1: Write failing route tests**

Add tests to `TestBatchRoutes` in `backend/tests/test_batch_routes.py`:

```python
def test_batch_courses_route_returns_summaries(self):
    with tempfile.TemporaryDirectory() as td:
        _reset_app_modules()
        old_output_dir = os.environ.get('NOTE_OUTPUT_DIR')
        os.environ['NOTE_OUTPUT_DIR'] = td

        try:
            from app.routers.batch import router
            from app.services.batch_manager import BatchManager

            app = FastAPI()
            app.include_router(router, prefix='/api')
            c = TestClient(app)

            mgr = BatchManager(output_dir=td)
            entry = {
                'video_url': 'https://www.bilibili.com/video/BV1xx/',
                'video_id': 'BV1xx',
                'title': '第一节',
                'duration': 100,
                'thumbnail': 'thumb',
                'order': 0,
            }
            batch_id = mgr.create_batch([entry], source_url='source', title='测试课程')
            mgr.register_task(batch_id, 'task-1', entry)
            with open(f'{td}/task-1.status.json', 'w', encoding='utf-8') as f:
                json.dump({'status': 'SUCCESS', 'message': ''}, f)

            r = c.get('/api/batch_courses')
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body['code'], 0)
            self.assertEqual(body['data'][0]['batch_id'], batch_id)
            self.assertEqual(body['data'][0]['title'], '测试课程')
            self.assertEqual(body['data'][0]['completed'], 1)
        finally:
            if old_output_dir is None:
                os.environ.pop('NOTE_OUTPUT_DIR', None)
            else:
                os.environ['NOTE_OUTPUT_DIR'] = old_output_dir
```

Add this test for child deletion:

```python
def test_delete_batch_task_route_removes_one_child(self):
    with tempfile.TemporaryDirectory() as td:
        db_path = pathlib.Path(td) / 'test.db'
        _reset_app_modules()
        old_output_dir = os.environ.get('NOTE_OUTPUT_DIR')
        old_database_url = os.environ.get('DATABASE_URL')
        os.environ['NOTE_OUTPUT_DIR'] = td
        os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'

        try:
            from app.db.init_db import init_db
            from app.db.video_task_dao import insert_video_task
            from app.routers.batch import router
            from app.services.batch_manager import BatchManager

            init_db()
            app = FastAPI()
            app.include_router(router, prefix='/api')
            c = TestClient(app)

            mgr = BatchManager(output_dir=td)
            entries = [
                {'video_url': 'u1', 'video_id': 'BV1', 'title': '第一节', 'thumbnail': 'thumb1', 'duration': 10, 'order': 0},
                {'video_url': 'u2', 'video_id': 'BV2', 'title': '第二节', 'thumbnail': 'thumb2', 'duration': 20, 'order': 1},
            ]
            batch_id = mgr.create_batch(entries, source_url='source', title='测试课程')
            mgr.register_task(batch_id, 'task-1', entries[0])
            mgr.register_task(batch_id, 'task-2', entries[1])
            for task_id, video_id in [('task-1', 'BV1'), ('task-2', 'BV2')]:
                with open(f'{td}/{task_id}.status.json', 'w', encoding='utf-8') as f:
                    json.dump({'status': 'SUCCESS', 'message': ''}, f)
                insert_video_task(video_id, 'bilibili', task_id)

            r = c.post('/api/delete_batch_task', json={'batch_id': batch_id, 'task_id': 'task-1'})
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body['code'], 0)
            self.assertEqual(body['data']['deleted_task_id'], 'task-1')
            self.assertEqual(body['data']['remaining_task_ids'], ['task-2'])
        finally:
            if old_output_dir is None:
                os.environ.pop('NOTE_OUTPUT_DIR', None)
            else:
                os.environ['NOTE_OUTPUT_DIR'] = old_output_dir
            if old_database_url is None:
                os.environ.pop('DATABASE_URL', None)
            else:
                os.environ['DATABASE_URL'] = old_database_url
```

**Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest backend/tests/test_batch_routes.py::TestBatchRoutes::test_batch_courses_route_returns_summaries backend/tests/test_batch_routes.py::TestBatchRoutes::test_delete_batch_task_route_removes_one_child -v
```

Expected: FAIL with 404 or missing route.

**Step 3: Implement routes**

Modify `backend/app/routers/batch.py`:

1. Add request model after `DeleteBatchRequest`:

```python
class DeleteBatchTaskRequest(BaseModel):
    batch_id: str
    task_id: str
```

2. Add list route before `/batch_status/{batch_id}` so static route matching stays obvious:

```python
@router.get('/batch_courses')
def batch_courses():
    try:
        mgr = BatchManager()
        return R.success(data=mgr.list_batches())
    except Exception as e:
        return R.error(msg=str(e))
```

3. Add child delete route after `delete_batch`:

```python
@router.post('/delete_batch_task')
def delete_batch_task(data: DeleteBatchTaskRequest):
    try:
        mgr = BatchManager()
        return R.success(data=mgr.delete_task_from_batch(data.batch_id, data.task_id), msg='删除成功')
    except FileNotFoundError:
        return R.error(msg='task not found', code=404)
    except Exception as e:
        return R.error(msg=str(e))
```

**Step 4: Run route tests**

Run:

```bash
python -m pytest backend/tests/test_batch_routes.py -v
```

Expected: all tests in `test_batch_routes.py` PASS.

**Step 5: Commit**

Only commit if explicitly requested:

```bash
git add backend/app/routers/batch.py backend/tests/test_batch_routes.py
git commit -m "feat(batch): expose course history APIs

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Frontend batch API types and store state

**Files:**
- Modify: `BillNote_frontend/src/services/batch.ts`
- Modify: `BillNote_frontend/src/store/taskStore/index.ts`

**Step 1: Add API types and clients**

Modify `BillNote_frontend/src/services/batch.ts`:

```ts
export interface BatchCourseSummary {
  batch_id: string
  title: string
  source_url: string
  cover_url: string
  total: number
  completed: number
  failed: number
  running: number
  status: string
  created_at: string
  updated_at: string
}

export interface DeleteBatchTaskResponse {
  batch_id: string
  deleted_task_id: string
  remaining_task_ids: string[]
}
```

Extend `BatchCourseResponse` with fields returned by the backend:

```ts
export interface BatchCourseResponse extends BatchCourseSummary {
  current_task_id: string | null
  items: BatchCourseItem[]
}
```

Add clients:

```ts
export const listBatchCourses = async () => {
  return await request.get<BatchCourseSummary[]>('/batch_courses')
}

export const deleteBatchTask = async (batchId: string, taskId: string) => {
  try {
    const res = await request.post<DeleteBatchTaskResponse>('/delete_batch_task', {
      batch_id: batchId,
      task_id: taskId,
    })
    toast.success('笔记已成功删除')
    return res
  } catch (e) {
    console.error('❌ 删除合集子笔记失败:', e)
    throw e
  }
}
```

**Step 2: Add batch course state to Zustand**

Modify imports in `BillNote_frontend/src/store/taskStore/index.ts`:

```ts
import { deleteBatch, deleteBatchTask, type BatchCourseSummary } from '@/services/batch.ts'
```

Extend `TaskStore`:

```ts
batchCourses: BatchCourseSummary[]
setBatchCourses: (courses: BatchCourseSummary[]) => void
upsertBatchCourse: (course: BatchCourseSummary) => void
removeBatchTask: (batchId: string, taskId: string) => Promise<void>
```

Add initial state:

```ts
batchCourses: [],
```

Add methods:

```ts
setBatchCourses: courses => set({ batchCourses: courses }),
upsertBatchCourse: course =>
  set(state => ({
    batchCourses: [
      course,
      ...state.batchCourses.filter(item => item.batch_id !== course.batch_id),
    ],
  })),
removeBatchTask: async (batchId, taskId) => {
  await deleteBatchTask(batchId, taskId)

  set(state => {
    const nextTasks = state.tasks.filter(item => item.id !== taskId)
    const nextCourses = state.batchCourses
      .map(course => {
        if (course.batch_id !== batchId) return course
        const total = Math.max(0, course.total - 1)
        return {
          ...course,
          total,
          completed: Math.min(course.completed, total),
          running: Math.max(0, total - Math.min(course.completed, total) - course.failed),
        }
      })
      .filter(course => course.batch_id !== batchId || course.total > 0)

    return {
      tasks: nextTasks,
      batchCourses: nextCourses,
      currentTaskId: state.currentTaskId === taskId ? null : state.currentTaskId,
      activeBatchId: nextCourses.some(course => course.batch_id === state.activeBatchId)
        ? state.activeBatchId
        : null,
    }
  })
},
```

Update `removeBatch` to also remove the summary:

```ts
batchCourses: state.batchCourses.filter(item => item.batch_id !== batchId),
```

Update `clearTasks`:

```ts
clearTasks: () => set({ tasks: [], batchCourses: [], currentTaskId: null, activeBatchId: null }),
```

Update `removeTask` so a child task deletes only itself instead of the whole batch:

```ts
if (task.batchId) {
  await get().removeBatchTask(task.batchId, task.id)
  return
}
```

**Step 3: Run TypeScript check**

Run:

```bash
cd BillNote_frontend && pnpm build
```

Expected: build may still fail until later UI tasks if new store methods are unused incorrectly; no syntax errors should come from `services/batch.ts` or `taskStore/index.ts`.

**Step 4: Commit**

Only commit if explicitly requested:

```bash
git add BillNote_frontend/src/services/batch.ts BillNote_frontend/src/store/taskStore/index.ts
git commit -m "feat(batch): track course history state

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Frontend history grouping UI

**Files:**
- Modify: `BillNote_frontend/src/pages/HomePage/components/NoteHistory.tsx`
- Modify: `BillNote_frontend/src/pages/HomePage/components/History.tsx`

**Step 1: Update NoteHistory props**

Change props in `NoteHistory.tsx`:

```ts
interface NoteHistoryProps {
  onSelect: (taskId: string) => void
  onSelectBatch: (batchId: string) => void
  selectedId: string | null
  activeBatchId: string | null
}
```

Read new store fields:

```ts
const batchCourses = useTaskStore(state => state.batchCourses)
const removeBatch = useTaskStore(state => state.removeBatch)
const removeBatchTask = useTaskStore(state => state.removeBatchTask)
const [expandedBatchIds, setExpandedBatchIds] = useState<string[]>([])
```

**Step 2: Build grouped list**

Replace `fuse` input and `filteredTasks` derivation with:

```ts
const standaloneTasks = useMemo(() => tasks.filter(task => !task.batchId), [tasks])
const tasksByBatchId = useMemo(() => {
  return tasks.reduce<Record<string, typeof tasks>>((acc, task) => {
    if (!task.batchId) return acc
    acc[task.batchId] = [...(acc[task.batchId] || []), task]
    return acc
  }, {})
}, [tasks])

const fuse = useMemo(
  () =>
    new Fuse(standaloneTasks, {
      keys: ['audioMeta.title'],
      threshold: 0.4,
    }),
  [standaloneTasks],
)

const filteredTasks = search.trim() ? fuse.search(search).map(result => result.item) : standaloneTasks
const filteredCourses = search.trim()
  ? batchCourses.filter(course => PinyinMatch.match(course.title || '视频合集', search))
  : batchCourses
```

Use `rawSearch` consistently in the input:

```tsx
value={rawSearch}
onChange={e => setRawSearch(e.target.value)}
```

**Step 3: Render course parent and child rows**

Add helper functions near the component:

```ts
const statusLabel = (status?: string) => {
  const normalized = String(status || '').toUpperCase()
  if (normalized === 'SUCCESS') return '已完成'
  if (normalized === 'FAILED') return '失败'
  if (normalized === 'RUNNING') return '生成中'
  if (normalized === 'EMPTY') return '空合集'
  return '等待中'
}
```

Before standalone tasks, render `filteredCourses.map(course => ...)`:

```tsx
{filteredCourses.map(course => {
  const expanded = expandedBatchIds.includes(course.batch_id) || activeBatchId === course.batch_id
  const childTasks = tasksByBatchId[course.batch_id] || []

  return (
    <div key={course.batch_id} className="rounded-md border border-neutral-200 bg-white">
      <div
        role="button"
        tabIndex={0}
        onClick={() => {
          setExpandedBatchIds(prev =>
            prev.includes(course.batch_id)
              ? prev.filter(id => id !== course.batch_id)
              : [...prev, course.batch_id],
          )
          onSelectBatch(course.batch_id)
        }}
        className={cn(
          'cursor-pointer p-3',
          activeBatchId === course.batch_id && 'border-primary bg-primary-light',
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="line-clamp-2 text-sm font-medium text-neutral-900">
              {course.title || '视频合集'}
            </div>
            <div className="mt-1 text-[10px] text-neutral-500">
              共 {course.total} 个视频 · 已完成 {course.completed} · 失败 {course.failed} · 生成中 {course.running}
            </div>
          </div>
          <Badge variant={course.status === 'FAILED' ? 'destructive' : 'outline'}>
            {statusLabel(course.status)}
          </Badge>
          <Button
            type="button"
            size="small"
            variant="ghost"
            onClick={async e => {
              e.stopPropagation()
              if (!window.confirm('将彻底删除该合集下所有笔记记录，是否继续？')) return
              await removeBatch(course.batch_id)
            }}
          >
            <Trash className="text-muted-foreground h-4 w-4" />
          </Button>
        </div>
      </div>

      {expanded && (
        <div className="space-y-1 border-t border-neutral-100 p-2">
          {childTasks.map(task => (
            <div
              key={task.id}
              onClick={() => onSelect(task.id)}
              className={cn(
                'ml-3 cursor-pointer rounded-md border border-neutral-100 p-2',
                selectedId === task.id && 'border-primary bg-primary-light',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="line-clamp-2 text-xs text-neutral-800">
                  {task.audioMeta.title || '未命名笔记'}
                </div>
                <Button
                  type="button"
                  size="small"
                  variant="ghost"
                  onClick={async e => {
                    e.stopPropagation()
                    if (!window.confirm('确定删除该视频笔记吗？')) return
                    await removeBatchTask(course.batch_id, task.id)
                  }}
                >
                  <Trash className="text-muted-foreground h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
          {childTasks.length === 0 && (
            <div className="px-3 py-2 text-xs text-neutral-400">暂无本地子笔记记录</div>
          )}
        </div>
      )}
    </div>
  )
})}
```

Keep existing standalone task rendering, but it should map over `filteredTasks` and no longer show the batch delete confirm branch.

**Step 4: Update History selection behavior**

Modify `History.tsx` props passed to `NoteHistory`:

```tsx
<NoteHistory
  onSelect={taskId => {
    const task = tasks.find(item => item.id === taskId)
    if (task?.batchId) {
      setActiveBatch(task.batchId)
    } else {
      clearActiveBatch()
    }
    setCurrentTask(taskId)
  }}
  onSelectBatch={batchId => {
    setActiveBatch(batchId)
    const firstTask = tasks.find(item => item.batchId === batchId)
    if (firstTask) {
      setCurrentTask(firstTask.id)
    }
  }}
  selectedId={currentTaskId}
  activeBatchId={useTaskStore.getState().activeBatchId}
/>
```

Prefer selecting `activeBatchId` via hook at top instead of `useTaskStore.getState()`:

```ts
const activeBatchId = useTaskStore(state => state.activeBatchId)
```

**Step 5: Run frontend build**

Run:

```bash
cd BillNote_frontend && pnpm build
```

Expected: PASS. If it fails on unused imports like `Badge` or `ScrollArea`, remove only the unused import from the touched file.

**Step 6: Commit**

Only commit if explicitly requested:

```bash
git add BillNote_frontend/src/pages/HomePage/components/NoteHistory.tsx BillNote_frontend/src/pages/HomePage/components/History.tsx
git commit -m "feat(batch): group course notes in history

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Frontend load and refresh batch summaries

**Files:**
- Modify: `BillNote_frontend/src/pages/HomePage/components/History.tsx`
- Modify: `BillNote_frontend/src/pages/HomePage/components/CourseViewer.tsx`
- Modify: `BillNote_frontend/src/pages/HomePage/components/NoteForm.tsx`

**Step 1: Load batch summaries when History mounts**

Modify `History.tsx` imports:

```ts
import { useEffect } from 'react'
import { listBatchCourses } from '@/services/batch.ts'
```

Read setter:

```ts
const setBatchCourses = useTaskStore(state => state.setBatchCourses)
```

Add effect:

```ts
useEffect(() => {
  let cancelled = false

  const load = async () => {
    try {
      const courses = await listBatchCourses()
      if (!cancelled) {
        setBatchCourses(courses)
      }
    } catch (e) {
      console.error('加载合集历史失败:', e)
    }
  }

  void load()

  return () => {
    cancelled = true
  }
}, [setBatchCourses])
```

**Step 2: Keep active course summary fresh from CourseViewer polling**

Modify `CourseViewer.tsx`:

```ts
const upsertBatchCourse = useTaskStore(state => state.upsertBatchCourse)
```

Add effect after polling data is available:

```ts
useEffect(() => {
  if (!data) return
  upsertBatchCourse({
    batch_id: data.batch_id,
    title: data.title,
    source_url: data.source_url,
    cover_url: data.cover_url,
    total: data.total,
    completed: data.completed,
    failed: data.failed,
    running: data.running,
    status: data.status,
    created_at: data.created_at,
    updated_at: data.updated_at,
  })
}, [data, upsertBatchCourse])
```

**Step 3: Upsert course summary after creating a batch**

In `NoteForm.tsx`, find the `generateBatchNote` success branch that receives `batch_id` and `task_map`.

After adding pending child tasks, call `upsertBatchCourse` with the selected entries:

```ts
upsertBatchCourse({
  batch_id: batchId,
  title: batchTitle || selectedEntries[0]?.title || '视频合集',
  source_url: sourceUrl,
  cover_url: selectedEntries[0]?.thumbnail || '',
  total: selectedEntries.length,
  completed: 0,
  failed: 0,
  running: selectedEntries.length,
  status: 'RUNNING',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
})
```

Use the actual local variable names from `NoteForm.tsx`; do not invent new state names if the file already has equivalents.

**Step 4: Run frontend build**

Run:

```bash
cd BillNote_frontend && pnpm build
```

Expected: PASS.

**Step 5: Commit**

Only commit if explicitly requested:

```bash
git add BillNote_frontend/src/pages/HomePage/components/History.tsx BillNote_frontend/src/pages/HomePage/components/CourseViewer.tsx BillNote_frontend/src/pages/HomePage/components/NoteForm.tsx
git commit -m "feat(batch): refresh course history summaries

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end verification and cleanup

**Files:**
- No planned source edits unless verification exposes a bug.
- Test evidence should be reported in the final response; do not create a new report file unless the user asks.

**Step 1: Run backend batch tests**

Run:

```bash
python -m pytest backend/tests/test_batch_manager.py backend/tests/test_batch_routes.py -v
```

Expected: PASS.

**Step 2: Run frontend build**

Run:

```bash
cd BillNote_frontend && pnpm build
```

Expected: PASS.

**Step 3: Start backend and frontend for manual UI verification**

In one terminal:

```bash
cd backend && python main.py
```

In another terminal:

```bash
cd BillNote_frontend && pnpm dev
```

Expected:

- Backend listens on `0.0.0.0:8483`.
- Frontend Vite dev server listens on port `3015`.

**Step 4: Verify UI golden paths in browser**

Use the browser against the local frontend:

1. Open Home page.
2. Submit a normal single-video URL.
3. Confirm the note appears as a normal flat history item.
4. Submit or simulate a video合集 URL that produces multiple entries.
5. Confirm history shows one合集父项 instead of many flat child rows.
6. Expand the合集父项.
7. Click a child video and confirm Markdown viewer shows that child note.
8. Delete one child video and confirm only that child disappears.
9. Delete the合集 and confirm the whole group disappears.
10. Refresh the page and confirm remaining合集分组 can be restored from backend summaries.

If real Bilibili generation is too slow, use existing backend tests plus a locally created `batch_*.json` fixture in `NOTE_OUTPUT_DIR` for UI verification. Do not claim real generation passed unless it was actually run.

**Step 5: Final git status review**

Run:

```bash
git status --short
```

Expected: only intended files changed. The repository already had unrelated uncommitted files before this plan; do not stage or delete them.

---

## Final verification checklist

- `python -m pytest backend/tests/test_batch_manager.py backend/tests/test_batch_routes.py -v` passes.
- `cd BillNote_frontend && pnpm build` passes.
- Single-video history remains flat.
- Video合集 history appears as a parent group with child notes underneath.
- Deleting a child note does not delete the whole合集.
- Deleting the合集 deletes all child notes and the batch record.
- Refreshing the page restores合集 summaries through `/batch_courses`.
