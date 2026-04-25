import request, { type IResponse } from '@/utils/request'
import toast from 'react-hot-toast'

export interface DetectedEntry {
  video_id: string
  title: string
  duration: number
  thumbnail: string
  video_url: string
}

export interface DetectUrlResponse {
  type: 'single' | 'multi'
  title?: string
  source_url?: string
  cover_url?: string
  entries: DetectedEntry[]
}

export const detectUrl = async (url: string): Promise<DetectUrlResponse> => {
  // Bilibili space list extraction may take longer due to browser automation.
  return await request.post('/detect_url', { url }, { timeout: 300000 })
}

export interface GenerateBatchRequest {
  video_urls: string[]
  platform: string
  quality: string
  model_name: string
  provider_id: string
  format: string[]
  style: string
  title?: string
  source_url?: string
  cover_url?: string
  extras?: string
  screenshot?: boolean
  link?: boolean
  video_understanding?: boolean
  video_interval?: number
  grid_size: number[]
}

export interface GenerateBatchResponse {
  batch_id: string
  task_map: Array<{ video_url: string; task_id: string }>
}

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

export interface BatchCourseItem {
  task_id: string
  video_url?: string
  title?: string
  thumbnail?: string
  duration?: number
  status?: string
  result_ready?: boolean
  note_excerpt?: string
  order?: number
  error?: string
}

export interface BatchCourseResponse extends BatchCourseSummary {
  current_task_id: string | null
  items: BatchCourseItem[]
}

export interface RawBatchTask {
  video_id?: string
  video_url?: string
  status?: string
  error?: string
  order?: number
}

export interface RawBatchEntry {
  video_url: string
  order?: number
}

export interface RawBatchStatusResponse {
  batch_id: string
  total: number
  completed: number
  failed: number
  tasks: Record<string, RawBatchTask>
  entries?: RawBatchEntry[]
  title?: string
  source_url?: string
  cover_url?: string
  created_at: string
  updated_at: string
}

export const toBatchCourseSummary = (raw: RawBatchStatusResponse): BatchCourseSummary => {
  const running = Math.max(raw.total - raw.completed - raw.failed, 0)
  const status =
    raw.total === 0 ? 'EMPTY' : running > 0 ? 'RUNNING' : raw.failed > 0 ? 'FAILED' : 'SUCCESS'

  return {
    batch_id: raw.batch_id,
    title: raw.title || '批量课程',
    source_url: raw.source_url || raw.entries?.[0]?.video_url || '',
    cover_url: raw.cover_url || '',
    total: raw.total,
    completed: raw.completed,
    failed: raw.failed,
    running,
    status,
    created_at: raw.created_at,
    updated_at: raw.updated_at,
  }
}

export interface DeleteBatchTaskResponse extends RawBatchStatusResponse {
  deleted_task_id: string
  remaining_task_ids: string[]
}

export interface DeleteBatchResponse {
  batch_id: string
  deleted_task_ids: string[]
}

export const generateBatchNote = async (data: GenerateBatchRequest): Promise<GenerateBatchResponse> => {
  return await request.post('/generate_batch_note', data, { timeout: 120000 })
}

export const getBatchStatus = async (batchId: string): Promise<RawBatchStatusResponse> => {
  return await request.get(`/batch_status/${batchId}`)
}

export const listBatchCourses = async (): Promise<BatchCourseSummary[]> => {
  return await request.get('/batch_courses')
}

export const deleteBatchTask = async (
  batchId: string,
  taskId: string
): Promise<DeleteBatchTaskResponse> => {
  try {
    const res: DeleteBatchTaskResponse = await request.post('/delete_batch_task', {
      batch_id: batchId,
      task_id: taskId,
    })
    toast.success('任务已成功删除')
    return res
  } catch (e) {
    console.error('删除批量任务失败:', e)
    throw e
  }
}

export const deleteBatch = async (batchId: string): Promise<DeleteBatchResponse> => {
  try {
    const res: DeleteBatchResponse = await request.delete(`/delete_batch/${batchId}`, {
      suppressErrorToast: true,
    })
    toast.success('合集已成功删除')
    return res
  } catch (e) {
    const response = e as IResponse | undefined
    if (response?.code === 404) {
      return { batch_id: batchId, deleted_task_ids: [] }
    }

    console.error('删除视频合集失败:', e)
    toast.error(response?.msg || '删除合集失败')
    throw e
  }
}
