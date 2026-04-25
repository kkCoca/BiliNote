import os
import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ensure we import the backend `app` package, not an unrelated module.
def _reset_app_modules() -> None:
    for k in list(sys.modules.keys()):
        if k == 'app' or k.startswith('app.'):
            sys.modules.pop(k, None)


class TestUrlDetector(unittest.TestCase):
    def test_space_url_uses_opencli_service(self):
        _reset_app_modules()
        import importlib

        url_detector = importlib.import_module('app.utils.url_detector')
        UrlDetector = url_detector.UrlDetector

        with patch.object(url_detector, 'get_bilibili_space_videos') as mock_get:
            mock_get.return_value = [
                {
                    'video_id': 'BV1xx411c7mD',
                    'title': 't1',
                    'duration': 0,
                    'thumbnail': '',
                    'video_url': 'https://www.bilibili.com/video/BV1xx411c7mD/',
                },
                {
                    'video_id': 'BV2xx411c7mD',
                    'title': 't2',
                    'duration': 0,
                    'thumbnail': '',
                    'video_url': 'https://www.bilibili.com/video/BV2xx411c7mD/',
                },
            ]
            res = UrlDetector.detect('https://space.bilibili.com/312017759/upload/video')
        self.assertEqual(res['type'], 'multi')
        self.assertEqual(len(res['entries']), 2)
        self.assertTrue(res['entries'][0]['video_url'].startswith('https://www.bilibili.com/video/'))

    @patch('yt_dlp.YoutubeDL')
    def test_bilibili_sets_headers_for_ytdlp(self, mock_ydl_class):
        _reset_app_modules()
        import importlib

        url_detector = importlib.import_module('app.utils.url_detector')
        UrlDetector = url_detector.UrlDetector

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {'id': 'BV123', 'title': 'x', 'duration': 1, 'thumbnail': ''}

        with patch.object(url_detector, '_apply_bilibili_ydl_options', wraps=url_detector._apply_bilibili_ydl_options) as mock_apply:
            UrlDetector.detect('https://www.bilibili.com/video/BV123')

        opts = mock_ydl_class.call_args[0][0]
        mock_apply.assert_called_once_with(opts)
        self.assertIn('http_headers', opts)
        self.assertEqual(opts['http_headers']['Origin'], 'https://www.bilibili.com')
        self.assertEqual(opts['http_headers']['Accept'], 'application/json, text/plain, */*')
        self.assertIn('User-Agent', opts['http_headers'])
        self.assertIn('Referer', opts['http_headers'])

    @patch('yt_dlp.YoutubeDL')
    def test_without_proxy_env_unsets_then_restores(self, mock_ydl_class):
        _reset_app_modules()
        from app.utils.url_detector import UrlDetector

        os.environ['HTTP_PROXY'] = 'http://127.0.0.1:9999'
        os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:9999'

        def _assert_no_proxy(*_a, **_kw):
            self.assertNotIn('HTTP_PROXY', os.environ)
            self.assertNotIn('HTTPS_PROXY', os.environ)
            return {'id': 'BV123', 'title': 'x', 'duration': 1, 'thumbnail': ''}

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = _assert_no_proxy
        mock_ydl_class.return_value = mock_ydl

        UrlDetector.detect('https://www.bilibili.com/video/BV123')

        self.assertEqual(os.environ.get('HTTP_PROXY'), 'http://127.0.0.1:9999')
        self.assertEqual(os.environ.get('HTTPS_PROXY'), 'http://127.0.0.1:9999')


if __name__ == '__main__':
    unittest.main()
