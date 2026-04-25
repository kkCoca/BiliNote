import os
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if 'ffmpeg' not in sys.modules:
    ffmpeg_stub = types.ModuleType('ffmpeg')
    ffmpeg_stub.probe = MagicMock(return_value={})
    ffmpeg_stub.input = MagicMock()
    sys.modules['ffmpeg'] = ffmpeg_stub

import app.transcriber.qwen_asr


class TestQwenASRTranscriber(unittest.TestCase):
    def setUp(self):
        fd, self.audio_path = tempfile.mkstemp(suffix='.mp3')
        with os.fdopen(fd, 'wb') as f:
            f.write(b'audio')

    def tearDown(self):
        if os.path.exists(self.audio_path):
            os.remove(self.audio_path)

    @patch('app.transcriber.qwen_asr._get_qwen_asr_model', return_value='qwen3-asr-flash')
    @patch('app.transcriber.qwen_asr.ffmpeg.probe', return_value={'format': {'duration': '12.5'}})
    @patch('app.transcriber.qwen_asr.requests.post')
    @patch('app.transcriber.qwen_asr.ProviderService.get_provider_by_id')
    def test_transcript_parses_success_response(self, mock_get_provider, mock_post, _mock_probe, _mock_model):
        from app.transcriber.qwen_asr import QwenASRTranscriber

        mock_get_provider.return_value = {
            'api_key': 'sk-test',
            'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        }
        response = MagicMock(status_code=200)
        response.json.return_value = {
            'id': 'chatcmpl-1',
            'model': 'qwen3-asr-flash',
            'choices': [
                {
                    'message': {
                        'content': '你好，世界',
                        'annotations': [{'language': 'zh'}],
                    }
                }
            ],
            'usage': {'total_tokens': 1},
        }
        mock_post.return_value = response

        result = QwenASRTranscriber().transcript(self.audio_path)

        self.assertEqual(result.language, 'zh')
        self.assertEqual(result.full_text, '你好，世界')
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.segments[0].start, 0)
        self.assertEqual(result.segments[0].end, 12.5)
        self.assertEqual(result.segments[0].text, '你好，世界')
        self.assertNotIn('sk-test', str(result.raw))
        self.assertNotIn('base64', str(result.raw))

        url = mock_post.call_args.kwargs['url'] if 'url' in mock_post.call_args.kwargs else mock_post.call_args.args[0]
        self.assertEqual(url, 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions')
        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(payload['model'], 'qwen3-asr-flash')
        self.assertTrue(payload['messages'][0]['content'][0]['input_audio']['data'].startswith('data:audio/mpeg;base64,'))

    @patch('app.transcriber.qwen_asr._get_qwen_asr_model', return_value='qwen-audio-asr')
    @patch('app.transcriber.qwen_asr.requests.post')
    @patch('app.transcriber.qwen_asr.ProviderService.get_provider_by_id')
    def test_configured_qwen_asr_model_is_used(self, mock_get_provider, mock_post, _mock_model):
        from app.transcriber.qwen_asr import QwenASRTranscriber

        mock_get_provider.return_value = {'api_key': 'sk-test', 'base_url': 'https://example.com/v1'}
        response = MagicMock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': 'text'}}]}
        mock_post.return_value = response

        result = QwenASRTranscriber().transcript(self.audio_path)

        self.assertEqual(result.raw['transcriber_model'], 'qwen-audio-asr')
        self.assertEqual(mock_post.call_args.kwargs['json']['model'], 'qwen-audio-asr')

    @patch('app.transcriber.qwen_asr.ProviderService.get_provider_by_id', return_value=None)
    def test_missing_qwen_provider_raises_clear_error(self, _mock_get_provider):
        from app.transcriber.qwen_asr import QwenASRTranscriber

        with self.assertRaisesRegex(Exception, 'Qwen 供应商未配置'):
            QwenASRTranscriber().transcript(self.audio_path)

    @patch('app.transcriber.qwen_asr.ProviderService.get_provider_by_id')
    def test_missing_api_key_raises_clear_error(self, mock_get_provider):
        from app.transcriber.qwen_asr import QwenASRTranscriber

        mock_get_provider.return_value = {'api_key': '', 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1'}

        with self.assertRaisesRegex(Exception, 'Qwen 供应商 API Key 为空'):
            QwenASRTranscriber().transcript(self.audio_path)

    @patch('app.transcriber.qwen_asr._get_qwen_asr_model', return_value='qwen3-asr-flash')
    @patch('app.transcriber.qwen_asr.requests.post')
    @patch('app.transcriber.qwen_asr.ProviderService.get_provider_by_id')
    def test_http_error_includes_status_and_message(self, mock_get_provider, mock_post, _mock_model):
        from app.transcriber.qwen_asr import QwenASRTranscriber

        mock_get_provider.return_value = {'api_key': 'sk-test', 'base_url': 'https://example.com/v1'}
        response = MagicMock(status_code=400, text='bad request')
        response.json.return_value = {'error': {'message': 'invalid audio'}}
        mock_post.return_value = response

        with self.assertRaisesRegex(Exception, 'HTTP 400: invalid audio'):
            QwenASRTranscriber().transcript(self.audio_path)

    @patch('app.transcriber.qwen_asr._get_qwen_asr_model', return_value='qwen3-asr-flash')
    @patch('app.transcriber.qwen_asr.requests.post')
    @patch('app.transcriber.qwen_asr.ProviderService.get_provider_by_id')
    def test_base_url_already_chat_completions_is_preserved(self, mock_get_provider, mock_post, _mock_model):
        from app.transcriber.qwen_asr import QwenASRTranscriber

        endpoint = 'https://example.com/compatible-mode/v1/chat/completions'
        mock_get_provider.return_value = {'api_key': 'sk-test', 'base_url': endpoint}
        response = MagicMock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': 'text'}}]}
        mock_post.return_value = response

        QwenASRTranscriber().transcript(self.audio_path)

        url = mock_post.call_args.kwargs['url'] if 'url' in mock_post.call_args.kwargs else mock_post.call_args.args[0]
        self.assertEqual(url, endpoint)

    @patch('app.transcriber.qwen_asr.MAX_BASE64_AUDIO_SIZE_BYTES', 1)
    @patch('app.transcriber.qwen_asr._get_qwen_asr_model', return_value='qwen3-asr-flash')
    @patch('app.transcriber.qwen_asr.os.remove')
    @patch('app.transcriber.qwen_asr._compress_audio')
    @patch('app.transcriber.qwen_asr.requests.post')
    @patch('app.transcriber.qwen_asr.ProviderService.get_provider_by_id')
    def test_oversized_audio_uses_compressed_file(self, mock_get_provider, mock_post, mock_compress, mock_remove, _mock_model):
        from app.transcriber.qwen_asr import QwenASRTranscriber

        fd, compressed_path = tempfile.mkstemp(suffix='.mp3')
        with os.fdopen(fd, 'wb') as f:
            f.write(b'a')
        mock_compress.return_value = compressed_path
        mock_get_provider.return_value = {'api_key': 'sk-test', 'base_url': 'https://example.com/v1'}
        response = MagicMock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': 'compressed text'}}]}
        mock_post.return_value = response

        result = QwenASRTranscriber().transcript(self.audio_path)

        self.assertEqual(result.full_text, 'compressed text')
        self.assertTrue(result.raw['compressed'])
        mock_compress.assert_called_once()
        mock_remove.assert_called_once_with(compressed_path)

    def test_chunk_duration_env_uses_valid_value_and_falls_back_for_invalid_value(self):
        from app.transcriber.qwen_asr import (
            DEFAULT_QWEN_ASR_CHUNK_DURATION_SECONDS,
            _get_qwen_asr_chunk_duration_seconds,
        )

        with patch.dict(os.environ, {'QWEN_ASR_CHUNK_DURATION_SECONDS': '90'}, clear=False):
            self.assertEqual(_get_qwen_asr_chunk_duration_seconds(), 90)

        with patch.dict(os.environ, {'QWEN_ASR_CHUNK_DURATION_SECONDS': 'invalid'}, clear=False):
            self.assertEqual(
                _get_qwen_asr_chunk_duration_seconds(),
                DEFAULT_QWEN_ASR_CHUNK_DURATION_SECONDS,
            )

        with patch.dict(os.environ, {'QWEN_ASR_CHUNK_DURATION_SECONDS': '-1'}, clear=False):
            self.assertEqual(
                _get_qwen_asr_chunk_duration_seconds(),
                DEFAULT_QWEN_ASR_CHUNK_DURATION_SECONDS,
            )

    @patch.dict(os.environ, {'QWEN_ASR_CHUNK_DURATION_SECONDS': '180'}, clear=False)
    @patch('app.transcriber.qwen_asr._get_qwen_asr_model', return_value='qwen3-asr-flash')
    @patch('app.transcriber.qwen_asr._slice_audio')
    @patch('app.transcriber.qwen_asr.requests.post')
    @patch('app.transcriber.qwen_asr.ProviderService.get_provider_by_id')
    def test_long_audio_is_sliced_and_merged(self, mock_get_provider, mock_post, mock_slice, _mock_model):
        from app.transcriber.qwen_asr import QwenASRTranscriber, _AudioChunk

        chunk_paths = []
        for index in range(3):
            fd, chunk_path = tempfile.mkstemp(suffix=f'-{index}.mp3')
            with os.fdopen(fd, 'wb') as f:
                f.write(f'chunk-{index}'.encode())
            chunk_paths.append(chunk_path)

        self.addCleanup(lambda: [os.remove(path) for path in chunk_paths if os.path.exists(path)])
        mock_slice.return_value = [
            _AudioChunk(path=chunk_paths[0], start=0, duration=180),
            _AudioChunk(path=chunk_paths[1], start=180, duration=180),
            _AudioChunk(path=chunk_paths[2], start=360, duration=20),
        ]
        mock_get_provider.return_value = {'api_key': 'sk-test', 'base_url': 'https://example.com/v1'}

        responses = []
        for text in ['第一段', '第二段', '第三段']:
            response = MagicMock(status_code=200)
            response.json.return_value = {
                'model': 'qwen3-asr-flash',
                'choices': [{'message': {'content': text, 'annotations': [{'language': 'zh'}]}}],
            }
            responses.append(response)
        mock_post.side_effect = responses

        def probe_duration(path):
            if path == self.audio_path:
                return 380
            if path == chunk_paths[0]:
                return 180
            if path == chunk_paths[1]:
                return 180
            if path == chunk_paths[2]:
                return 20
            return 0

        with patch('app.transcriber.qwen_asr._probe_duration', side_effect=probe_duration):
            result = QwenASRTranscriber().transcript(self.audio_path)

        self.assertEqual(mock_post.call_count, 3)
        mock_slice.assert_called_once()
        self.assertEqual(result.language, 'zh')
        self.assertEqual(result.full_text, '第一段\n第二段\n第三段')
        self.assertEqual(len(result.segments), 3)
        self.assertEqual(result.segments[0].start, 0)
        self.assertEqual(result.segments[0].end, 180)
        self.assertEqual(result.segments[1].start, 180)
        self.assertEqual(result.segments[1].end, 360)
        self.assertEqual(result.segments[2].start, 360)
        self.assertEqual(result.segments[2].end, 380)
        self.assertTrue(result.raw['chunked'])
        self.assertEqual(result.raw['chunk_duration_seconds'], 180)
        self.assertEqual(result.raw['transcriber_model'], 'qwen3-asr-flash')
        self.assertEqual(len(result.raw['chunks']), 3)


class TestQwenASRRegistration(unittest.TestCase):
    def test_qwen_asr_registered_in_factory_and_config(self):
        from app.routers.config import AVAILABLE_TRANSCRIBER_TYPES
        from app.transcriber.transcriber_provider import TranscriberType, _transcribers

        self.assertEqual(TranscriberType.QWEN.value, 'qwen')
        self.assertEqual(TranscriberType.QWEN_ASR.value, 'qwen-asr')
        self.assertIn(TranscriberType.QWEN, _transcribers)
        self.assertIn(TranscriberType.QWEN_ASR, _transcribers)
        self.assertIn('qwen', [item['value'] for item in AVAILABLE_TRANSCRIBER_TYPES])
        self.assertNotIn('qwen-asr', [item['value'] for item in AVAILABLE_TRANSCRIBER_TYPES])


class TestQwenASRConfig(unittest.TestCase):
    def test_transcriber_config_persists_qwen_model_and_aliases_old_type(self):
        from app.services.transcriber_config_manager import TranscriberConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, 'transcriber.json')
            manager = TranscriberConfigManager(config_path)

            result = manager.update_config('qwen-asr', qwen_asr_model='qwen-audio-asr')

            self.assertEqual(result['transcriber_type'], 'qwen')
            self.assertEqual(result['qwen_asr_model'], 'qwen-audio-asr')
            self.assertEqual(manager.get_qwen_asr_model(), 'qwen-audio-asr')

    def test_config_route_filters_qwen_asr_models(self):
        from app.routers.config import _extract_model_ids, DEFAULT_QWEN_ASR_MODELS

        response = types.SimpleNamespace(data=[
            types.SimpleNamespace(id='qwen-plus'),
            types.SimpleNamespace(id='qwen3-asr-flash'),
            types.SimpleNamespace(id='qwen-audio-asr'),
        ])

        self.assertEqual(_extract_model_ids(response), ['qwen3-asr-flash', 'qwen-audio-asr'])
        self.assertIn('qwen3-asr-flash', DEFAULT_QWEN_ASR_MODELS)


if __name__ == '__main__':
    unittest.main()
