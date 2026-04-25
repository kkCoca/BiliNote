import { useTaskStore, type Task } from '@/store/taskStore'
import { cn } from '@/lib/utils.ts'
import { ChevronDown, ChevronRight, Trash } from 'lucide-react'
import { Button } from '@/components/ui/button.tsx'
import toast from 'react-hot-toast'

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip.tsx'
import LazyImage from '@/components/LazyImage.tsx'
import { FC, useMemo, useState } from 'react'

interface NoteHistoryProps {
  onSelect: (taskId: string) => void
  selectedId: string | null
}

type HistorySingleItem = {
  type: 'single'
  task: Task
}

type HistoryCourseItem = {
  type: 'course'
  batchId: string
  tasks: Task[]
  title: string
  coverUrl: string
  total: number
  completed: number
  failed: number
  running: number
}

type HistoryItem = HistorySingleItem | HistoryCourseItem

const getTaskBatchId = (task: Task) => task.batchId ?? task.formData?.batchId ?? task.formData?.batch_id

const getTaskTitle = (task: Task) => task.audioMeta?.title || '未命名笔记'

const getStatusLabel = (status?: string) => {
  if (status === 'SUCCESS') return '已完成'
  if (status === 'FAILED') return '失败'
  return '等待中'
}

const getStatusClassName = (status?: string) => {
  if (status === 'SUCCESS') return 'bg-primary'
  if (status === 'FAILED') return 'bg-red-500'
  return 'bg-green-500'
}

const matchesSearch = (value: string | undefined, search: string) =>
  (value || '').toLowerCase().includes(search.toLowerCase())

const getImageSrc = (coverUrl: string | undefined, platform: string | undefined, baseURL: string) => {
  if (!coverUrl) return '/placeholder.png'
  if (platform === 'local') return coverUrl
  return `${baseURL}/image_proxy?url=${encodeURIComponent(coverUrl)}`
}

