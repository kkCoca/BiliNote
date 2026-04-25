import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { delete_task, generateNote } from '@/services/note.ts'
import { deleteBatch, deleteBatchTask, type BatchCourseSummary } from '@/services/batch.ts'
import { v4 as uuidv4 } from 'uuid'
import toast from 'react-hot-toast'


export type TaskStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'PARSING'
  | 'DOWNLOADING'
  | 'TRANSCRIBING'
  | 'SUMMARIZING'
  | 'FORMATTING'
  | 'SAVING'
  | 'SUCCESS'
  | 'FAILED'

export interface TaskFormData {
  video_url: string
  link: undefined | boolean
  screenshot: undefined | boolean
  platform: string
  quality: string
  model_name: string
  provider_id: string
  style?: string
  batchId?: string
  batch_id?: string
  format?: string[]
  extras?: string
  video_understanding?: boolean
  video_interval?: number
  grid_size?: number[]
}

export interface AudioMeta {
  cover_url: string
  duration: number
  file_path: string
  platform: string
  raw_info: unknown
  title: string
  video_id: string
}

export interface Segment {
  start: number
  end: number
  text: string
}

export interface Transcript {
  full_text: string
  language: string
  raw: unknown
  segments: Segment[]
}
export interface Markdown {
  ver_id: string
  content: string
  style: string
  model_name: string
  created_at: string
}

export interface Task {
  id: string
  markdown: string|Markdown [] //为了兼容之前的笔记
  transcript: Transcript
  status: TaskStatus
  audioMeta: AudioMeta
  createdAt: string
  formData: TaskFormData
  platform?: string
  batchId?: string
}

interface TaskStore {
  tasks: Task[]
  batchCourses: BatchCourseSummary[]
  currentTaskId: string | null
  addPendingTask: (taskId: string, platform: string, formData?: TaskFormData) => void
  updateTaskContent: (id: string, data: Partial<Omit<Task, 'id' | 'createdAt'>>) => void
  removeTask: (id: string) => Promise<void>
  removeBatch: (batchId: string) => Promise<void>
  clearTasks: () => void
  setBatchCourses: (batchCourses: BatchCourseSummary[]) => void
  mergeBatchCourses: (batchCourses: BatchCourseSummary[]) => void
  upsertBatchCourse: (batchCourse: BatchCourseSummary) => void
  removeBatchTask: (batchId: string, taskId: string) => Promise<void>
  setCurrentTask: (taskId: string | null) => void
  getCurrentTask: () => Task | null
  retryTask: (id: string, payload?: TaskFormData) => Promise<void>
}

const getTaskBatchId = (task: Task) => task.batchId ?? task.formData?.batchId ?? task.formData?.batch_id

const normalizeTaskStatus = (status?: string): TaskStatus | undefined => {
  if (status === 'FAILD') return 'FAILED'
  const allowedStatuses: TaskStatus[] = [
    'PENDING',
    'RUNNING',
    'PARSING',
    'DOWNLOADING',
    'TRANSCRIBING',
    'SUMMARIZING',
    'FORMATTING',
    'SAVING',
    'SUCCESS',
    'FAILED',
  ]
  return allowedStatuses.includes(status as TaskStatus) ? (status as TaskStatus) : undefined
}

const getBatchCourseStatus = (batchCourse: Pick<BatchCourseSummary, 'total' | 'failed' | 'running'>) => {
  if (batchCourse.total === 0) return 'EMPTY'
  if (batchCourse.running > 0) return 'RUNNING'
  if (batchCourse.failed > 0) return 'FAILED'
  return 'SUCCESS'
}

const parseBatchCourseUpdatedAt = (updatedAt?: string) => {
  const timestamp = Date.parse(updatedAt || '')
  return Number.isNaN(timestamp) ? null : timestamp
}

const isStaleBatchCourseSummary = (incoming: BatchCourseSummary, existing?: BatchCourseSummary) => {
  if (!existing || incoming.batch_id !== existing.batch_id) return false

  const incomingUpdatedAt = parseBatchCourseUpdatedAt(incoming.updated_at)
  const existingUpdatedAt = parseBatchCourseUpdatedAt(existing.updated_at)

  return incomingUpdatedAt !== null && existingUpdatedAt !== null && incomingUpdatedAt < existingUpdatedAt
}

