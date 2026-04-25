import base64
import math
import mimetypes
import os
import tempfile
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import ffmpeg
import requests

from app.decorators.timeit import timeit
from app.models.transcriber_model import TranscriptResult, TranscriptSegment
from app.services.provider import ProviderService
from app.transcriber.base import Transcriber

DEFAULT_QWEN_ASR_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_ASR_MODEL = "qwen3-asr-flash"
DEFAULT_QWEN_ASR_CHUNK_DURATION_SECONDS = 180
MAX_BASE64_AUDIO_SIZE_MB = 18
MAX_BASE64_AUDIO_SIZE_BYTES = MAX_BASE64_AUDIO_SIZE_MB * 1024 * 1024


@dataclass
class _AudioChunk:
    path: str
    start: float
    duration: float


def _get_qwen_asr_model() -> str:
    try:
        from app.services.transcriber_config_manager import TranscriberConfigManager

        configured_model = TranscriberConfigManager().get_qwen_asr_model().strip()
        if configured_model:
            return configured_model
    except Exception:
        pass
    return os.getenv("QWEN_ASR_MODEL") or DEFAULT_QWEN_ASR_MODEL


def _get_qwen_asr_timeout() -> int:
    return int(os.getenv("QWEN_ASR_TIMEOUT_SECONDS", "600"))


def _get_qwen_asr_compress_bitrate() -> str:
    return os.getenv("QWEN_ASR_COMPRESS_BITRATE", "64k")


def _get_qwen_asr_chunk_duration_seconds() -> float:
    try:
        value = float(os.getenv("QWEN_ASR_CHUNK_DURATION_SECONDS", str(DEFAULT_QWEN_ASR_CHUNK_DURATION_SECONDS)))
        if value > 0:
            return value
    except ValueError:
        pass
    return DEFAULT_QWEN_ASR_CHUNK_DURATION_SECONDS


