# 🎵 Music Downloader → copytele

A tiny webapp that takes a **YouTube** or **TikTok** URL, downloads the
**best-quality audio** (no lossy re-encode, with title/cover-art metadata), and
pushes it straight onto your **copytele** (copyparty clone) volume.

Use it from the browser, or trigger it from an **iOS Share-Sheet Shortcut** while
watching a TikTok.

## How it works

```
URL ──► FastAPI ──► yt-dlp (+ffmpeg: best audio, metadata, cover art) ──► HTTP PUT ──► copytele volume
```

- `bestaudio/best` keeps the source codec (YouTube opus/m4a, TikTok original sound)
  — TikTok's "original sound" is often the cleaner master, which is why it can sound
  better than the YouTube upload.
- Files land in a **per-source subfolder**: `…/music/youtube/`, `…/music/tiktok/`
  (anything else → `…/music/other/`). copyparty creates these folders on upload.
- Files are uploaded via a plain copyparty `PUT`, so an **open/no-auth volume** just works.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `COPYTELE_UPLOAD_URL` | `http://localhost:3923/music/` | Destination folder. **Must end with `/`.** |
| `COPYTELE_PW` | *(empty)* | copyparty password; empty = open volume. |
| `OVERWRITE` | `false` | Replace same-name file instead of auto-renaming. |
| `DOWNLOAD_DIR` | `/tmp/music_downloader` | Temp buffer, cleared after each job. |
| `COOKIES_FILE` | *(empty)* | Path to a Netscape `cookies.txt` for TikTok / restricted YouTube. |
| `MAX_JOBS` | `200` | Finished jobs kept in memory for status polling. |
| `HOST` / `PORT` | `0.0.0.0` / `8080` | Server bind. |

> ⚠️ Run with a **single uvicorn worker** — the job queue is in-process.

## Background jobs

Requests don't block on the download. `POST /api/download` (and `/api/save`)
**queue** the job and return immediately with a job `id`; downloads run one at a
time in a background worker. Poll `GET /api/jobs/{id}` for progress
(`queued → running → done | error`). The web UI does this polling for you.

## TikTok cookies fallback

Some TikTok links (and age/region-restricted YouTube) need a logged-in session.
Export your cookies to a **Netscape-format `cookies.txt`** (e.g. the
"Get cookies.txt" browser extension), then:

- **Docker:** put the file at `./cookies/cookies.txt` — it's mounted read-only to
  `/cookies/cookies.txt`, which `COOKIES_FILE` already points at.
- **Local:** set `COOKIES_FILE=/abs/path/cookies.txt` in `.env`.

It's used automatically when present and ignored when missing — no code changes.

## Run with Docker (recommended for your server)

1. Edit `COPYTELE_UPLOAD_URL` in `docker-compose.yml`.
2. `docker compose up -d --build`
3. In **nginx-proxy-manager**, add a Proxy Host → forward to the
   `music-downloader` container, port **8080**. Give it a hostname like
   `music.yourdomain`. (Add Access List / Basic Auth there if you want a gate.)

## Run locally (dev)

Requires `ffmpeg` on the host.

```bash
cp .env.example .env      # edit COPYTELE_UPLOAD_URL
uv sync                   # or: uv pip install -r pyproject.toml
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open http://localhost:8080.

## API

| Method | Path | Body / Query | Notes |
|---|---|---|---|
| `POST` | `/api/download` | JSON `{"url": "..."}` | Queues, returns job (202). Used by the web UI. |
| `POST` | `/api/download-form` | form field `url` | Form-encoded; queues, returns job. |
| `GET`  | `/api/save?url=...` | `url`, optional `wait=1` | Easiest for iOS Shortcuts. |
| `GET`  | `/api/jobs/{id}` | — | Poll job status. |
| `GET`  | `/healthz` | — | Health check. |

Queue response (immediate):

```json
{ "id": "a1b2c3d4e5f6", "status": "queued", "url": "..." }
```

Finished job (from `/api/jobs/{id}`, or `/api/save?wait=1`):

```json
{ "id": "a1b2c3d4e5f6", "status": "done", "title": "...", "source": "tiktok",
  "filename": "....m4a", "copytele_url": "https://files.example.com/music/....m4a" }
```

On failure: `"status": "error"` with an `"error"` message.

## 📱 iPhone Shortcut (share a TikTok → save to copytele)

1. Open the **Shortcuts** app → **+** → name it e.g. *"Save to copytele"*.
2. Tap the shortcut's settings (ⓘ) → enable **Show in Share Sheet**, and set
   **Share Sheet Types** to **URLs** (and optionally Text/Safari web pages).
3. Add these actions:
   - **Receive** *URLs* input from *Share Sheet*.
   - **Text** → set its value to:
     `https://music.yourdomain/api/save?url=`
     then place the **Shortcut Input** variable right after the `=`.
     *(Tip: wrap the input in a `URL Encode` action first if links misbehave.)*
   - **Get Contents of URL** → URL = the Text above, **Method: GET**.
   - *(optional)* **Show Notification** → show the result so you get a ✅/❌.
4. Now in TikTok: **Share → Save to copytele**. Done.

**Instant vs. confirmed:**

- As written (`/api/save?url=...`) the Shortcut returns **instantly** — the
  download runs in the background. Quick, but the notification only says *queued*.
- Want a real ✅/❌ in the notification? Append **`&wait=1`** to the URL so the
  request waits for the download to finish (up to 3 min) before responding.

> Prefer POST? Use **Get Contents of URL** with Method **POST**, Request Body
> **JSON**, key `url` = Shortcut Input, against `https://music.yourdomain/api/download`
> (also returns immediately with a job id).
