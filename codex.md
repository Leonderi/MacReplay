# Codex Project Notes: MacReplay (stb-proxy)

Short purpose
- Web app that proxies Stalker/MAC portals and generates M3U/XMLTV for Plex and similar clients.
- Docker-first setup with persistent data/logs volumes.

Key entry points
- app.py: Flask app, routes, EPG/playlist generation, DB access, logs, background refresh.
- stb.py: Stalker portal API client and streaming helpers.
- templates/: Jinja UI (dashboard, editor, portals, logs, settings, epg).
- static/: CSS/JS assets.

Runtime data (default)
- DATA_DIR: /app/data
- LOG_DIR: /app/logs
- Config JSON: /app/data/MacReplay.json (CONFIG)
- SQLite DB: /app/data/channels.db (DB_PATH)
- EPG cache: /app/data/epg_cache.xml (EPG_CACHE_PATH)

Important env vars
- BIND_HOST, PORT: listen address/port (default 0.0.0.0:8001)
- PUBLIC_HOST or HOST: used for generated URLs
- CONFIG, DB_PATH, DATA_DIR, LOG_DIR, EPG_CACHE_PATH
- FFMPEG, FFPROBE

Primary routes (selected)
- /dashboard (via /api/dashboard): active streams + quick downloads
- /editor + /api/editor_*: channel editor + bulk ops
- /portals: portal/MAC management + genre groups
- /logs and /logs/stream: live log viewer
- /xmltv, /playlist.m3u: generated outputs
- /streaming: active stream list JSON

Docker compose
- docker-compose.yml exposes 8001 and mounts /opt/stb-proxy/{data,logs} to /app/{data,logs}.

Tests
- pytest (see README.md)

Notes on existing features
- Live log viewer + download endpoint is implemented.
- Portal genre/group selection and editor merge/duplicate tooling exist.