def _normalize_chat_completions_url(base_url: str | None) -> str:
    url = (base_url or DEFAULT_QWEN_ASR_BASE_URL).strip().rstrip("/")
    if not url:
        url = DEFAULT_QWEN_ASR_BASE_URL
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def _audio_data_url(file_path: str) -> str:
    mime_type = mimetypes.guess_type(file_path)[0] or "audio/mpeg"
    with open(file_path, "rb") as audio_file:
        encoded = base64.b64encode(audio_file.read()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _compress_audio(input_path: str, target_bitrate: str) -> str:
    output_fd, output_path = tempfile.mkstemp(suffix=".mp3")
    os.close(output_fd)
    ffmpeg.input(input_path).output(output_path, audio_bitrate=target_bitrate).run(
        quiet=True,
        overwrite_output=True,
    )
    return output_path


def _probe_duration(file_path: str) -> float:
    try:
        info = ffmpeg.probe(file_path)
        return float(info.get("format", {}).get("duration") or 0)
    except Exception:
        return 0.0


def _slice_audio(file_path: str, total_duration: float, chunk_duration: float, output_dir: str) -> list[_AudioChunk]:
    chunk_count = math.ceil(total_duration / chunk_duration)
    chunks = []
    for index in range(chunk_count):
        start = index * chunk_duration
        duration = min(chunk_duration, total_duration - start)
        chunk_path = os.path.join(output_dir, f"qwen_asr_chunk_{index + 1}.mp3")
        ffmpeg.input(file_path, ss=start, t=duration).output(
            chunk_path,
            format="mp3",
            audio_bitrate=_get_qwen_asr_compress_bitrate(),
        ).run(quiet=True, overwrite_output=True)
        chunks.append(_AudioChunk(path=chunk_path, start=start, duration=duration))
    return chunks


def _extract_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    texts.append(text.strip())
        return "\n".join(text for text in texts if text).strip()
    return ""


def _extract_language(message: dict[str, Any]) -> str | None:
    annotations = message.get("annotations") or []
    if not isinstance(annotations, list):
        return None
    for annotation in annotations:
        if isinstance(annotation, dict) and annotation.get("language"):
            return str(annotation["language"])
    return None


def _safe_raw_response(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data.get("id"),
        "model": data.get("model"),
        "object": data.get("object"),
        "created": data.get("created"),
        "usage": data.get("usage"),
    }


def _get_qwen_provider() -> dict[str, Any] | None:
    return ProviderService.get_provider_by_id("qwen")


class QwenASRTranscriber(Transcriber, ABC):
    @timeit
    def transcript(self, file_path: str) -> TranscriptResult:
        provider = _get_qwen_provider()
        if not provider:
            raise Exception("Qwen 供应商未配置，请先在模型供应商中配置 Qwen。")

        api_key = (provider.get("api_key") or "").strip()
        if not api_key:
            raise Exception("Qwen 供应商 API Key 为空，请先在模型供应商中配置 Qwen API Key。")

        duration = _probe_duration(file_path)
        chunk_duration = _get_qwen_asr_chunk_duration_seconds()
        if duration <= 0 or duration <= chunk_duration:
            return self._transcript_single_audio(file_path, file_path, provider, api_key)

        with tempfile.TemporaryDirectory() as temp_dir:
            chunks = _slice_audio(file_path, duration, chunk_duration, temp_dir)
            results = [
                self._transcript_single_audio(chunk.path, file_path, provider, api_key)
                for chunk in chunks
            ]

        full_text = "\n".join(result.full_text for result in results if result.full_text).strip()
        language = next((result.language for result in results if result.language), None)
        segments = []
        for chunk, result in zip(chunks, results):
            for segment in result.segments:
                segments.append(TranscriptSegment(
                    start=round(chunk.start + segment.start, 3),
                    end=round(chunk.start + segment.end, 3),
                    text=segment.text,
                ))

        first_raw = results[0].raw or {}
        return TranscriptResult(
            language=language,
            full_text=full_text,
            segments=segments,
            raw={
                "provider": "qwen",
                "endpoint_host": first_raw.get("endpoint_host"),
                "transcriber_model": first_raw.get("transcriber_model"),
                "audio_file": Path(file_path).name,
                "chunked": True,
                "chunk_duration_seconds": chunk_duration,
                "total_duration_seconds": duration,
                "chunks": [
                    {
                        "index": index + 1,
                        "start": chunk.start,
                        "duration": chunk.duration,
                        "raw": result.raw,
                    }
                    for index, (chunk, result) in enumerate(zip(chunks, results))
                ],
            },
        )

    def _transcript_single_audio(
        self,
        file_path: str,
        original_file_path: str,
        provider: dict[str, Any],
        api_key: str,
    ) -> TranscriptResult:
        tmp_compressed: str | None = None
        audio_path = file_path
        try:
            file_size = os.path.getsize(audio_path)
            if file_size > MAX_BASE64_AUDIO_SIZE_BYTES:
                tmp_compressed = _compress_audio(audio_path, _get_qwen_asr_compress_bitrate())
                audio_path = tmp_compressed
                file_size = os.path.getsize(audio_path)

            if file_size > MAX_BASE64_AUDIO_SIZE_BYTES:
                size_mb = round(file_size / (1024 * 1024), 2)
                raise Exception(f"音频文件压缩后仍超过 {MAX_BASE64_AUDIO_SIZE_MB}MB（当前 {size_mb}MB），无法提交 Qwen ASR。")

            data_url = _audio_data_url(audio_path)
            model = _get_qwen_asr_model()
            endpoint = _normalize_chat_completions_url(provider.get("base_url"))
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {"data": data_url},
                                }
                            ],
                        }
                    ],
                    "stream": False,
                    "asr_options": {"enable_itn": True},
                },
                timeout=_get_qwen_asr_timeout(),
            )
            try:
                data = response.json()
            except ValueError as exc:
                raise Exception(f"Qwen ASR 返回非 JSON 响应，HTTP {response.status_code}") from exc

            if response.status_code >= 400:
                error = data.get("error") if isinstance(data, dict) else None
                message = error.get("message") if isinstance(error, dict) else response.text
                raise Exception(f"Qwen ASR 请求失败，HTTP {response.status_code}: {message}")

            choices = data.get("choices") if isinstance(data, dict) else None
            if not choices:
                raise Exception("Qwen ASR 响应缺少 choices。")

            message = choices[0].get("message") or {}
            full_text = _extract_text(message)
            if not full_text:
                raise Exception("Qwen ASR 响应未返回转写文本。")

            duration = _probe_duration(audio_path)
            return TranscriptResult(
                language=_extract_language(message),
                full_text=full_text,
                segments=[TranscriptSegment(start=0, end=duration, text=full_text)],
                raw={
                    **_safe_raw_response(data),
                    "provider": "qwen",
                    "endpoint_host": urlparse(endpoint).netloc,
                    "transcriber_model": model,
                    "audio_file": Path(original_file_path).name,
                    "compressed": tmp_compressed is not None,
                },
            )
        finally:
            if tmp_compressed:
                try:
                    os.remove(tmp_compressed)
                except Exception:
                    pass
