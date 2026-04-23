## Goal

Make BiliNote able to reliably fetch Bilibili creator space video lists (e.g. `https://space.bilibili.com/<uid>/upload/video`) without requiring the user to provide cookies, by reusing the login session in the user's host Chrome via OpenCLI.

This specifically targets the current failure mode where `yt-dlp` / direct HTTP calls against space endpoints frequently hit `412`.

## Constraints

1. Backend runs inside Docker (docker-compose).
2. Chrome runs on the host machine.
3. We must reuse the host Chrome login state (no cookie export).
4. Avoid large invasive changes to backend container image.
5. Prefer stable, debuggable integration that can be switched off.

## Chosen Approach (Option 1): OpenCLI Sidecar Container

We add an `opencli` sidecar container that:

1. Runs OpenCLI daemon and CLI inside the container.
2. Exposes daemon port `19825` to the host as `127.0.0.1:19825`.
3. Host Chrome extension connects to `localhost:19825` (unchanged for users).
4. Provides a small HTTP API to the backend container to request a Bilibili space video list.

The backend container will call the sidecar HTTP API and get a normalized list of entries `{ video_id, title, duration, thumbnail, video_url }`.

### Why sidecar

1. No need to install Node/OpenCLI into the backend image.
2. Isolates OpenCLI instability from the backend process.
3. Keeps the host Chrome interaction entirely through the official OpenCLI Browser Bridge extension.

## High-Level Architecture

Components:

1. Host Chrome + OpenCLI Browser Bridge extension
2. `opencli` sidecar container
   - OpenCLI daemon (listens on 0.0.0.0:19825 inside container)
   - HTTP service (listens on 0.0.0.0:19826 inside container)
   - Uses `opencli browser ...` commands to drive host Chrome through the extension
3. `backend` container
   - Calls `http://opencli:19826/...` on the Docker network
   - Uses results to populate `/api/detect_url` entries for space URLs

Networking:

1. `127.0.0.1:19825` (host) -> `opencli:19825` (container)
2. `backend` -> `opencli:19826` (container-to-container)

## HTTP API (Sidecar)

Endpoints:

1. `GET /healthz`
   - Returns 200 if service is running.
2. `GET /bilibili/space_videos?uid=<uid>&max_pages=<n>`
   - Returns JSON array of videos:
     - `video_id` (BV...)
     - `title`
     - `duration` (optional/0 if unavailable)
     - `thumbnail` (optional/empty if unavailable)
     - `video_url` (canonical `https://www.bilibili.com/video/BV.../`)

Sidecar error handling:

1. If `opencli doctor` does not show `Extension: connected`, return 503 with actionable message.
2. If navigation/eval fails, return 502 with stderr captured.
3. Implement retries (e.g. up to 3) around `opencli browser eval` for transient issues.

## Bilibili Extraction Strategy (OpenCLI)

Target page:

`https://space.bilibili.com/<uid>/upload/video`

Extraction logic (aligned with `OPENCLI-AI-REFERENCE.md` best practices):

1. Prefer `opencli browser tab new <URL>` to reduce instability.
2. Wait for render by polling `document.documentElement.outerHTML.length` until > 10000 (timeout ~15s).
3. For each page:
   - Extract all `a[href*="BV"]` links.
   - Parse `BV...` from href.
   - Build canonical URL `https://www.bilibili.com/video/<bvid>/`.
   - De-duplicate by `bvid`.
4. Pagination:
   - Click the button containing text `下一页`.
   - Wait 3-5 seconds after click.
   - Stop when next button not found / disabled, or `max_pages` reached.
5. Close browser session via `opencli browser close` (best-effort).

Notes:

1. Title/thumbnail/duration may not be reliably obtainable from DOM; collect what we can without overfitting selectors.
2. The primary deliverable is the list of canonical video URLs.

## Backend Integration

We will integrate the sidecar into backend URL detection.

1. Add a small client that calls `OPENCLI_SERVICE_URL` (default `http://opencli:19826`).
2. Extend `/api/detect_url` behavior:
   - If URL matches Bilibili space patterns (`space.bilibili.com/<uid>` or contains `/upload/video`), call sidecar and return `type=multi` with entries.
   - Otherwise keep current yt-dlp based logic.
3. Fallback:
   - If yt-dlp throws 412 (or any failure) for a suspected space URL, attempt sidecar.

Security:

1. Sidecar daemon port is bound to `127.0.0.1` on host only.
2. Sidecar HTTP API is only exposed to Docker network (no host publish).
3. No cookies are persisted by BiliNote; Chrome handles auth.

## docker-compose Changes

Add an `opencli` service:

1. Image includes Node >= 20 and installs `@jackwener/opencli`.
2. Starts `opencli daemon` and the HTTP server.
3. Publishes host port mapping: `127.0.0.1:19825:19825`.
4. `backend` depends_on `opencli`.

Operational note:

If the host is already running an OpenCLI daemon bound to `127.0.0.1:19825`, docker-compose will fail to bind the port. The user must stop the host daemon (or we must adjust the Chrome extension to use another port if supported).

## Testing Strategy

1. Unit test backend client parsing and error mapping (mock HTTP responses).
2. API tests for `/api/detect_url` on a space URL with sidecar mocked.
3. No automated E2E for OpenCLI/browser interaction in CI; verify manually in a dev environment.

## Success Criteria

1. Given a Bilibili space URL, `/api/detect_url` returns `type=multi` and a non-empty entries list without 412.
2. User can select entries in the existing batch flow and submit `/api/generate_batch_note`.
3. Works in docker-compose with host Chrome login session.
