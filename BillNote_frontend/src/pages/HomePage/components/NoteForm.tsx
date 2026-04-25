/* NoteForm.tsx ---------------------------------------------------- */
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form.tsx'
import { useEffect, useState } from 'react'
import { useForm, useWatch, type FieldErrors, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'

import { Info, Loader2, Plus } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert.tsx'
import { generateNote } from '@/services/note.ts'
import { detectUrl, generateBatchNote, getBatchStatus, toBatchCourseSummary, type DetectedEntry } from '@/services/batch.ts'
import { uploadFile } from '@/services/upload.ts'
import { useTaskStore, type TaskFormData } from '@/store/taskStore'
import { useModelStore } from '@/store/modelStore'
import toast from 'react-hot-toast'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip.tsx'
import { Checkbox } from '@/components/ui/checkbox.tsx'
import { ScrollArea } from '@/components/ui/scroll-area.tsx'
import { Button } from '@/components/ui/button.tsx'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select.tsx'
import { Input } from '@/components/ui/input.tsx'
import { Textarea } from '@/components/ui/textarea.tsx'
import { noteStyles, noteFormats, videoPlatforms } from '@/constant/note.ts'
import { useNavigate } from 'react-router-dom'

/* -------------------- 校验 Schema -------------------- */
const formSchema = z
  .object({
    video_url: z.string().optional(),
    platform: z.string().nonempty('请选择平台'),
    quality: z.enum(['fast', 'medium', 'slow']),
    screenshot: z.boolean().optional(),
    link: z.boolean().optional(),
    model_name: z.string().nonempty('请选择模型'),
    format: z.array(z.string()).default([]),
    style: z.string().nonempty('请选择笔记生成风格'),
    extras: z.string().optional(),
    video_understanding: z.boolean().optional(),
    video_interval: z.coerce.number().min(1).max(30).default(6).optional(),
    grid_size: z
      .tuple([z.coerce.number().min(1).max(10), z.coerce.number().min(1).max(10)])
      .default([2, 2])
      .optional(),
  })
  .superRefine(({ video_url, platform }, ctx) => {
    if (platform === 'local') {
      if (!video_url) {
        ctx.addIssue({ code: 'custom', message: '本地视频路径不能为空', path: ['video_url'] })
      }
    }
    else {
      if (!video_url) {
        ctx.addIssue({ code: 'custom', message: '视频链接不能为空', path: ['video_url'] })
      }
      else {
        try {
          const url = new URL(video_url)
          if (!['http:', 'https:'].includes(url.protocol))
            throw new Error()
        }
        catch {
          ctx.addIssue({ code: 'custom', message: '请输入正确的视频链接', path: ['video_url'] })
        }
      }
    }
  })

export type NoteFormValues = z.infer<typeof formSchema>

type BatchPayload = NoteFormValues & {
  provider_id: string
  task_id: string
}

type BatchTask = {
  video_url: string
  title: string
  task_id: string
}

const getErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof Error && error.message) {
    return error.message
  }

  return fallback
}

/* -------------------- 可复用子组件 -------------------- */
const SectionHeader = ({ title, tip }: { title: string; tip?: string }) => (
  <div className="my-3 flex items-center justify-between">
    <h2 className="block">{title}</h2>
    {tip && (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Info className="hover:text-primary h-4 w-4 cursor-pointer text-neutral-400" />
          </TooltipTrigger>
          <TooltipContent className="text-xs">{tip}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    )}
  </div>
)

const CheckboxGroup = ({
  value = [],
  onChange,
  disabledMap,
}: {
  value?: string[]
  onChange: (v: string[]) => void
  disabledMap: Record<string, boolean>
}) => (
  <div className="flex flex-wrap space-x-1.5">
    {noteFormats.map(({ label, value: v }) => (
      <label key={v} className="flex items-center space-x-2">
        <Checkbox
          checked={value.includes(v)}
          disabled={disabledMap[v]}
          onCheckedChange={checked =>
            onChange(checked ? [...value, v] : value.filter(x => x !== v))
          }
        />
        <span>{label}</span>
      </label>
    ))}
  </div>
)

