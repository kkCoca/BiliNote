import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def _service_url() -> str:
    return os.getenv('OPENCLI_SERVICE_URL', 'http://opencli:19826').rstrip('/')


def get_bilibili_space_videos(uid: str, *, max_pages: int = 10) -> list[dict[str, Any]]:
    if not uid or not str(uid).isdigit():
        raise ValueError('uid must be numeric')

    max_pages = max(1, min(50, int(max_pages)))
    url = f"{_service_url()}/bilibili/space_videos?uid={uid}&max_pages={max_pages}"

    try:
        # Space list extraction uses browser automation and may take longer.
        timeout_s = int(os.getenv('OPENCLI_SPACE_TIMEOUT_SECS', '600'))
        with urlopen(url, timeout=timeout_s) as resp:
            body = resp.read().decode('utf-8')
    except HTTPError as e:
        raw = e.read().decode('utf-8', errors='ignore') if hasattr(e, 'read') else ''
        raise RuntimeError(f'opencli service http error: {e.code} {raw}'.strip())
    except URLError as e:
        raise RuntimeError(f'opencli service unreachable: {e}')

    try:
        data = json.loads(body)
    except Exception as e:
        raise RuntimeError(f'opencli service returned invalid json: {e}')

    if isinstance(data, dict) and data.get('error'):
        raise RuntimeError(str(data.get('error')))

    if not isinstance(data, list):
        raise RuntimeError('opencli service returned unexpected payload')

    return [x for x in data if isinstance(x, dict)]
