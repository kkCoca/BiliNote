import { useEffect, useRef } from 'react'
import { useTaskStore } from '@/store/taskStore'
import { get_task_status } from '@/services/note.ts'
import { getBatchStatus, listBatchCourses, toBatchCourseSummary } from '@/services/batch.ts'
import toast from 'react-hot-toast'

const getTaskBatchId = (task: { batchId?: string; formData?: { batchId?: string; batch_id?: string } }) =>
  task.batchId ?? task.formData?.batchId ?? task.formData?.batch_id

export const useTaskPolling = (interval = 3000) => {
  const tasks = useTaskStore(state => state.tasks)
  const batchCourses = useTaskStore(state => state.batchCourses)
  const updateTaskContent = useTaskStore(state => state.updateTaskContent)
  const mergeBatchCourses = useTaskStore(state => state.mergeBatchCourses)
  const upsertBatchCourse = useTaskStore(state => state.upsertBatchCourse)
  const tasksRef = useRef(tasks)
  const batchCoursesRef = useRef(batchCourses)
  const isPollingRef = useRef(false)

  // 每次 tasks 更新，把最新的 tasks 同步进去
  useEffect(() => {
    tasksRef.current = tasks
  }, [tasks])

  useEffect(() => {
    batchCoursesRef.current = batchCourses
  }, [batchCourses])

  useEffect(() => {
    const timer = setInterval(async () => {
      if (isPollingRef.current) return
      isPollingRef.current = true

      try {
        const pendingTasks = tasksRef.current.filter(
          task => task.status != 'SUCCESS' && task.status != 'FAILED'
        )

        const activeBatchIds = new Set(
          pendingTasks.map(getTaskBatchId).filter((id): id is string => Boolean(id))
        )
        const hasRunningPersistedBatch = batchCoursesRef.current.some(batchCourse => batchCourse.running > 0)

        if (pendingTasks.length === 0 && !hasRunningPersistedBatch) return

        for (const task of pendingTasks) {
          try {
            const res = await get_task_status(task.id)
            const { status } = res

            if (status && status !== task.status) {
              if (status === 'SUCCESS' && res.result) {
                const { markdown, transcript, audio_meta } = res.result
                toast.success('笔记生成成功')
                updateTaskContent(task.id, {
                  status,
                  markdown,
                  transcript,
                  audioMeta: audio_meta,
                })
              } else if (status === 'FAILED') {
                updateTaskContent(task.id, { status })
                console.warn(`⚠️ 任务 ${task.id} 失败`)
              } else {
                updateTaskContent(task.id, { status })
              }
            }
          } catch (e) {
            console.error('❌ 任务轮询失败：', e)
            updateTaskContent(task.id, { status: 'FAILED' })
          }
        }

        for (const batchId of activeBatchIds) {
          try {
            const rawStatus = await getBatchStatus(batchId)
            upsertBatchCourse(toBatchCourseSummary(rawStatus))
          } catch (e) {
            console.error('批量任务摘要刷新失败：', e)
          }
        }

        if (hasRunningPersistedBatch) {
          try {
            mergeBatchCourses(await listBatchCourses())
          } catch (e) {
            console.error('批量课程列表刷新失败：', e)
          }
        }
      } finally {
        isPollingRef.current = false
      }
    }, interval)

    return () => clearInterval(timer)
  }, [interval, mergeBatchCourses, updateTaskContent, upsertBatchCourse])
}
