# OpenCLI Sidecar For Bilibili Space Lists Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** In docker-compose, fetch Bilibili creator space video lists via host Chrome login session using an OpenCLI sidecar container, and use that list in backend `/api/detect_url` to unlock batch generation.

**Architecture:** Add an `opencli` sidecar service that exposes the OpenCLI daemon to the host (for the Chrome extension) and exposes a small HTTP API to the backend. Backend detects Bilibili space URLs and calls the sidecar to return `entries`.

**Tech Stack:** Docker Compose, Node.js (OpenCLI), Python 3.11 (FastAPI), existing backend URL detector and tests.

---

### Task 1: Add OpenCLI Sidecar Service To docker-compose

**Files:**
- Create: `opencli/Dockerfile`
- Create: `opencli/server.py`
- Create: `opencli/start.sh`
- Modify: `docker-compose.yml`

**Step 1: Write the failing expectation (manual check)**

This is infra-only; we will validate by running containers.

**Step 2: Implement minimal sidecar container**

Create `opencli/Dockerfile` that:

1. Uses Node 20 base.
2. Installs `@jackwener/opencli` globally.
3. Installs Python (or use a Python base and install Node; choose minimal image size and simplicity).
4. Copies `server.py` and `start.sh`.
5. Exposes ports `19825` (daemon) and `19826` (HTTP API).

Create `opencli/start.sh` that:

1. Starts `opencli daemon start` (or runs daemon in foreground if supported).
2. Starts the HTTP server.
3. Forwards signals and exits cleanly.

**Step 3: Modify docker-compose**

Add service:

1. `opencli` built from `./opencli`.
2. `ports` includes `127.0.0.1:19825:19825`.
3. `backend` gets env `OPENCLI_SERVICE_URL=http://opencli:19826`.
4. `backend` depends_on `opencli`.

**Step 4: Run docker-compose to verify wiring**

Run: `docker-compose up -d --build opencli`

Expected:

1. Container is running.
2. Host port `127.0.0.1:19825` is bound.
3. `curl http://localhost:19826/healthz` returns 200 (if we publish 19826 for debug; otherwise `docker exec` curl inside network).

**Step 5: Commit (ask user before committing)**

We will not commit without explicit user request.

---

### Task 2: Implement OpenCLI Sidecar HTTP API For Space Video List

**Files:**
- Modify: `opencli/server.py`
- Test: (optional local smoke tests)

**Step 1: Implement `/healthz`**

`server.py` should listen on `0.0.0.0:19826` and return `OK`.

**Step 2: Implement `/bilibili/space_videos`**

Pseudo-code:

```python
def run_opencli(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    # subprocess.run([...], capture_output=True, text=True)

def ensure_connected():
    # opencli doctor; require 'Extension: connected'

def wait_rendered():
    # loop 1..15: eval outerHTML.length; accept >10000

def extract_page():
    js = r"""(() => {
      const links = Array.from(document.querySelectorAll('a[href*="BV"]'));
      const out = [];
      const seen = new Set();
      for (const a of links) {
        const href = a.href || '';
        const m = href.match(/BV[A-Za-z0-9]+/);
        const bvid = m ? m[0] : '';
        if (!bvid || seen.has(bvid)) continue;
        seen.add(bvid);
        const title = (a.getAttribute('title') || a.textContent || '').trim();
        out.push({ video_id: bvid, title, duration: 0, thumbnail: '', video_url: 'https://www.bilibili.com/video/' + bvid + '/' });
      }
      return JSON.stringify(out);
    })()"""
    # opencli browser eval js; parse JSON

def click_next() -> bool:
    js = r"""(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const next = btns.find(b => (b.textContent || '').includes('下一页'));
      if (!next) return 'not_found';
      if (next.disabled) return 'disabled';
      next.click();
      return 'clicked';
    })()"""
    # return clicked?
```

Behavior:

1. `ensure_connected()`.
2. `opencli browser tab new https://space.bilibili.com/{uid}/upload/video`.
3. `wait_rendered()`.
4. Loop pages up to `max_pages`:
   - `extract_page()` append unique `video_id`.
   - `click_next()` and `sleep 3` if clicked; else break.