/* -------------------- 主组件 -------------------- */
const NoteForm = () => {
  const navigate = useNavigate();
  const [isUploading, setIsUploading] = useState(false)
  const [uploadSuccess, setUploadSuccess] = useState(false)
  const [detectingUrl, setDetectingUrl] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewEntries, setPreviewEntries] = useState<DetectedEntry[]>([])
  const [previewTitle, setPreviewTitle] = useState('')
  const [previewSourceUrl, setPreviewSourceUrl] = useState('')
  const [previewCoverUrl, setPreviewCoverUrl] = useState('')
  const [selectedVideoUrls, setSelectedVideoUrls] = useState<Record<string, boolean>>({})
  const [pendingBatchPayload, setPendingBatchPayload] = useState<BatchPayload | null>(null)
  const [activeBatch, setActiveBatch] = useState<
    | null
    | {
        batchId: string
        items: BatchTask[]
      }
  >(null)
  /* ---- 全局状态 ---- */
  const { addPendingTask, currentTaskId, setCurrentTask, getCurrentTask, retryTask, upsertBatchCourse } =
    useTaskStore()
  const { loadEnabledModels, modelList } = useModelStore()

  /* ---- 表单 ---- */
  const form = useForm<NoteFormValues>({
    resolver: zodResolver(formSchema) as Resolver<NoteFormValues>,
    defaultValues: {
      platform: 'bilibili',
      quality: 'medium',
      model_name: modelList[0]?.model_name || '',
      style: 'minimal',
      video_interval: 6,
      grid_size: [2, 2],
      format: [],
    },
  })
  const currentTask = getCurrentTask()

  /* ---- 派生状态（只 watch 一次，提高性能） ---- */
  const platform = useWatch({ control: form.control, name: 'platform' }) as string
  const videoUnderstandingEnabled = useWatch({ control: form.control, name: 'video_understanding' })
  const editing = currentTask && currentTask.id

  const goModelAdd = () => {
    navigate("/settings/model");
  };
  /* ---- 副作用 ---- */
  useEffect(() => {
    loadEnabledModels()

    return
  }, [])
  useEffect(() => {
    if (!currentTask) {
      form.reset({
        platform: 'bilibili',
        video_url: '',
        model_name: modelList[0]?.model_name || '',
        style: 'minimal',
        quality: 'medium',
        extras: '',
        screenshot: false,
        link: false,
        video_understanding: false,
        video_interval: 6,
        grid_size: [2, 2],
        format: [],
      })
      return
    }

    const { formData } = currentTask

    console.log('currentTask.formData.platform:', formData.platform)

    form.reset({
      platform: formData.platform || 'bilibili',
      video_url: formData.video_url || '',
      model_name: formData.model_name || modelList[0]?.model_name || '',
      style: formData.style || 'minimal',
      quality: formData.quality === 'fast' || formData.quality === 'medium' || formData.quality === 'slow'
        ? formData.quality
        : 'medium',
      extras: formData.extras || '',
      screenshot: formData.screenshot ?? false,
      link: formData.link ?? false,
      video_understanding: formData.video_understanding ?? false,
      video_interval: formData.video_interval ?? 6,
      grid_size: Array.isArray(formData.grid_size) && formData.grid_size.length >= 2
        ? [formData.grid_size[0], formData.grid_size[1]]
        : [2, 2],
      format: formData.format ?? [],
    })
  }, [
    // 当下面任意一个变了，就重新 reset
    currentTaskId,
    // modelList 用来兜底 model_name
    modelList.length,
    // 还要加上 formData 的各字段，或者直接 currentTask
    currentTask?.formData,
  ])

  /* ---- 帮助函数 ---- */
  const isBilibiliSpaceUrl = (u?: string) => /space\.bilibili\.com\/(\d+)/.test(String(u || ''))
  const isGenerating = () => !['SUCCESS', 'FAILED', undefined].includes(getCurrentTask()?.status)
  const generating = isGenerating()
  const handleFileUpload = async (file: File, cb: (url: string) => void) => {
    const formData = new FormData()
    formData.append('file', file)
    setIsUploading(true)
    setUploadSuccess(false)

    try {
  
      const  data  = await uploadFile(formData)
        cb(data.url)
        setUploadSuccess(true)
    } catch (err) {
      console.error('上传失败:', err)
      // message.error('上传失败，请重试')
    } finally {
      setIsUploading(false)
    }
  }

  const toTaskFormData = (payload: BatchPayload, videoUrl = payload.video_url || '', batchId?: string): TaskFormData => ({
    video_url: videoUrl,
    link: payload.link,
    screenshot: payload.screenshot,
    platform: payload.platform,
    quality: payload.quality,
    model_name: payload.model_name,
    provider_id: payload.provider_id,
    style: payload.style,
    batchId,
    format: payload.format,
    extras: payload.extras,
    video_understanding: payload.video_understanding,
    video_interval: payload.video_interval,
    grid_size: payload.grid_size,
  })

  const openPreview = (
    entries: DetectedEntry[],
    payloadForBatch: BatchPayload,
    meta: { title?: string; source_url?: string; cover_url?: string } = {},
  ) => {
    const selected: Record<string, boolean> = {}
    for (const e of entries) {
      if (e.video_url) selected[e.video_url] = true
    }
    setPreviewEntries(entries)
    setPreviewTitle(meta.title || '')
    setPreviewSourceUrl(meta.source_url || '')
    setPreviewCoverUrl(meta.cover_url || '')
    setSelectedVideoUrls(selected)
    setPendingBatchPayload(payloadForBatch)
    setPreviewOpen(true)
  }

  const confirmBatchGenerate = async () => {
    const payload = pendingBatchPayload
    if (!payload) return

    const urls = Object.entries(selectedVideoUrls)
      .filter(([, v]) => v)
      .map(([u]) => u)
      .filter(Boolean)

    if (!urls.length) {
      toast.error('请至少选择 1 个视频')
      return
    }

    const selectedEntries = urls
      .map(url => previewEntries.find(entry => entry.video_url === url))
      .filter((entry): entry is DetectedEntry => Boolean(entry))
    const batchTitle = previewTitle || '批量课程'
    const batchSourceUrl = previewSourceUrl || pendingBatchPayload?.video_url || urls[0] || ''
    const batchCoverUrl = previewCoverUrl || selectedEntries[0]?.thumbnail || ''

    try {
      setDetectingUrl(true)
      const res = await generateBatchNote({
        video_urls: urls,
        title: batchTitle,
        source_url: batchSourceUrl,
        cover_url: batchCoverUrl,
        platform: payload.platform,
        quality: payload.quality,
        model_name: payload.model_name,
        provider_id: payload.provider_id,
        format: payload.format || [],
        style: payload.style,
        extras: payload.extras,
        screenshot: payload.screenshot,
        link: payload.link,
        video_understanding: payload.video_understanding,
        video_interval: payload.video_interval,
        grid_size: payload.grid_size || [2, 2],
      })

      const taskMap = res.task_map || []
      const titleByUrl = new Map(previewEntries.map(e => [e.video_url, e.title]))
      const items: BatchTask[] = taskMap.map((x: { video_url: string; task_id: string }) => ({
        video_url: x.video_url,
        task_id: x.task_id,
        title: titleByUrl.get(x.video_url) || x.video_url,
      }))

      for (const it of items) {
        addPendingTask(it.task_id, payload.platform, toTaskFormData(payload, it.video_url, res.batch_id))
      }

      const now = new Date().toISOString()
      upsertBatchCourse(
        toBatchCourseSummary({
          batch_id: res.batch_id,
          title: batchTitle,
          source_url: batchSourceUrl,
          cover_url: batchCoverUrl,
          total: items.length,
          completed: 0,
          failed: 0,
          tasks: Object.fromEntries(
            items.map((item, order) => [
              item.task_id,
              { video_url: item.video_url, status: 'PENDING', order },
            ])
          ),
          entries: urls.map((video_url, order) => ({ video_url, order })),
          created_at: now,
          updated_at: now,
        })
      )

      getBatchStatus(res.batch_id)
        .then(rawStatus => upsertBatchCourse(toBatchCourseSummary(rawStatus)))
        .catch(error => {
          console.error('刷新批量课程摘要失败：', error)
        })

      setActiveBatch({ batchId: res.batch_id, items })
      setPreviewOpen(false)
      setPreviewTitle('')
      setPreviewSourceUrl('')
      setPreviewCoverUrl('')
      toast.success(`已提交批量任务：${items.length} 个`)
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, '批量提交失败'))
    } finally {
      setDetectingUrl(false)
    }
  }

  const selectedCount = previewEntries.reduce((acc, e) => acc + (selectedVideoUrls[e.video_url] ? 1 : 0), 0)

  const onSubmit = async (values: NoteFormValues) => {
    const providerId = modelList.find(m => m.model_name === values.model_name)?.provider_id
    if (!providerId) {
      toast.error('请选择模型')
      return
    }

    const payload: BatchPayload = {
      ...values,
      provider_id: providerId,
      task_id: currentTaskId || '',
    }

    // Collection/space links are multi-video flows; retrying a single task ID here is incorrect.
    if (currentTaskId && isBilibiliSpaceUrl(values.video_url)) {
      toast.error('合集链接不支持“重试/重新生成”，请点「新建笔记」后再操作')
      return
    }
    if (currentTaskId) {
      retryTask(currentTaskId, toTaskFormData(payload))
      return
    }

    if (values.platform !== 'local') {
      // Force multi-video preview for bilibili space URLs.
      if (isBilibiliSpaceUrl(values.video_url)) {
        try {
          setDetectingUrl(true)
          const detected = await detectUrl(values.video_url || '')
          const n = detected?.entries?.length || 0
          if (n > 1) {
            openPreview(detected.entries, payload, detected)
            return
          }
          toast.error('未解析到视频列表，请稍后重试')
          return
        } catch (error: unknown) {
          console.warn('detect_url failed for bilibili space url:', error)
          toast.error(getErrorMessage(error, '解析视频列表失败，请稍后重试'))
          return
        } finally {
          setDetectingUrl(false)
        }
      }

      // Other URLs: detection is best-effort.
      try {
        setDetectingUrl(true)
        const detected = await detectUrl(values.video_url || '')
        if (detected?.type === 'multi' && (detected.entries?.length || 0) > 1) {
          openPreview(detected.entries, payload)
          return
        }
      } catch (error: unknown) {
        console.warn('detect_url failed, fallback to generate_note:', error)
      } finally {
        setDetectingUrl(false)
      }
    }

    const data = await generateNote({
      ...payload,
      video_url: payload.video_url || '',
      format: payload.format || [],
      style: payload.style || '',
      grid_size: payload.grid_size || [2, 2],
    })
    if (!data) return
    addPendingTask(data.task_id, values.platform, toTaskFormData(payload))
  }
  const onInvalid = (errors: FieldErrors<NoteFormValues>) => {
    console.warn('表单校验失败：', errors)
    // message.error('请完善所有必填项后再提交')
  }
  const handleCreateNew = () => {
    // 🔁 这里清空当前任务状态
    // 比如调用 resetCurrentTask() 或者 navigate 到一个新页面
    setCurrentTask(null)
  }
  const FormButton = () => {
    const label = generating ? '正在生成…' : editing ? '重新生成' : '生成笔记'

    const handlePreviewClick = async () => {
      const v = form.getValues()
      if (!v.video_url || v.platform === 'local') {
        toast.error('请输入在线视频链接后再预览')
        return
      }
      const providerId = modelList.find(m => m.model_name === v.model_name)?.provider_id
      if (!providerId) {
        toast.error('请选择模型')
        return
      }

      const payload: BatchPayload = {
        ...v,
        provider_id: providerId,
        task_id: '',
      }
      try {
        setDetectingUrl(true)
        const detected = await detectUrl(v.video_url)
        if ((detected.entries?.length || 0) <= 1) {
          toast('检测到单个视频')
          return
        }
        openPreview(detected.entries, payload)
      } catch (error: unknown) {
        // Keep error explicit for space/collection URLs; otherwise users may think it generated only one item.
        toast.error(
          getErrorMessage(
            error,
            isBilibiliSpaceUrl(v.video_url) ? '解析视频列表失败，请稍后重试' : '预览失败',
          ),
        )
      } finally {
        setDetectingUrl(false)
      }
    }

    return (
      <div className="flex gap-2">
        <Button
          type="submit"
          className={!editing ? 'w-full' : 'w-2/3' + ' bg-primary'}
          disabled={generating || detectingUrl}
        >
          {generating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {detectingUrl && !generating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {label}
        </Button>

        {!editing && (
          <Button type="button" variant="outline" onClick={handlePreviewClick} disabled={detectingUrl}>
            预览
          </Button>
        )}

        {editing && (
          <Button type="button" variant="outline" className="w-1/3" onClick={handleCreateNew}>
            <Plus className="mr-2 h-4 w-4" />
            新建笔记
          </Button>
        )}
      </div>
    )
  }

  /* -------------------- 渲染 -------------------- */
  return (
    <div className="h-full w-full">
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit, onInvalid)} className="space-y-4">
          {/* 顶部按钮 */}
          <FormButton></FormButton>

          {activeBatch && (
            <Alert>
              <AlertDescription>
                批次 {activeBatch.batchId}：共 {activeBatch.items.length} 个任务已提交。
              </AlertDescription>
            </Alert>
          )}

          {/* 视频链接 & 平台 */}
          <SectionHeader title="视频链接" tip="支持 B 站、YouTube 等平台" />
          <div className="flex gap-2">
            {/* 平台选择 */}

            <FormField
              control={form.control}
              name="platform"
              render={({ field }) => (
                <FormItem>
                  <Select
                    disabled={!!editing}
                    value={field.value}
                    onValueChange={field.onChange}
                    defaultValue={field.value}
                  >
                    <FormControl>
                      <SelectTrigger className="w-32">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {videoPlatforms?.map(p => (
                        <SelectItem key={p.value} value={p.value}>
                          <div className="flex items-center justify-center gap-2">
                            <div className="h-4 w-4">{p.logo()}</div>
                            <span>{p.label}</span>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage style={{ display: 'none' }} />
                </FormItem>
              )}
            />
            {/* 链接输入 / 上传框 */}
            <FormField
              control={form.control}
              name="video_url"
              render={({ field }) => (
                <FormItem className="flex-1">
                  {platform === 'local' ? (
                    <>
                      <Input disabled={!!editing} placeholder="请输入本地视频路径" {...field} />
                    </>
                  ) : (
                    <Input disabled={!!editing} placeholder="请输入视频网站链接" {...field} />
                  )}
                  <FormMessage style={{ display: 'none' }} />
                </FormItem>
              )}
            />
          </div>

          {platform === 'local' && (
            <FormItem className="flex-1">
              <div
                className="hover:border-primary mt-2 flex h-40 cursor-pointer items-center justify-center rounded-md border-2 border-dashed border-gray-300 transition-colors"
                onDragOver={e => {
                  e.preventDefault()
                  e.stopPropagation()
                }}
                onDrop={e => {
                  e.preventDefault()
                  const file = e.dataTransfer.files?.[0]
                  if (file) handleFileUpload(file, url => form.setValue('video_url', url, { shouldDirty: true }))
                }}
                onClick={() => {
                  const input = document.createElement('input')
                  input.type = 'file'
                  input.accept = 'video/*'
                  input.onchange = e => {
                    const file = (e.target as HTMLInputElement).files?.[0]
                    if (file) handleFileUpload(file, url => form.setValue('video_url', url, { shouldDirty: true }))
                  }
                  input.click()
                }}
              >
                {isUploading ? (
                  <p className="text-center text-sm text-blue-500">上传中，请稍候…</p>
                ) : uploadSuccess ? (
                  <p className="text-center text-sm text-green-500">上传成功！</p>
                ) : (
                  <p className="text-center text-sm text-gray-500">
                    拖拽文件到这里上传 <br />
                    <span className="text-xs text-gray-400">或点击选择文件</span>
                  </p>
                )}
              </div>
            </FormItem>
          )}
          <div className="grid grid-cols-2 gap-2">
            {/* 模型选择 */}
            {

             modelList.length>0?(     <FormField
               control={form.control}
               name="model_name"
               render={({ field }) => (
                 <FormItem>
                   <SectionHeader title="模型选择" tip="不同模型效果不同，建议自行测试" />
                   <Select
                     onOpenChange={()=>{
                       loadEnabledModels()
                     }}
                     value={field.value}
                     onValueChange={field.onChange}
                     defaultValue={field.value}
                   >
                     <FormControl>
                       <SelectTrigger className="w-full min-w-0 truncate">
                         <SelectValue />
                       </SelectTrigger>
                     </FormControl>
                     <SelectContent>
                       {modelList.map(m => (
                         <SelectItem key={m.id} value={m.model_name}>
                           {m.model_name}
                         </SelectItem>
                       ))}
                     </SelectContent>
                   </Select>
                   <FormMessage />
                 </FormItem>
               )}
             />): (
               <FormItem>
                 <SectionHeader title="模型选择" tip="不同模型效果不同，建议自行测试" />
                  <Button type={'button'} variant={
                    'outline'
                  } onClick={()=>{goModelAdd()}}>请先添加模型</Button>
                 <FormMessage />
               </FormItem>
             )
            }

            {/* 笔记风格 */}
            <FormField
              control={form.control}
              name="style"
              render={({ field }) => (
                <FormItem>
                  <SectionHeader title="笔记风格" tip="选择生成笔记的呈现风格" />
                  <Select
                    value={field.value}
                    onValueChange={field.onChange}
                    defaultValue={field.value}
                  >
                    <FormControl>
                      <SelectTrigger className="w-full min-w-0 truncate">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {noteStyles.map(({ label, value }) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
          {/* 视频理解 */}
          <SectionHeader title="视频理解" tip="将视频截图发给多模态模型辅助分析" />
          <div className="flex flex-col gap-2">
            <FormField
              control={form.control}
              name="video_understanding"
              render={() => (
                <FormItem>
                  <div className="flex items-center gap-2">
                    <FormLabel>启用</FormLabel>
                    <Checkbox
                      checked={!!videoUnderstandingEnabled}
                      onCheckedChange={v => form.setValue('video_understanding', v === true)}
                    />
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-2 gap-4">
              {/* 采样间隔 */}
              <FormField
                control={form.control}
                name="video_interval"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>采样间隔（秒）</FormLabel>
                    <Input disabled={!videoUnderstandingEnabled} type="number" {...field} />
                    <FormMessage />
                  </FormItem>
                )}
              />
              {/* 拼图大小 */}
              <FormField
                control={form.control}
                name="grid_size"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>拼图尺寸（列 × 行）</FormLabel>
                    <div className="flex items-center space-x-2">
                      <Input
                        disabled={!videoUnderstandingEnabled}
                        type="number"
                        value={field.value?.[0] || 3}
                        onChange={e => field.onChange([+e.target.value, field.value?.[1] || 3])}
                        className="w-16"
                      />
                      <span>x</span>
                      <Input
                        disabled={!videoUnderstandingEnabled}
                        type="number"
                        value={field.value?.[1] || 3}
                        onChange={e => field.onChange([field.value?.[0] || 3, +e.target.value])}
                        className="w-16"
                      />
                    </div>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <Alert variant="warning" className="text-sm">
              <AlertDescription>
                <strong>提示：</strong>视频理解功能必须使用多模态模型。
              </AlertDescription>
            </Alert>
          </div>

          {/* 笔记格式 */}
          <FormField
            control={form.control}
            name="format"
            render={({ field }) => (
              <FormItem>
                <SectionHeader title="笔记格式" tip="选择要包含的笔记元素" />
                <CheckboxGroup
                  value={field.value}
                  onChange={field.onChange}
                  disabledMap={{
                    link: platform === 'local',
                    screenshot: !videoUnderstandingEnabled,
                  }}
                />
                <FormMessage />
              </FormItem>
            )}
          />

          {/* 备注 */}
          <FormField
            control={form.control}
            name="extras"
            render={({ field }) => (
              <FormItem>
                <SectionHeader title="备注" tip="可在 Prompt 结尾附加自定义说明" />
                <Textarea placeholder="笔记需要罗列出 xxx 关键点…" {...field} />
                <FormMessage />
              </FormItem>
            )}
          />
        </form>
      </Form>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{previewTitle || '视频列表预览'}（共 {previewEntries.length} 条）</DialogTitle>
            <DialogDescription>
              勾选要生成笔记的视频，然后点击“批量生成”。已选 {selectedCount} 条。
            </DialogDescription>
          </DialogHeader>

          <div className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
            <label className="flex items-center gap-2">
              <Checkbox
                checked={previewEntries.length > 0 && selectedCount === previewEntries.length}
                onCheckedChange={checked => {
                  const next: Record<string, boolean> = {}
                  for (const e of previewEntries) next[e.video_url] = !!checked
                  setSelectedVideoUrls(next)
                }}
              />
              全选
            </label>
            <div className="text-neutral-500">已选 {selectedCount}/{previewEntries.length}</div>
          </div>

          <ScrollArea className="h-[380px] pr-2">
            <div className="space-y-2">
              {previewEntries.map(e => (
                <label key={e.video_url} className="flex items-start gap-3 rounded-md border p-3">
                  <Checkbox
                    checked={!!selectedVideoUrls[e.video_url]}
                    onCheckedChange={checked =>
                      setSelectedVideoUrls(prev => ({ ...prev, [e.video_url]: !!checked }))
                    }
                  />
                  <div className="min-w-0">
                    <div
                      className="font-medium text-sm leading-5"
                      title={e.title || e.video_url}
                      style={{
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}
                    >
                      {e.title || e.video_url}
                    </div>
                    <div className="truncate text-xs text-neutral-500">{e.video_url}</div>
                  </div>
                </label>
              ))}
            </div>
          </ScrollArea>

          <DialogFooter>
            <div className="mr-auto text-sm text-neutral-600">已选 {selectedCount}/{previewEntries.length}</div>
            <Button variant="outline" onClick={() => setPreviewOpen(false)}>
              取消
            </Button>
            <Button onClick={confirmBatchGenerate} disabled={detectingUrl}>
              批量生成
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default NoteForm
