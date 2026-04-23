import request from '@/utils/request'

export interface DetectedEntry {
  video_id: string
  title: string
  duration: number
  thumbnail: string
  video_url: string
}

export interface DetectUrlResponse {
  type: 'single' | 'multi'
  entries: DetectedEntry[]
}

export const detectUrl = async (url: string) => {
  // Bilibili space list extraction may take longer due to browser automation.
  return await request.post<DetectUrlResponse>('/detect_url', { url }, { timeout: 300000 })
}

export interface GenerateBatchRequest {
  video_urls: string[]
  platform: string
  quality: string
  model_name: string
  provider_id: string
  format: string[]
  style: string
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

export const generateBatchNote = async (data: GenerateBatchRequest) => {
  return await request.post<GenerateBatchResponse>('/generate_batch_note', data, { timeout: 120000 })
}

export const getBatchStatus = async (batchId: string) => {
  return await request.get(`/batch_status/${batchId}`)
}
