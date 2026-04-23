import pathlib
import sys
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


if __name__ == '__main__':
    unittest.main()
