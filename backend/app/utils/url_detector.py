"""URL detector for single vs multi-video pages.

Primary use-case:

1. Single video URL -> returns one entry
2. Collection/playlist/space URL -> returns entries (multi)

For Bilibili creator space pages, we call the OpenCLI sidecar to reuse host Chrome
login session, avoiding 412 blocks from direct scraping.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any, Optional

import yt_dlp

from app.utils.logger import get_logger
from app.utils.opencli_service import get_bilibili_space_videos


logger = get_logger(__name__)


@contextmanager
def _without_proxy_env():
    keys = [
        'HTTP_PROXY',
        'HTTPS_PROXY',
        'ALL_PROXY',
        'http_proxy',
        'https_proxy',
        'all_proxy',
        'NO_PROXY',
        'no_proxy',
    ]
    saved = {k: os.environ.get(k) for k in keys if k in os.environ}
    try:
        for k in keys:
            os.environ.pop(k, None)
        yield
    finally:
        for k in keys:
            os.environ.pop(k, None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def _bilibili_space_uid(url: str) -> Optional[str]:
    if not url:
        return None
    m = re.search(r'space\.bilibili\.com/(\d+)', url)
    return m.group(1) if m else None


class UrlDetector:
    @staticmethod
    def detect(url: str) -> dict[str, Any]:
        # Special-case bilibili space pages: use opencli sidecar.
        uid = _bilibili_space_uid(url)
        if uid:
            # Bilibili space list: fetch multiple pages via OpenCLI sidecar.
            # Default is large enough for most creators; tune via env if needed.
            try:
                # Keep default conservative. Listing 10 pages can take several minutes.
                max_pages = int(os.getenv('BILIBILI_SPACE_DETECT_MAX_PAGES', '3'))
            except Exception:
                max_pages = 3
            items = get_bilibili_space_videos(uid, max_pages=max_pages)
            entries = [
                {
                    'video_id': it.get('video_id', ''),
                    'title': it.get('title', '未知视频'),
                    'duration': int(it.get('duration') or 0),
                    'thumbnail': it.get('thumbnail', ''),
                    'video_url': it.get('video_url', ''),
                }
                for it in items
                if isinstance(it, dict) and it.get('video_url')
            ]

            url_type = 'multi' if len(entries) > 1 else 'single'
            return {'type': url_type, 'entries': entries}

        opts: dict[str, Any] = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
        }

        if 'bilibili.com' in (url or '').lower():
            opts['http_headers'] = {
                'User-Agent': (
                    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
                ),
                'Referer': 'https://www.bilibili.com/',
            }

        try:
            with _without_proxy_env():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
        except Exception as e:
            logger.error(f'URL detect failed: {e}')
            raise Exception(f'URL 探测失败: {e}')

        if not info:
            raise Exception('无法获取 URL 信息')

        entries: list[dict[str, Any]] = []

        if info.get('entries'):
            for e in info['entries']:
                entry = UrlDetector._extract_entry_info(e, url)
                if entry:
                    entries.append(entry)
        elif info.get('id'):
            vid = info.get('id', '')
            entries.append(
                {
                    'video_id': vid,
                    'title': info.get('title', '未知视频'),
                    'duration': info.get('duration', 0) or 0,
                    'thumbnail': info.get('thumbnail', ''),
                    'video_url': UrlDetector._build_video_url(vid, url),
                }
            )

        url_type = 'multi' if len(entries) > 1 else 'single'
        return {'type': url_type, 'entries': entries}

    @staticmethod
    def _extract_entry_info(entry: dict[str, Any], parent_url: str) -> Optional[dict[str, Any]]:
        if not entry:
            return None
        vid = entry.get('id')
        if not vid:
            return None
        return {
            'video_id': vid,
            'title': entry.get('title', '未知视频'),
            'duration': entry.get('duration', 0) or 0,
            'thumbnail': entry.get('thumbnail', ''),
            'video_url': UrlDetector._build_video_url(vid, parent_url),
        }

    @staticmethod
    def _build_video_url(video_id: str, parent_url: str) -> str:
        if not video_id:
            return ''
        u = (parent_url or '').lower()
        if 'bilibili.com' in u or str(video_id).startswith('BV'):
            return f'https://www.bilibili.com/video/{video_id}/'
        if 'youtube.com' in u or 'youtu.be' in u:
            return f'https://www.youtube.com/watch?v={video_id}'
        return str(video_id)
