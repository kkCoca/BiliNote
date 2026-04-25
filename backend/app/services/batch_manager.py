import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.utils.logger import get_logger


logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BatchManager:
    """Persist batch note-generation status as JSON files."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or os.getenv('NOTE_OUTPUT_DIR', 'note_results')
        os.makedirs(self.output_dir, exist_ok=True)

    def _batch_path(self, batch_id: str) -> str:
        return os.path.join(self.output_dir, f'batch_{batch_id}.json')

    def _task_result_path(self, task_id: str) -> str:
        return os.path.join(self.output_dir, f'{task_id}.json')

    def _task_status_path(self, task_id: str) -> str:
        return os.path.join(self.output_dir, f'{task_id}.status.json')

    def _task_artifact_paths(self, task_id: str) -> list[str]:
        return [
            self._task_result_path(task_id),
            self._task_status_path(task_id),
            os.path.join(self.output_dir, f'{task_id}_audio.json'),
            os.path.join(self.output_dir, f'{task_id}_transcript.json'),
            os.path.join(self.output_dir, f'{task_id}_markdown.md'),
            os.path.join(self.output_dir, f'{task_id}_markdown.status.json'),
        ]

    def create_batch(
        self,
        video_urls: list[str],
        *,
        title: str = '',
        source_url: str = '',
        cover_url: str = '',
    ) -> str:
        batch_id = str(uuid.uuid4())
        data: Dict[str, Any] = {
            'batch_id': batch_id,
            'title': title,
            'source_url': source_url,
            'cover_url': cover_url,
            'total': len(video_urls),
            'completed': 0,
            'failed': 0,
            'tasks': {},
            'entries': [
                {'video_url': video_url, 'order': index}
                for index, video_url in enumerate(video_urls)
            ],
            'created_at': _now_iso(),
            'updated_at': _now_iso(),
        }
        self._write(batch_id, data)
        logger.info(f'Batch created: {batch_id}, total={len(video_urls)}')
        return batch_id

    def register_task(self, batch_id: str, task_id: str, video_url: str, *, video_id: str = '') -> None:
        data = self._read(batch_id)
        order = self._entry_order(data, video_url)
        data['tasks'][task_id] = {
            'video_id': video_id,
            'video_url': video_url,
            'status': 'PENDING',
            'error': '',
            'order': order,
        }
        data['updated_at'] = _now_iso()
        self._recount(data)
        self._write(batch_id, data)

    def refresh_from_task_status(self, batch_id: str) -> Dict[str, Any]:
        data = self._read(batch_id)
        for task_id, task in data.get('tasks', {}).items():
            status_path = os.path.join(self.output_dir, f'{task_id}.status.json')
            if not os.path.exists(status_path):
                continue
            try:
                with open(status_path, 'r', encoding='utf-8') as f:
                    status_content = json.load(f)
                st = status_content.get('status')
                msg = status_content.get('message', '')
                if st:
                    task['status'] = st
                if str(st).upper() == 'FAILED' and msg:
                    task['error'] = msg
            except Exception:
                continue

        data['updated_at'] = _now_iso()
        self._recount(data)
        self._write(batch_id, data)
        return data

    def list_batches(self) -> list[Dict[str, Any]]:
        summaries: list[Dict[str, Any]] = []
        for filename in os.listdir(self.output_dir):
            if not filename.startswith('batch_') or not filename.endswith('.json'):
                continue
            path = os.path.join(self.output_dir, filename)
            batch_id = filename[len('batch_'):-len('.json')]
            try:
                data = self.refresh_from_task_status(batch_id)
                summaries.append(self._summary_from_data(data))
            except Exception:
                logger.warning(f'Failed to refresh batch file: {path}', exc_info=True)
        summaries.sort(key=lambda item: item.get('created_at', '') or item.get('updated_at', ''), reverse=True)
        return summaries

    def build_course_view(self, batch_id: str) -> Dict[str, Any]:
        data = self.refresh_from_task_status(batch_id)
        items: list[dict[str, Any]] = []

        for task_id, task in data.get('tasks', {}).items():
            item = {'task_id': task_id, **task}
            result = self._read_task_result(task_id)

            if result:
                audio_meta = result.get('audio_meta', {}) or {}
                item['result_ready'] = True
                item['title'] = audio_meta.get('title') or item.get('title', '')
                item['thumbnail'] = audio_meta.get('cover_url') or item.get('thumbnail', '')
                item['duration'] = audio_meta.get('duration') or item.get('duration', 0)
                item['note_excerpt'] = self._build_excerpt(result.get('markdown', ''))
            else:
                item['result_ready'] = False
                item['note_excerpt'] = ''

            items.append(item)

        items.sort(key=lambda x: (x.get('order', 0), x.get('task_id', '')))
        current_task_id = next((item['task_id'] for item in items if item.get('result_ready')), None)
        if not current_task_id and items:
            current_task_id = items[0]['task_id']

        summary = self._summary_from_data(data)
        if not summary.get('cover_url'):
            summary['cover_url'] = next((item.get('thumbnail', '') for item in items if item.get('thumbnail')), '')
        if not summary.get('title'):
            summary['title'] = (items[0].get('title') if items else '批量课程') or '批量课程'

        return {
            **summary,
            'current_task_id': current_task_id,
            'items': items,
        }

    def delete_task_from_batch(self, batch_id: str, task_id: str) -> Dict[str, Any]:
        data = self.refresh_from_task_status(batch_id)
        tasks = data.get('tasks', {})
        if task_id not in tasks:
            raise FileNotFoundError(task_id)

        task = tasks[task_id]
        self._ensure_task_deletable(task_id, task)

        self._delete_task_artifacts(task_id)
        tasks.pop(task_id)
        data['total'] = len(tasks)
        data['updated_at'] = _now_iso()
        self._recount(data)
        self._write(batch_id, data)
        return data

    def delete_batch(self, batch_id: str) -> Dict[str, Any]:
        data = self.refresh_from_task_status(batch_id)
        self._ensure_batch_terminal(data)

        task_ids = sorted(
            data.get('tasks', {}).keys(),
            key=lambda tid: (data['tasks'][tid].get('order', 0), tid),
        )

        for task_id in task_ids:
            self._delete_task_artifacts(task_id)

        batch_path = self._batch_path(batch_id)
        if os.path.exists(batch_path):
            os.remove(batch_path)

        logger.info(f'Batch deleted: {batch_id}, tasks={len(task_ids)}')
        return {'batch_id': batch_id, 'deleted_task_ids': task_ids}

    def _delete_task_artifacts(self, task_id: str) -> None:
        try:
            from app.db.video_task_dao import delete_tasks_by_task_ids

            delete_tasks_by_task_ids([task_id])
        except ImportError:
            from app.db.engine import get_db
            from app.db.models.video_tasks import VideoTask

            db = next(get_db())
            try:
                tasks = db.query(VideoTask).filter_by(task_id=task_id).all()
                for task in tasks:
                    db.delete(task)
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        for path in self._task_artifact_paths(task_id):
            if os.path.exists(path):
                os.remove(path)

    def _read(self, batch_id: str) -> Dict[str, Any]:
        path = self._batch_path(batch_id)
        if not os.path.exists(path):
            raise FileNotFoundError(batch_id)
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write(self, batch_id: str, data: Dict[str, Any]) -> None:
        path = self._batch_path(batch_id)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _read_task_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        path = self._task_result_path(task_id)
        if not os.path.exists(path):
            return None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _build_excerpt(markdown: str, limit: int = 280) -> str:
        text = str(markdown or '')
        text = re.sub(r'^>\s*来源链接：[^\n]*\n*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
        text = re.sub(r'[`>*_#-]+', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:limit]

    @staticmethod
    def _summary_from_data(data: Dict[str, Any]) -> Dict[str, Any]:
        tasks = data.get('tasks', {}) or {}
        total = len(tasks) if tasks else int(data.get('total', 0) or 0)
        completed = 0
        failed = 0
        running = 0
        for task in tasks.values():
            status = str(task.get('status') or '').upper()
            if status == 'SUCCESS':
                completed += 1
            elif status == 'FAILED':
                failed += 1
            else:
                running += 1

        if not tasks:
            completed = int(data.get('completed', 0) or 0)
            failed = int(data.get('failed', 0) or 0)
            running = 0

        if not tasks or total == 0:
            status = 'EMPTY'
        elif running > 0:
            status = 'RUNNING'
        elif failed > 0:
            status = 'FAILED'
        else:
            status = 'SUCCESS'

        return {
            'batch_id': data.get('batch_id', ''),
            'title': data.get('title', '') or '',
            'source_url': data.get('source_url', '') or '',
            'cover_url': data.get('cover_url', '') or '',
            'total': total,
            'completed': completed,
            'failed': failed,
            'running': running,
            'status': status,
            'created_at': data.get('created_at', '') or '',
            'updated_at': data.get('updated_at', '') or '',
        }

    @staticmethod
    def _recount(data: Dict[str, Any]) -> None:
        completed = 0
        failed = 0
        for t in data.get('tasks', {}).values():
            st = (t.get('status') or '').upper()
            if st == 'SUCCESS':
                completed += 1
            elif st == 'FAILED':
                failed += 1
        data['total'] = len(data.get('tasks', {}))
        data['completed'] = completed
        data['failed'] = failed

    @staticmethod
    def _entry_order(data: Dict[str, Any], video_url: str) -> int:
        used_orders = {
            task.get('order')
            for task in data.get('tasks', {}).values()
            if isinstance(task.get('order'), int)
        }
        for index, entry in enumerate(data.get('entries', []) or []):
            entry_url = entry.get('video_url') if isinstance(entry, dict) else entry
            order = entry.get('order', index) if isinstance(entry, dict) else index
            if entry_url == video_url and order not in used_orders:
                return int(order)
        return len(data.get('tasks', {}))

    def _ensure_task_deletable(self, task_id: str, task: Dict[str, Any]) -> None:
        status = str(task.get('status') or '').upper()
        if status not in ('SUCCESS', 'FAILED'):
            raise ValueError('当前任务进行中，暂不允许删除')
        if status == 'SUCCESS' and not os.path.exists(self._task_result_path(task_id)):
            raise ValueError('当前任务进行中，暂不允许删除')

    @staticmethod
    def _ensure_batch_terminal(data: Dict[str, Any]) -> None:
        for task in data.get('tasks', {}).values():
            status = str(task.get('status') or '').upper()
            if status not in ('SUCCESS', 'FAILED'):
                raise ValueError('当前合集仍有任务进行中，暂不允许删除')