5. `opencli browser close` best-effort.

**Step 3: Add retries**

For `eval` operations, retry up to 3 times if output is empty / JSON parse fails.

**Step 4: Manual verification**

1. Open host Chrome.
2. Ensure OpenCLI extension is installed and logged into bilibili.com.
3. Run: `curl 'http://localhost:19826/bilibili/space_videos?uid=312017759&max_pages=2'` (if port is published; otherwise from backend container).

Expected: JSON list of BV items.

---

### Task 3: Backend Client For Sidecar + Integrate Into `/api/detect_url`

**Files:**
- Create: `backend/app/utils/opencli_service.py`
- Modify: `backend/app/utils/url_detector.py`
- Test: `backend/tests/test_url_detector.py`

**Step 1: Write failing tests**

Add tests that:

1. When URL is `https://space.bilibili.com/312017759/upload/video`, detector calls OpenCLI service client and returns `type=multi` with entries.
2. When service is unreachable, detector returns an error message that instructs to start opencli service.

Use `unittest.mock.patch` to mock HTTP calls.

Example (sketch):

```python
@patch('app.utils.opencli_service.urlopen')
def test_space_url_uses_opencli(mock_urlopen):
    mock_urlopen.return_value.__enter__.return_value.read.return_value = b'[{"video_id":"BV1xx","title":"t","duration":0,"thumbnail":"","video_url":"https://www.bilibili.com/video/BV1xx/"}]'
    res = UrlDetector.detect('https://space.bilibili.com/312017759/upload/video')
    assert res['type'] == 'single' or res['type'] == 'multi'
    assert res['entries'][0]['video_url'].startswith('https://www.bilibili.com/video/')
```

**Step 2: Run tests to verify failure**

Run: `python -m unittest backend/tests/test_url_detector.py`

Expected: FAIL because `opencli_service` does not exist or detector doesn't call it.

**Step 3: Implement `opencli_service.py`**

Use stdlib `urllib.request` (avoid new deps). Provide:

1. `get_space_videos(uid: str, max_pages: int = 10) -> list[dict]`
2. Read `OPENCLI_SERVICE_URL` env default `http://opencli:19826`.
3. Raise exceptions with clear messages on non-200 or invalid JSON.

**Step 4: Modify `UrlDetector.detect`**

1. Add a Bilibili-space URL matcher.
2. Extract `uid` from URL.
3. Call `opencli_service.get_space_videos(uid, ...)`.
4. Return entries in the existing schema.
5. Keep existing yt-dlp logic for other URLs.

**Step 5: Run tests to verify pass**

Run: `python -m unittest backend/tests/test_url_detector.py`

Expected: PASS.

---

### Task 4: Backend Route Smoke Test With Sidecar Mock

**Files:**
- Test: `backend/tests/test_batch_routes.py`

**Step 1: Write failing test**

Patch `UrlDetector.detect` or `opencli_service.get_space_videos` so `/api/detect_url` returns multi entries for a space URL.

**Step 2: Run the test to verify failure**

Run: `python -m unittest backend/tests/test_batch_routes.py`

**Step 3: Adjust route / response if needed**

Keep response format unchanged.

**Step 4: Run the test to verify pass**

Run: `python -m unittest backend/tests/test_batch_routes.py`

Expected: PASS.

---

### Task 5: Document Ops Steps (Host Chrome + Port Conflicts)

**Files:**
- Modify: `DEPLOYMENT_GUIDE.md` (or add a short section in existing docs)

**Step 1: Add a short runbook**

Include:

1. Install OpenCLI extension into host Chrome.
2. Make sure the host is logged into bilibili.com.
3. Start docker-compose.
4. If port `19825` is already in use (host opencli daemon), stop it.
5. Verify `opencli doctor` (from inside sidecar container) shows extension connected.

---

## Execution

Plan complete and saved to `docs/plans/2026-04-21-opencli-bilibili-list-implementation.md`.

Two execution options:

1. Subagent-Driven (this session)
2. Parallel Session (separate)

Which approach?
