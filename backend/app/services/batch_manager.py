import json
import os
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

    def create_batch(self, video_urls: list[str]) -> str:
        batch_id = str(uuid.uuid4())
        data: Dict[str, Any] = {
            'batch_id': batch_id,
            'total': len(video_urls),
            'completed': 0,
            'failed': 0,
            'tasks': {},
            'created_at': _now_iso(),
            'updated_at': _now_iso(),
        }
        self._write(batch_id, data)
        logger.info(f'Batch created: {batch_id}, total={len(video_urls)}')
        return batch_id

    def register_task(self, batch_id: str, task_id: str, video_url: str, *, video_id: str = '') -> None:
        data = self._read(batch_id)
        data['tasks'][task_id] = {
            'video_id': video_id,
            'video_url': video_url,
            'status': 'PENDING',
            'error': '',
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
        data['completed'] = completed
        data['failed'] = failed
