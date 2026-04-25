import json
import os
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def _reset_app_modules() -> None:
    for k in list(sys.modules.keys()):
        if k == 'app' or k.startswith('app.'):
            sys.modules.pop(k, None)


class TestBatchRoutes(unittest.TestCase):
    def _client(self):
        _reset_app_modules()
        from app.routers.batch import router

        app = FastAPI()
        app.include_router(router, prefix='/api')
        return TestClient(app)

    def test_detect_url_route(self):
        c = self._client()

        import importlib
        batch = importlib.import_module('app.routers.batch')
        with patch.object(batch, 'UrlDetector') as mock_detector:
            mock_detector.detect.return_value = {'type': 'multi', 'entries': [{'video_url': 'u'}]}
            r = c.post('/api/detect_url', json={'url': 'x'})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['code'], 0)
        self.assertEqual(body['data']['type'], 'multi')

    def test_generate_batch_note_returns_batch_id(self):
        original_note_output_dir = os.environ.get('NOTE_OUTPUT_DIR')
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ['NOTE_OUTPUT_DIR'] = td
                c = self._client()

                import importlib
                importlib.import_module('app.routers.batch')

                # Avoid importing the real note pipeline (it may require optional deps).
                dummy_note = types.ModuleType('app.routers.note')
                dummy_note._run_note_task_impl = lambda *_a, **_kw: None
                sys.modules['app.routers.note'] = dummy_note

                payload = {
                    'video_urls': ['https://www.bilibili.com/video/BV1xx/'],
                    'platform': 'bilibili',
                    'quality': 'medium',
                    'model_name': 'm',
                    'provider_id': 'p',
                    'format': [],
                    'style': 'minimal',
                    'grid_size': [2, 2],
                }

                r = c.post('/api/generate_batch_note', json=payload)
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertEqual(body['code'], 0)
                self.assertIn('batch_id', body['data'])
                self.assertEqual(len(body['data']['task_map']), 1)
        finally:
            if original_note_output_dir is None:
                os.environ.pop('NOTE_OUTPUT_DIR', None)
            else:
                os.environ['NOTE_OUTPUT_DIR'] = original_note_output_dir
            _reset_app_modules()

    def test_batch_courses_route_returns_summaries(self):
        original_note_output_dir = os.environ.get('NOTE_OUTPUT_DIR')
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ['NOTE_OUTPUT_DIR'] = td
                _reset_app_modules()

                from app.services.batch_manager import BatchManager

                mgr = BatchManager()
                batch_id = mgr.create_batch(['https://example.com/course/1'])
                mgr.register_task(batch_id, 'task-1', 'https://example.com/course/1')

                with open(f'{td}/task-1.status.json', 'w', encoding='utf-8') as f:
                    json.dump({'status': 'SUCCESS', 'message': ''}, f)

                mgr.refresh_from_task_status(batch_id)
                c = self._client()

                r = c.get('/api/batch_courses')
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertEqual(body['code'], 0)
                self.assertEqual(len(body['data']), 1)
                summary = body['data'][0]
                self.assertEqual(summary['batch_id'], batch_id)
                self.assertEqual(summary['title'], '')
                self.assertEqual(summary['completed'], 1)
        finally:
            if original_note_output_dir is None:
                os.environ.pop('NOTE_OUTPUT_DIR', None)
            else:
                os.environ['NOTE_OUTPUT_DIR'] = original_note_output_dir
            _reset_app_modules()

    def test_delete_batch_task_route_removes_one_child(self):
        original_database_url = os.environ.get('DATABASE_URL')
        original_note_output_dir = os.environ.get('NOTE_OUTPUT_DIR')
        try:
            with tempfile.TemporaryDirectory() as td:
                db_path = os.path.join(td, 'test.db')
                os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'
                os.environ['NOTE_OUTPUT_DIR'] = td
                _reset_app_modules()

                from app.db.engine import Base, SessionLocal, engine
                from app.db.models.video_tasks import VideoTask
                from app.services.batch_manager import BatchManager

                Base.metadata.create_all(bind=engine)
                db = SessionLocal()
                db.add(VideoTask(video_id='video-1', platform='bilibili', task_id='task-1'))
                db.add(VideoTask(video_id='video-2', platform='bilibili', task_id='task-2'))
                db.commit()
                db.close()

                mgr = BatchManager()
                batch_id = mgr.create_batch(['https://example.com/course/1', 'https://example.com/course/2'])
                mgr.register_task(batch_id, 'task-1', 'https://example.com/course/1')
                mgr.register_task(batch_id, 'task-2', 'https://example.com/course/2')
                for task_id in ('task-1', 'task-2'):
                    with open(f'{td}/{task_id}.status.json', 'w', encoding='utf-8') as f:
                        json.dump({'status': 'SUCCESS', 'message': ''}, f)
                    with open(f'{td}/{task_id}.json', 'w', encoding='utf-8') as f:
                        json.dump({'markdown': '', 'audio_meta': {}}, f)

                mgr.refresh_from_task_status(batch_id)
                c = self._client()

                r = c.post('/api/delete_batch_task', json={'batch_id': batch_id, 'task_id': 'task-1'})
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertEqual(body['code'], 0)
                self.assertEqual(body['data'].get('deleted_task_id'), 'task-1')
                self.assertEqual(body['data'].get('remaining_task_ids'), ['task-2'])
        finally:
            if original_database_url is None:
                os.environ.pop('DATABASE_URL', None)
            else:
                os.environ['DATABASE_URL'] = original_database_url
            if original_note_output_dir is None:
                os.environ.pop('NOTE_OUTPUT_DIR', None)
            else:
                os.environ['NOTE_OUTPUT_DIR'] = original_note_output_dir
            _reset_app_modules()

    def test_delete_batch_task_route_returns_batch_not_found_for_missing_batch(self):
        original_note_output_dir = os.environ.get('NOTE_OUTPUT_DIR')
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ['NOTE_OUTPUT_DIR'] = td
                c = self._client()

                r = c.post(
                    '/api/delete_batch_task',
                    json={'batch_id': 'missing-batch', 'task_id': 'task-1'},
                )
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertEqual(body['code'], 404)
                self.assertEqual(body['msg'], 'batch not found')
        finally:
            if original_note_output_dir is None:
                os.environ.pop('NOTE_OUTPUT_DIR', None)
            else:
                os.environ['NOTE_OUTPUT_DIR'] = original_note_output_dir
            _reset_app_modules()

    def test_delete_batch_task_route_returns_task_not_found_for_missing_task(self):
        original_note_output_dir = os.environ.get('NOTE_OUTPUT_DIR')
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ['NOTE_OUTPUT_DIR'] = td
                _reset_app_modules()

                from app.services.batch_manager import BatchManager

                mgr = BatchManager()
                batch_id = mgr.create_batch(['https://example.com/course/1'])
                c = self._client()

                r = c.post(
                    '/api/delete_batch_task',
                    json={'batch_id': batch_id, 'task_id': 'missing-task'},
                )
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertEqual(body['code'], 404)
                self.assertEqual(body['msg'], 'task not found')
        finally:
            if original_note_output_dir is None:
                os.environ.pop('NOTE_OUTPUT_DIR', None)
            else:
                os.environ['NOTE_OUTPUT_DIR'] = original_note_output_dir
            _reset_app_modules()


if __name__ == '__main__':
    unittest.main()
