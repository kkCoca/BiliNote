# OpenCLI (Host Chrome) Integration

This repo can fetch Bilibili creator space video lists by reusing your host Chrome login session via OpenCLI.

## What You Need

1. Host Chrome/Chromium.
2. Install the OpenCLI Browser Bridge extension (`opencli-extension.zip`) and enable it in `chrome://extensions`.
3. Log in to `bilibili.com` in that Chrome profile.

## docker-compose Wiring

We add an `opencli` sidecar container:

1. Host Chrome extension connects to `localhost:19825`.
2. In docker-compose, `opencli` publishes `127.0.0.1:19825:19825`.
3. Backend calls the sidecar HTTP API at `http://opencli:19826`.

Important:

If the host is already running an OpenCLI daemon on port `19825`, stop it first, otherwise docker-compose cannot bind the port.

Example:

```bash
opencli daemon stop
```

## Verify

1. Start stack:

```bash
docker-compose up -d --build
```

2. Inside the opencli container:

```bash
docker exec -it bilinote-opencli opencli doctor
```

Expected: `Extension: connected`.

## API Behavior

When calling backend `POST /api/detect_url` with a Bilibili space URL like:

`https://space.bilibili.com/<uid>/upload/video`

the backend will request the list from the sidecar (host Chrome), returning `type=multi` and the list of canonical `video_url` entries.
