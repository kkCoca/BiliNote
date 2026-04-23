#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _run_opencli(args: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
    p = subprocess.run(
        ['opencli', *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return p.returncode, p.stdout or '', p.stderr or ''


def _require_extension_connected() -> None:
    code, out, err = _run_opencli(['doctor'], timeout=20)
    merged = (out + '\n' + err).strip()
    if code != 0:
        raise RuntimeError(f'opencli doctor failed: {merged}')
    if 'Extension: connected' not in merged:
        raise RuntimeError(
            'OpenCLI extension is not connected. Ensure host Chrome is open, '
            'OpenCLI Browser Bridge extension is installed/enabled, and it can reach localhost:19825.'
        )


# Short TTL cache to reduce repeated scraping and avoid triggering rate limits.
_SPACE_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_SPACE_CACHE_TTL_SECS = 120


def _extract_json_line(text: str) -> str:
    # opencli sometimes prints extra lines; prefer the last JSON-looking line.
    for line in reversed([l.strip() for l in (text or '').splitlines() if l.strip()]):
        if line.startswith('[') or line.startswith('{') or line.startswith('"'):
            return line
    return (text or '').strip()


def _extract_json_blob(text: str) -> str:
    """Best-effort extract a full JSON object/array from mixed output."""
    s = (text or '').strip()
    if not s:
        return ''

    obj_start = s.find('{')
    obj_end = s.rfind('}')
    if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
        return s[obj_start : obj_end + 1]

    arr_start = s.find('[')
    arr_end = s.rfind(']')
    if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
        return s[arr_start : arr_end + 1]

    return ''


def _eval_js(js_expr: str, *, timeout: int = 30, retries: int = 3) -> str:
    last_err = ''
    for _ in range(max(1, retries)):
        code, out, err = _run_opencli(['browser', 'eval', js_expr], timeout=timeout)
        if code == 0:
            line = _extract_json_line(out)
            if line:
                return line
        last_err = (out + '\n' + err).strip()
        time.sleep(0.5)
    raise RuntimeError(f'opencli browser eval failed: {last_err}')


def _wait_rendered(*, timeout_s: int = 15) -> None:
    start = time.time()
    while True:
        try:
            out = _eval_js('document.documentElement.outerHTML.length', timeout=10, retries=1)
            m = re.search(r'(\d+)', out)
            if m and int(m.group(1)) > 10000:
                return
        except Exception:
            pass
        if time.time() - start > timeout_s:
            raise RuntimeError('page did not render in time (outerHTML too small)')
        time.sleep(0.5)


def _wait_video_items(*, timeout_s: int = 25) -> None:
    """Wait until the space upload list has actually rendered."""
    start = time.time()
    js = (
        "(() => ("
        "document.querySelectorAll('.upload-video-card, .bili-video-card, .bili-video-card__wrap').length + "
        "document.querySelectorAll(\"a[href*='/video/']\").length"
        "))()"
    )
    while True:
        try:
            out = _eval_js(js, timeout=10, retries=1)
            m = re.search(r'(\d+)', str(out))
            if m and int(m.group(1)) > 0:
                return
        except Exception:
            pass
        if time.time() - start > timeout_s:
            raise RuntimeError('video list not found in time (maybe blocked / not loaded)')
        time.sleep(0.5)


def _space_url(uid: str) -> str:
    return f'https://space.bilibili.com/{uid}/upload/video'


def _get_space_videos(uid: str, *, max_pages: int = 10) -> list[dict[str, Any]]:
    now = time.time()
    cached = _SPACE_CACHE.get(uid)
    if cached and now - cached[0] <= _SPACE_CACHE_TTL_SECS and cached[1]:
        return cached[1]

    # Always require extension connection; public API fallback is too unreliable (-799 rate limit).
    _require_extension_connected()

    # Opening/selection can be flaky; retry the whole open+wait sequence.
    last_open_err = ''
    for _ in range(3):
        # Prefer `browser open` over tab create+select; it is more reliable.
        code, out, err = _run_opencli(['browser', 'open', _space_url(uid)], timeout=45)
        if code != 0:
            last_open_err = (out + '\n' + err).strip()
            time.sleep(1)
            continue

        try:
            # Ensure we are not stuck on about:blank.
            href = _eval_js('location.href', timeout=10, retries=2)
            if 'about:blank' in str(href):
                last_open_err = 'tab selected but still about:blank'
                _run_opencli(['browser', 'close'], timeout=10)
                time.sleep(1)
                continue

            _wait_rendered(timeout_s=45)

            # The list can be lazy-loaded; scroll a bit and wait for BV links.
            for attempt in range(4):
                try:
                    _wait_video_items(timeout_s=35)
                    break
                except Exception as e:
                    last_open_err = str(e)
                    _eval_js('window.scrollTo(0, document.body.scrollHeight)', timeout=10, retries=1)
                    time.sleep(2)
            else:
                raise RuntimeError(last_open_err or 'BV links not found')
            break
        except Exception as e:
            last_open_err = str(e)
            _run_opencli(['browser', 'close'], timeout=10)
            time.sleep(1)
    else:
        raise RuntimeError(f'failed to open/render space page: {last_open_err}')

    seen: set[str] = set()
    all_items: list[dict[str, Any]] = []

    js_extract = r'''(() => {
  const hasWord = (s) => /[A-Za-z\u4e00-\u9fff]/.test(s || '');

  const normalizeThumb = (src) => {
    if (!src) return '';
    if (src.startsWith('//')) return 'https:' + src;
    return src;
  };

  const parseDurationSeconds = (s) => {
    const m = (s || '').match(/\b(\d{1,2}:\d{2}(?::\d{2})?)\b/);
    if (!m) return 0;
    const parts = m[1].split(':').map(x => parseInt(x, 10));
    if (parts.some(x => Number.isNaN(x))) return 0;
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return 0;
  };

  const bestTitleFromCard = (card) => {
    if (!card) return '';
    const cand = [];

    // Prefer explicit titles from elements carrying title attr.
    for (const el of card.querySelectorAll('[title]')) {
      const t = (el.getAttribute('title') || '').trim();
      if (t) cand.push(t);
    }

    // Fallback to text from likely title elements.
    for (const el of card.querySelectorAll('[class*="title"], h3')) {
      const t = (el.textContent || '').trim();
      if (t) cand.push(t);
    }

    // Rank: must contain words; pick the longest (real titles tend to be longest).
    const scored = cand
      .map(t => t.replace(/\s+/g, ' ').trim())
      .filter(t => t && hasWord(t))
      .sort((a, b) => b.length - a.length);
    return scored[0] || '';
  };

  const out = [];
  const seen = new Set();

  // The space upload page uses card components; iterate cards first.
  const cards = Array.from(document.querySelectorAll('.upload-video-card, .bili-video-card, .bili-video-card__wrap'));

  for (const card of cards) {
    const a = card.querySelector("a[href*='/video/']");
    if (!a) continue;
    const href = a.href || '';
    const m = href.match(/BV[A-Za-z0-9]+/);
    const bvid = m ? m[0] : '';
    if (!bvid || seen.has(bvid)) continue;
    seen.add(bvid);

    const title = bestTitleFromCard(card) || bvid;

    const img = card.querySelector('img');
    const thumb = normalizeThumb(img?.src || img?.getAttribute('data-src') || img?.getAttribute('src') || '');

    const duration = parseDurationSeconds((card.querySelector('.bili-video-card__cover')?.textContent || card.textContent || '').trim());

    out.push({
      video_id: bvid,
      title,
      duration,
      thumbnail: thumb,
      video_url: 'https://www.bilibili.com/video/' + bvid + '/',
    });
  }

  // Fallback: if cards didn't match, scan links.
  if (out.length === 0) {
    const links = Array.from(document.querySelectorAll("a[href*='/video/']"));
    for (const a of links) {
      const href = a.href || '';
      const m = href.match(/BV[A-Za-z0-9]+/);
      const bvid = m ? m[0] : '';
      if (!bvid || seen.has(bvid)) continue;
      seen.add(bvid);
      const title = ((a.getAttribute('title') || a.textContent || '') + '').trim() || bvid;
      out.push({ video_id: bvid, title, duration: 0, thumbnail: '', video_url: 'https://www.bilibili.com/video/' + bvid + '/' });
    }
  }

  return JSON.stringify(out);
})()'''


    js_click_next = r'''(() => {
  const btns = Array.from(document.querySelectorAll('button'));
  const next = btns.find(b => (b.textContent || '').includes('下一页'));
  if (!next) return 'not_found';
  if (next.disabled) return 'disabled';
  next.click();
  return 'clicked';
})()'''

    try:
        for page in range(1, max_pages + 1):
            raw = _eval_js(js_extract, timeout=30, retries=3)
            try:
                items = json.loads(raw)
            except Exception:
                items = []

            # If nothing extracted, scroll and wait a bit then retry once.
            if not items:
                _eval_js('window.scrollTo(0, document.body.scrollHeight)', timeout=10, retries=1)
                time.sleep(2)
                raw = _eval_js(js_extract, timeout=30, retries=2)
                try:
                    items = json.loads(raw)
                except Exception:
                    items = []

            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    vid = str(it.get('video_id') or '')
                    if not vid or vid in seen:
                        continue
                    seen.add(vid)
                    all_items.append(it)

            # Try go next.
            if page >= max_pages:
                break
            nxt = _eval_js(js_click_next, timeout=20, retries=2)
            if 'clicked' not in str(nxt):
                break
            time.sleep(3)
            _wait_rendered(timeout_s=20)
            _wait_video_items(timeout_s=20)
    finally:
        # Best-effort cleanup.
        _run_opencli(['browser', 'close'], timeout=10)

    if all_items:
        _SPACE_CACHE[uid] = (now, all_items)
    return all_items


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Keep logs minimal.
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == '/healthz':
            return _json_response(self, 200, {'ok': True})

        if parsed.path == '/bilibili/space_videos':
            qs = parse_qs(parsed.query)
            uid = (qs.get('uid') or [''])[0].strip()
            max_pages_raw = (qs.get('max_pages') or ['10'])[0]
            try:
                max_pages = max(1, min(50, int(max_pages_raw)))
            except Exception:
                max_pages = 10

            if not uid or not uid.isdigit():
                return _json_response(self, 400, {'error': 'uid is required and must be numeric'})

            try:
                items = _get_space_videos(uid, max_pages=max_pages)
                return _json_response(self, 200, items)
            except Exception as e:
                msg = str(e)
                # Map connectivity issues to 503.
                if 'Extension' in msg or 'doctor' in msg:
                    return _json_response(self, 503, {'error': msg})
                return _json_response(self, 502, {'error': msg})

        return _json_response(self, 404, {'error': 'not found'})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=19826)
    args = ap.parse_args()

    server = HTTPServer((args.host, args.port), Handler)
    server.serve_forever()


if __name__ == '__main__':
    main()