const mergeBatchCourseSummary = (
  incoming: BatchCourseSummary,
  existing?: BatchCourseSummary
): BatchCourseSummary => {
  const merged = {
    ...incoming,
    title: incoming.title && incoming.title !== '批量课程' ? incoming.title : existing?.title || incoming.title,
    source_url: incoming.source_url || existing?.source_url || '',
    cover_url: incoming.cover_url || existing?.cover_url || '',
  }

  if (!isStaleBatchCourseSummary(incoming, existing) || !existing) return merged

  return {
    ...merged,
    total: existing.total,
    completed: existing.completed,
    failed: existing.failed,
    running: existing.running,
    status: existing.status,
    updated_at: existing.updated_at,
  }
}

export const useTaskStore = create<TaskStore>()(
  persist(
    (set, get) => ({
      tasks: [],
      batchCourses: [],
      currentTaskId: null,

      addPendingTask: (taskId: string, platform: string, formData?: TaskFormData) =>

        set(state => ({
          tasks: [
            {
              formData: formData ?? {
                video_url: '',
                link: undefined,
                screenshot: undefined,
                platform,
                quality: '',
                model_name: '',
                provider_id: '',
              },
              id: taskId,
              batchId: formData?.batchId ?? formData?.batch_id,
              status: 'PENDING',
              markdown: '',
              platform: platform,
              transcript: {
                full_text: '',
                language: '',
                raw: null,
                segments: [],
              },
              createdAt: new Date().toISOString(),
              audioMeta: {
                cover_url: '',
                duration: 0,
                file_path: '',
                platform: '',
                raw_info: null,
                title: '',
                video_id: '',
              },
            },
            ...state.tasks,
          ],
          currentTaskId: taskId, // 默认设置为当前任务
        })),

      updateTaskContent: (id, data) =>
          set(state => ({
            tasks: state.tasks.map(task => {
              if (task.id !== id) return task

              const normalizedStatus = normalizeTaskStatus(data.status)
              const normalizedData = normalizedStatus ? { ...data, status: normalizedStatus } : data

              if (task.status === 'SUCCESS' && normalizedData.status === 'SUCCESS') return task

              // 如果是 markdown 字符串，封装为版本
              if (typeof normalizedData.markdown === 'string') {
                const prev = task.markdown
                const newVersion: Markdown = {
                  ver_id: `${task.id}-${uuidv4()}`,
                  content: normalizedData.markdown,
                  style: task.formData.style || '',
                  model_name: task.formData.model_name || '',
                  created_at: new Date().toISOString(),
                }

                let updatedMarkdown: Markdown[]
                if (Array.isArray(prev)) {
                  updatedMarkdown = [newVersion, ...prev]
                } else {
                  updatedMarkdown = [
                    newVersion,
                    ...(typeof prev === 'string' && prev
                        ? [{
                          ver_id: `${task.id}-${uuidv4()}`,
                          content: prev,
                          style: task.formData.style || '',
                          model_name: task.formData.model_name || '',
                          created_at: new Date().toISOString(),
                        }]
                        : []),
                  ]
                }

                return {
                  ...task,
                  ...normalizedData,
                  markdown: updatedMarkdown,
                }
              }

              return { ...task, ...normalizedData }
            }),
          })),


      getCurrentTask: () => {
        const currentTaskId = get().currentTaskId
        return get().tasks.find(task => task.id === currentTaskId) || null
      },
      retryTask: async (id: string, payload?: TaskFormData) => {

        if (!id){
          toast.error('任务不存在')
          return
        }
        const task = get().tasks.find(task => task.id === id)
        if (!task) return

        const newFormData = payload || task.formData
        const newBatchId = newFormData.batchId ?? newFormData.batch_id
        console.log('retry',task)
        const { batchId, batch_id, ...notePayload } = newFormData
        void batchId
        void batch_id
        await generateNote({
          ...notePayload,
          format: notePayload.format || [],
          style: notePayload.style || '',
          grid_size: notePayload.grid_size || [2, 2],
          task_id: id,
        })

        set(state => ({
          tasks: state.tasks.map(t =>
              t.id === id
                  ? {
                    ...t,
                    formData: newFormData, // ✅ 显式更新 formData
                    batchId: newBatchId,
                    status: 'PENDING',
                  }
                  : t
          ),
        }))
      },


      removeTask: async id => {
        const task = get().tasks.find(t => t.id === id)
        const batchId = task ? getTaskBatchId(task) : undefined

        if (task && batchId) {
          await get().removeBatchTask(batchId, id)
          return
        }

        // 更新 Zustand 状态
        set(state => ({
          tasks: state.tasks.filter(task => task.id !== id),
          currentTaskId: state.currentTaskId === id ? null : state.currentTaskId,
        }))

        // 调用后端删除接口（如果找到了任务）
        if (task) {
          await delete_task({
            video_id: task.audioMeta.video_id,
            platform: task.audioMeta.platform || task.formData.platform || task.platform,
          })
        }
      },

      removeBatch: async batchId => {
        const snapshot = {
          tasks: get().tasks,
          batchCourses: get().batchCourses,
          currentTaskId: get().currentTaskId,
        }

        set(state => ({
          tasks: state.tasks.filter(task => getTaskBatchId(task) !== batchId),
          batchCourses: state.batchCourses.filter(batchCourse => batchCourse.batch_id !== batchId),
          currentTaskId: state.tasks.some(
            task => task.id === state.currentTaskId && getTaskBatchId(task) === batchId
          )
            ? null
            : state.currentTaskId,
        }))

        try {
          await deleteBatch(batchId)
        } catch (error) {
          const isAlreadyDeleted =
            typeof error === 'object' &&
            error !== null &&
            'code' in error &&
            (error as { code?: number }).code === 404

          if (isAlreadyDeleted) return

          set(snapshot)
          toast.error(error instanceof Error ? error.message : '删除合集失败')
          throw error
        }
      },

      clearTasks: () => set({ tasks: [], batchCourses: [], currentTaskId: null }),

      setBatchCourses: batchCourses => set({ batchCourses }),

      mergeBatchCourses: batchCourses =>
        set(state => {
          const existingByBatchId = new Map(
            state.batchCourses.map(batchCourse => [batchCourse.batch_id, batchCourse])
          )
          const incomingByBatchId = new Set(batchCourses.map(batchCourse => batchCourse.batch_id))
          const mergedIncoming = batchCourses.map(batchCourse =>
            mergeBatchCourseSummary(batchCourse, existingByBatchId.get(batchCourse.batch_id))
          )
          const localOnly = state.batchCourses.filter(
            batchCourse => !incomingByBatchId.has(batchCourse.batch_id)
          )

          return { batchCourses: [...mergedIncoming, ...localOnly] }
        }),

      upsertBatchCourse: batchCourse =>
        set(state => {
          const existing = state.batchCourses.find(item => item.batch_id === batchCourse.batch_id)
          const mergedBatchCourse = mergeBatchCourseSummary(batchCourse, existing)
          return {
            batchCourses: existing
              ? state.batchCourses.map(item =>
                  item.batch_id === batchCourse.batch_id ? mergedBatchCourse : item
                )
              : [mergedBatchCourse, ...state.batchCourses],
          }
        }),

      removeBatchTask: async (batchId, taskId) => {
        const result = await deleteBatchTask(batchId, taskId)
        set(state => {
          const updatedCourses = state.batchCourses
            .map(batchCourse => {
              if (batchCourse.batch_id !== batchId) return batchCourse

              const running = Math.max(result.total - result.completed - result.failed, 0)

              return {
                ...batchCourse,
                total: result.total,
                completed: result.completed,
                failed: result.failed,
                running,
                status: getBatchCourseStatus({
                  total: result.total,
                  failed: result.failed,
                  running,
                }),
                updated_at: result.updated_at,
              }
            })
            .filter(batchCourse => batchCourse.batch_id !== batchId || batchCourse.total > 0)

          return {
            tasks: state.tasks.filter(task => task.id !== taskId),
            batchCourses: updatedCourses,
            currentTaskId: state.currentTaskId === taskId ? null : state.currentTaskId,
          }
        })
      },

      setCurrentTask: taskId => set({ currentTaskId: taskId }),
    }),
    {
      name: 'task-storage',
      version: 1,
      migrate: persistedState => ({
        ...(persistedState as TaskStore),
        tasks: [],
        batchCourses: [],
        currentTaskId: null,
      }),
    }
  )
)