const NoteHistory: FC<NoteHistoryProps> = ({ onSelect, selectedId }) => {
  const tasks = useTaskStore(state => state.tasks)
  const batchCourses = useTaskStore(state => state.batchCourses)
  const removeTask = useTaskStore(state => state.removeTask)
  // 确保baseURL没有尾部斜杠
  const baseURL = (String(import.meta.env.VITE_API_BASE_URL || 'api')).replace(/\/$/, '')
  const [search, setSearch] = useState('')
  const [expandedBatchIds, setExpandedBatchIds] = useState<Set<string>>(new Set())

  const historyItems = useMemo<HistoryItem[]>(() => {
    const groupedTasks = new Map<string, Task[]>()
    const singleTasks: Task[] = []

    tasks.forEach(task => {
      const batchId = getTaskBatchId(task)
      if (!batchId) {
        singleTasks.push(task)
        return
      }

      groupedTasks.set(batchId, [...(groupedTasks.get(batchId) || []), task])
    })

    const courseIds = new Set<string>([
      ...batchCourses.map(course => course.batch_id),
      ...groupedTasks.keys(),
    ])

    const courseItems = Array.from(courseIds).map<HistoryCourseItem>(batchId => {
      const course = batchCourses.find(item => item.batch_id === batchId) || null
      const courseTasks = groupedTasks.get(batchId) || []
      const firstTask = courseTasks[0]
      const completed = course?.completed ?? courseTasks.filter(task => task.status === 'SUCCESS').length
      const failed = course?.failed ?? courseTasks.filter(task => task.status === 'FAILED').length
      const total = course?.total ?? courseTasks.length
      const running = course?.running ?? Math.max(total - completed - failed, 0)

      return {
        type: 'course',
        batchId,
        tasks: courseTasks,
        title: course?.title || firstTask?.audioMeta?.title || '未命名课程',
        coverUrl: course?.cover_url || firstTask?.audioMeta?.cover_url || '',
        total,
        completed,
        failed,
        running,
      }
    })

    const courseItemsByBatchId = new Map(courseItems.map(item => [item.batchId, item]))
    const orderedItems: HistoryItem[] = []

    tasks.forEach(task => {
      const batchId = getTaskBatchId(task)
      if (!batchId) {
        orderedItems.push({ type: 'single', task })
        return
      }

      const courseItem = courseItemsByBatchId.get(batchId)
      if (!courseItem) return
      orderedItems.push(courseItem)
      courseItemsByBatchId.delete(batchId)
    })

    courseItemsByBatchId.forEach(item => orderedItems.push(item))
    return orderedItems
  }, [batchCourses, tasks])

  const filteredItems = useMemo(() => {
    const trimmedSearch = search.trim()
    if (!trimmedSearch) return historyItems

    return historyItems
      .map<HistoryItem | null>(item => {
        if (item.type === 'single') {
          return matchesSearch(getTaskTitle(item.task), trimmedSearch) ? item : null
        }

        const courseMatched = matchesSearch(item.title, trimmedSearch)
        const matchedTasks = item.tasks.filter(task => matchesSearch(getTaskTitle(task), trimmedSearch))
        if (!courseMatched && matchedTasks.length === 0) return null

        return {
          ...item,
          tasks: courseMatched ? item.tasks : matchedTasks,
        }
      })
      .filter((item): item is HistoryItem => Boolean(item))
  }, [historyItems, search])

  const toggleBatch = (batchId: string) => {
    setExpandedBatchIds(prev => {
      const next = new Set(prev)
      if (next.has(batchId)) {
        next.delete(batchId)
      } else {
        next.add(batchId)
      }
      return next
    })
  }

  const renderTaskCover = (task: Task) => {
    const coverUrl = task.audioMeta?.cover_url
    const platform = task.platform || task.audioMeta?.platform || task.formData?.platform

    if (platform === 'local') {
      return (
        <img
          src={getImageSrc(coverUrl, platform, baseURL)}
          alt="封面"
          className="h-10 w-12 rounded-md object-cover"
        />
      )
    }

    return <LazyImage src={getImageSrc(coverUrl, platform, baseURL)} alt="封面" />
  }

  const renderTitle = (title: string, className = 'line-clamp-2 max-w-[180px] flex-1 overflow-hidden text-sm text-ellipsis') => (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={className}>{title}</div>
        </TooltipTrigger>
        <TooltipContent>
          <p>{title}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )

  const renderDeleteButton = (label: string, onDelete: () => void | Promise<void>) => (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={e => {
              e.stopPropagation()
              void Promise.resolve(onDelete()).catch(error => {
                console.error('删除失败', error)
                toast.error(error instanceof Error ? error.message : '删除失败')
              })
            }}
            className="shrink-0"
          >
            <Trash className="text-muted-foreground h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{label}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )

  const renderStatusBadge = (status?: string) => (
    <div className={cn('w-10 rounded p-0.5 text-center text-white', getStatusClassName(status))}>
      {getStatusLabel(status)}
    </div>
  )

  const renderTaskCard = (task: Task) => (
    <div
      key={task.id}
      onClick={() => onSelect(task.id)}
      className={cn(
        'flex cursor-pointer flex-col rounded-md border border-neutral-200 p-3',
        selectedId === task.id && 'border-primary bg-primary-light'
      )}
    >
      <div className={cn('flex items-center gap-4')}>
        {renderTaskCover(task)}

        <div className="flex w-full items-center justify-between gap-2">
          {renderTitle(getTaskTitle(task))}
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between text-[10px]">
        <div className="shrink-0">{renderStatusBadge(task.status)}</div>

        <div>{renderDeleteButton('删除', () => removeTask(task.id))}</div>
      </div>
    </div>
  )

  const renderCourseCover = (item: HistoryCourseItem) => {
    const platform = item.tasks[0]?.platform || item.tasks[0]?.audioMeta?.platform || item.tasks[0]?.formData?.platform

    if (platform === 'local') {
      return (
        <img
          src={getImageSrc(item.coverUrl, platform, baseURL)}
          alt="课程封面"
          className="h-10 w-12 rounded-md object-cover"
        />
      )
    }

    return <LazyImage src={getImageSrc(item.coverUrl, platform, baseURL)} alt="课程封面" />
  }

  const renderCourseItem = (item: HistoryCourseItem) => {
    const isExpanded = expandedBatchIds.has(item.batchId) || Boolean(search.trim())
    const hasSelectedChild = item.tasks.some(task => task.id === selectedId)

    return (
      <div key={item.batchId} className="flex flex-col gap-1">
        <div
          onClick={() => toggleBatch(item.batchId)}
          className={cn(
            'flex cursor-pointer flex-col rounded-md border border-neutral-200 p-3',
            hasSelectedChild && 'border-primary bg-primary-light'
          )}
        >
          <div className="flex items-center gap-3">
            {isExpanded ? (
              <ChevronDown className="h-4 w-4 shrink-0 text-neutral-500" />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0 text-neutral-500" />
            )}
            {renderCourseCover(item)}

            <div className="flex w-full items-center justify-between gap-2">
              {renderTitle(item.title, 'line-clamp-2 max-w-[160px] flex-1 overflow-hidden text-sm text-ellipsis')}
            </div>
          </div>

          <div className="mt-2 flex items-center justify-between text-[10px]">
            <div className="flex flex-wrap items-center gap-1 text-neutral-500">
              <span className="rounded bg-neutral-100 px-1.5 py-0.5">共 {item.total}</span>
              <span className="rounded bg-primary px-1.5 py-0.5 text-white">完成 {item.completed}</span>
              {item.running > 0 && (
                <span className="rounded bg-green-500 px-1.5 py-0.5 text-white">进行中 {item.running}</span>
              )}
              {item.failed > 0 && (
                <span className="rounded bg-red-500 px-1.5 py-0.5 text-white">失败 {item.failed}</span>
              )}
            </div>
          </div>
        </div>

        {isExpanded && (
          <div className="ml-5 flex flex-col gap-1 border-l border-neutral-200 pl-2">
            {item.tasks.length > 0 ? (
              item.tasks.map(task => (
                <div
                  key={task.id}
                  onClick={() => onSelect(task.id)}
                  className={cn(
                    'flex cursor-pointer items-center justify-between gap-2 rounded-md border border-neutral-200 p-2 text-xs',
                    selectedId === task.id && 'border-primary bg-primary-light'
                  )}
                >
                  <div className="min-w-0 flex-1">
                    {renderTitle(
                      getTaskTitle(task),
                      'line-clamp-2 overflow-hidden text-xs text-ellipsis text-neutral-700'
                    )}
                  </div>
                  <div className="shrink-0 text-[10px]">{renderStatusBadge(task.status)}</div>
                  {renderDeleteButton('删除', () => removeTask(task.id))}
                </div>
              ))
            ) : (
              <div className="rounded-md border border-dashed border-neutral-200 bg-neutral-50 px-3 py-4 text-center text-xs text-neutral-500">
                暂无本地视频记录，刷新或重新生成后可查看子笔记。
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <>
      <div className="mb-2">
        <input
          type="text"
          placeholder="搜索笔记标题..."
          className="w-full rounded border border-neutral-300 px-3 py-1 text-sm outline-none focus:border-primary"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>
      {filteredItems.length === 0 ? (
        <div className="rounded-md border border-neutral-200 bg-neutral-50 py-6 text-center">
          <p className="text-sm text-neutral-500">暂无记录</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2 overflow-hidden">
          {filteredItems.map(item => (item.type === 'single' ? renderTaskCard(item.task) : renderCourseItem(item)))}
        </div>
      )}
    </>
  )
}

export default NoteHistory
