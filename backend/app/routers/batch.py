import uuid
import json
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.enmus.note_enums import DownloadQuality
from app.enmus.task_status_enums import TaskStatus
from app.services.batch_manager import BatchManager
from app.utils.response import ResponseWrapper as R
from app.utils.url_detector import UrlDetector


router = APIRouter()


def _write_status(task_id: str, status: TaskStatus, message: str = '') -> None:
    output_dir = os.getenv('NOTE_OUTPUT_DIR', 'note_results')
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f'{task_id}.status.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'status': status.value, 'message': message}, f, ensure_ascii=False, indent=2)


class DetectUrlRequest(BaseModel):
    url: str


class BatchGenerateRequest(BaseModel):
    video_urls: list[str]
    platform: str
    quality: DownloadQuality
    model_name: str
    provider_id: str
    title: Optional[str] = None
    source_url: Optional[str] = None
    cover_url: Optional[str] = None
    screenshot: Optional[bool] = False
    link: Optional[bool] = False
    format: Optional[list] = []
    style: Optional[str] = None
    extras: Optional[str] = None
    video_understanding: Optional[bool] = False
    video_interval: Optional[int] = 0
    grid_size: Optional[list] = []


class DeleteBatchTaskRequest(BaseModel):
    batch_id: str
    task_id: str


@router.post('/detect_url')
def detect_url(data: DetectUrlRequest):
    try:
        res = UrlDetector.detect(data.url)
        return R.success(data=res)
    except Exception as e:
        return R.error(msg=str(e))


@router.post('/generate_batch_note')
def generate_batch_note(data: BatchGenerateRequest, background_tasks: BackgroundTasks):
    if not data.video_urls:
        raise HTTPException(status_code=400, detail='video_urls is empty')

    mgr = BatchManager()
    batch_id = mgr.create_batch(
        data.video_urls,
        title=data.title or '',
        source_url=data.source_url or data.video_urls[0],
        cover_url=data.cover_url or '',
    )
    task_map: list[dict] = []

    # Schedule each task independently in the shared executor.
    from app.services.task_serial_executor import task_serial_executor
    from app.routers import note as note_router

    for video_url in data.video_urls:
        task_id = str(uuid.uuid4())
        _write_status(task_id, TaskStatus.PENDING)
        mgr.register_task(batch_id, task_id, video_url)
        task_map.append({'video_url': video_url, 'task_id': task_id})

        task_serial_executor.submit(
            note_router._run_note_task_impl,
            task_id,
            video_url,
            data.platform,
            data.quality,
            data.link,
            data.screenshot,
            data.model_name,
            data.provider_id,
            data.format,
            data.style,
            data.extras,
            data.video_understanding,
            data.video_interval,
            data.grid_size,
        )

    return R.success(data={'batch_id': batch_id, 'task_map': task_map})


@router.get('/batch_courses')
def batch_courses():
    mgr = BatchManager()
    return R.success(data=mgr.list_batches())


@router.post('/delete_batch_task')
def delete_batch_task(data: DeleteBatchTaskRequest):
    try:
        mgr = BatchManager()
        result = mgr.delete_task_from_batch(data.batch_id, data.task_id)
        ordered_task_ids = sorted(
            result.get('tasks', {}).keys(),
            key=lambda task_id: (result['tasks'][task_id].get('order', 0), task_id),
        )
        return R.success(
            data={
                **result,
                'deleted_task_id': data.task_id,
                'remaining_task_ids': ordered_task_ids,
            },
            msg='删除成功',
        )
    except FileNotFoundError as e:
        missing_id = e.args[0] if e.args else str(e)
        message = 'batch not found' if missing_id == data.batch_id else 'task not found'
        return R.error(msg=message, code=404)
    except ValueError as e:
        return R.error(msg=str(e), code=400)


@router.delete('/delete_batch/{batch_id}')
def delete_batch(batch_id: str):
    try:
        mgr = BatchManager()
        return R.success(data=mgr.delete_batch(batch_id), msg='删除成功')
    except FileNotFoundError:
        return R.error(msg='batch not found', code=404)
    except ValueError as e:
        return R.error(msg=str(e), code=400)


@router.get('/batch_status/{batch_id}')
def batch_status(batch_id: str):
    try:
        mgr = BatchManager()
        return R.success(data=mgr.refresh_from_task_status(batch_id))
    except FileNotFoundError:
        return R.error(msg='batch not found', code=404)
    except Exception as e:
        return R.error(msg=str(e))
