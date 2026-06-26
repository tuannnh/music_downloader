# ⬇️ Universal Downloader → copytele

A second, **separate** app (the music downloader in `app/` is unchanged). Takes a
**TikTok / Instagram / Facebook** URL, downloads the **original media** (video *or*
photos — no re-encode), and pushes every file onto your **copytele** volume under:

```
source/<platform>/<videos|photos>/
   e.g.  source/tiktok/videos/…mp4
         source/tiktok/photos/…jpg
         source/instagram/photos/…jpg
         source/facebook/videos/…mp4
```

## How it works

```
URL ─► FastAPI ─┬─ type=video ─► yt-dlp (+ffmpeg)         ─┐
                └─ type=photo ─► gallery-dl (image posts)  ─┴─► HTTP PUT ─► copytele
```

- **Videos** use **yt-dlp** (browser-impersonation on for TikTok).
- **Photos** use **gallery-dl** (yt-dlp can't fetch Facebook/Instagram photos).
- `type` is `auto` (inferred from the URL), `video`, or `photo`. Photo posts /
  carousels / slideshows upload **all** their files.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `COPYTELE_UPLOAD_URL` | `https://copytele.zum.vn/source/` | Base folder. **Must end with `/`.** `<platform>/<type>/` is appended. |
| `COPYTELE_PW` | *(empty)* | copyparty password; empty = open volume. |
| `OVERWRITE` | `false` | Replace same-name file instead of auto-renaming. |
| `DOWNLOAD_DIR` | `/tmp/universal_downloader` | Temp buffer, cleared after each job. |
| `COOKIES_DIR` | `/cookies` | Dir holding per-platform cookie files (see below). |
| `MAX_JOBS` | `200` | Finished jobs kept in memory for status polling. |
| `HOST` / `PORT` | `0.0.0.0` / `8081` | Server bind. |

> ⚠️ Run with a **single uvicorn worker** — the job queue is in-process.

## Cookies (optional — only for private / login-walled content)

Cookies are **not required** for public profiles/posts — leave them out and downloads
are attempted anonymously. Add them only if a specific **private** or login-walled item
fails. Export a **Netscape `cookies.txt`** from a logged-in browser (e.g. the
"Get cookies.txt" extension) and drop one file per platform into the mounted `cookies/`
dir, named by platform:

```
cookies/instagram.txt     # only if a private IG item needs login
cookies/facebook.txt      # only if a private FB item needs login
cookies/tiktok.txt         # rarely needed
```

Each is used automatically for that platform when present, and silently ignored when
missing. TikTok is also subject to occasional IP-level WAF blocks (transient — retry later).

## Run with Docker

```bash
# .env supplies COPYTELE_UPLOAD_URL (use copytele's DIRECT LAN origin, ending in
# /source/) and COPYTELE_PW. Put cookie files in ./cookies/.
docker compose -f docker-compose.universal.yml up -d
```

Then point **nginx-proxy-manager** at the `universal_downloader` container, port **8081**.
The published image is `ghcr.io/tuannnh/universal_downloader:latest` (built by CI).

## Run locally (dev)

Requires `ffmpeg` on the host.

```bash
uv pip install -r pyproject.toml && uv pip install gallery-dl
uv run uvicorn universal.main:app --host 0.0.0.0 --port 8081
```

## API

| Method | Path | Body / Query | Notes |
|---|---|---|---|
| `POST` | `/api/download` | JSON `{"url": "...", "type": "auto\|video\|photo"}` | Queues, returns job (202). Used by the UI. |
| `POST` | `/api/download-form` | form `url`, `type` | Form-encoded variant. |
| `GET`  | `/api/save?url=...&type=...` | `url`, `type`, optional `wait=1` | Easiest for iOS Shortcuts. |
| `GET`  | `/api/jobs/{id}` | — | Poll job status. |
| `GET`  | `/healthz` | — | Health check. |

Finished job (`/api/jobs/{id}` or `/api/save?wait=1`):

```json
{ "id": "…", "status": "done", "platform": "tiktok", "media_type": "photos",
  "title": "…", "count": 3, "files": ["1.jpg","2.jpg","3.jpg"],
  "copytele_urls": ["…/source/tiktok/photos/1.jpg", "…"], "folder": "tiktok/photos" }
```

On failure: `"status": "error"` with an `"error"` message.

## 📱 iPhone Shortcut (share → choose Video/Photo → save to copytele)

1. **Shortcuts** app → **+** → name it e.g. *"Save to copytele"*.
2. Settings (ⓘ) → enable **Show in Share Sheet**, set **Share Sheet Types** to **URLs**.
3. Actions:
   - **Receive** *URLs* from *Share Sheet*.
   - **Choose from Menu** → items **Video** and **Photo**.
   - In the **Video** branch: **Text** = `video`; in the **Photo** branch: **Text** = `photo`.
     (Each branch ends setting a variable, say *Kind*, to that text.)
   - **URL Encode** the *Shortcut Input* (handles `?`/`&` in shared links).
   - **Text** =
     `https://universal.yourdomain/api/save?type=` *Kind* `&wait=1&url=` *Encoded URL*
   - **Get Contents of URL** → that Text, **Method GET**.
   - **Show Notification** → show the result (✅/❌).
4. In TikTok/Instagram/Facebook: **Share → Save to copytele → Video / Photo**.

`&wait=1` makes the request wait for the download to finish (up to ~4 min) so the
notification shows the real result; drop it for an instant *queued* return.
Use `type=auto` (or omit `type`) to let the server infer from the URL.
