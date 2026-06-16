# Music Downloader → Copytele (via MeTube)

Download the audio from a YouTube or TikTok video and push it to your copyparty
instance (`copytele.zum.vn`). The actual downloading is delegated to your
existing **MeTube** (`metube.zum.vn`); this app is a thin, **authenticated
orchestrator** that drives MeTube and then uploads the result to copytele.

Two ways to use it:

1. **Web app** — open the site, paste a URL, pick a format, hit download.
2. **iPhone Shortcut** — while watching YouTube/TikTok, tap **Share → your
   shortcut**, choose a format, and the audio lands in copytele automatically.

---

## How it works

```
iPhone Share Sheet ─┐
Web UI (paste URL) ─┴─► POST /api/download ─► MeTube /add (audio, best)
                                          ├─► poll MeTube /history until finished
                                          ├─► GET MeTube /audio_download/<file>
                                          ├─► PUT file to copytele/music/<source>/
                                          └─► MeTube /delete (cleanup) → returns link
```

Why through MeTube: you already run it, and it brings a robust yt-dlp queue,
retries, cookie handling (for age/region-locked videos) and history. This app
adds the two things MeTube lacks for your use case: **authentication** (MeTube
has none) and **automatic upload to copytele**, organised by source.

| Endpoint            | Method | Purpose                                              |
| ------------------- | ------ | ---------------------------------------------------- |
| `/`                 | GET    | Web UI                                               |
| `/api/download`     | POST   | `{ "url": "...", "format": "m4a" }` → download+upload |
| `/shortcut`         | GET    | `?token=...` → downloads the iOS shortcut file       |
| `/healthz`          | GET    | Liveness check                                       |

`/api/download` requires an `Authorization: Bearer <API_TOKEN>` header. `format`
is one of:

| `format` | Behaviour                                                              |
| -------- | --------------------------------------------------------------------- |
| `m4a`    | *(default)* extract to M4A — **lossless copy** for YouTube/TikTok AAC  |
| `opus`   | extract to Opus — **lossless copy** if the source is Opus             |
| `mp3`    | transcode to 320 kbps MP3 (always a lossy re-encode)                  |

Files land in copytele as `/music/youtube/<title>.m4a` and
`/music/tiktok/<title>.m4a` (source detected from the URL host).

---

## Requirements on your MeTube

- Reachable from this app at `METUBE_BASE` (e.g. `https://metube.zum.vn`).
- This app talks to MeTube's current API: `POST /add` (with
  `download_type:"audio"`), `GET /history`, `GET /audio_download/...`,
  `POST /delete`. Keep MeTube reasonably up to date.
- **MeTube has no auth** — don't expose it to the public internet, or put it
  behind your reverse proxy with IP allow-listing / basic auth. This app is the
  authenticated front door; MeTube can stay private (only this app needs to
  reach it).

---

## Setup

```bash
cp .env.template .env
# generate a strong token:
python -c "import secrets; print(secrets.token_urlsafe(32))"
# edit .env: paste it into API_TOKEN, set METUBE_BASE, COPYTELE_* as needed
```

| Var                        | Meaning                                                            |
| -------------------------- | ----------------------------------------------------------------- |
| `API_TOKEN`                | Secret the web UI / Shortcut must send. Make it long+random.      |
| `PUBLIC_BASE_URL`          | Public URL of this app (e.g. `https://music.zum.vn`), baked into the shortcut. Blank = derived from request. |
| `METUBE_BASE`              | Your MeTube URL, e.g. `https://metube.zum.vn`.                    |
| `METUBE_TIMEOUT_SEC`       | Max wait for a download to finish (default 600).                 |
| `METUBE_POLL_INTERVAL_SEC` | How often to poll MeTube while waiting (default 2).              |
| `COPYTELE_BASE`            | `https://copytele.zum.vn`.                                        |
| `COPYTELE_UPLOAD_PATH`     | Base folder/volume, e.g. `/music/`. `youtube/` or `tiktok/` is appended. |
| `COPYTELE_PW`              | Copyparty upload password. **Leave blank** if uploads need no password. |

> Copyparty auto-creates the `youtube/` / `tiktok/` subfolders on upload; if
> yours doesn't, create them once. Test a manual upload (drop `-H "PW: ..."` if
> the volume needs no password):
> ```bash
> curl -X PUT --data-binary @song.m4a https://copytele.zum.vn/music/youtube/song.m4a
> ```

---

## Run with Docker

```bash
docker compose up --build -d
curl http://127.0.0.1:8077/healthz   # -> {"ok":true}
```

The container binds to `127.0.0.1:8077`. Point the reverse proxy that fronts
your other services at it on a new subdomain (e.g. `music.zum.vn`).

**Caddy:**
```caddy
music.zum.vn {
    reverse_proxy 127.0.0.1:8077
}
```

**nginx:**
```nginx
server {
    server_name music.zum.vn;
    location / {
        proxy_pass http://127.0.0.1:8077;
        proxy_set_header Host $host;
        client_max_body_size 0;   # allow large audio uploads
    }
}
```

Then add a DNS record for `music.zum.vn`.

### Run without Docker (local dev)

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8077
```

No ffmpeg/yt-dlp needed here — MeTube does that work.

---

## CI/CD — auto build, push & deploy

`.github/workflows/deploy.yml` runs on every push to `main`:

1. **build-and-push** — builds the image and pushes it to GHCR as
   `ghcr.io/<owner>/<repo>:latest` (and a `:sha-<commit>` tag). Uses the built-in
   `GITHUB_TOKEN`, no extra secret needed.
2. **deploy** — SSHes to your server and runs `docker compose pull && up -d`.
   Only runs when the repo variable `DEPLOY_ENABLED=true` is set.

**One-time GitHub setup** (repo → Settings → Secrets and variables → Actions):

| Kind     | Name           | Value                                             |
| -------- | -------------- | ------------------------------------------------- |
| Variable | `DEPLOY_ENABLED` | `true` to enable the SSH deploy job             |
| Secret   | `SSH_HOST`     | server hostname/IP                                |
| Secret   | `SSH_USER`     | SSH user (must be in the `docker` group)          |
| Secret   | `SSH_KEY`      | private key for that user (PEM)                   |
| Secret   | `SSH_PORT`     | *(optional)* SSH port, defaults to 22             |
| Secret   | `DEPLOY_PATH`  | dir on the server holding `docker-compose.yml` + `.env` |

**One-time server setup:** put `docker-compose.yml` + a filled `.env` in
`DEPLOY_PATH`, and add to that `.env`:
```
MUSIC_IMAGE=ghcr.io/<owner>/<repo>:latest
```
so `docker compose pull` fetches the CI-built image. The deploy logs in to GHCR
with the workflow token; alternatively make the GHCR package public (repo →
Packages → package settings) and drop the login.

> This project isn't a git repo yet. To use the workflow:
> `git init && git add -A && git commit -m "init"`, create a GitHub repo, then
> `git push`. The first push to `main` triggers the build.

---

## iPhone Shortcut (Share Sheet → download music)

The app generates a ready-made shortcut with your token already baked in, and it
**asks which format** each time it runs.

**Easiest way (from your iPhone):**
1. Open `https://music.zum.vn` in Safari, enter your **API token**.
2. Tap **➕ Add iPhone Shortcut** — Safari downloads `Save Music to
   Copytele.shortcut`.
3. Open it (Downloads → tap the file) → **Shortcuts** imports it.
   - First time only: enable **Settings → Shortcuts → Allow Untrusted
     Shortcuts** (you must have run any shortcut once before this appears).
4. **Use it:** in YouTube or TikTok, open a video → **Share** → **Save Music to
   Copytele** → pick **M4A / Opus / MP3 320**. Audio is fetched and pushed to
   copytele.

Direct download link: `https://music.zum.vn/shortcut?token=YOUR_API_TOKEN`

> TikTok's share sheet sometimes shares a `vt.tiktok.com/...` short link — fine,
> yt-dlp (inside MeTube) resolves it.

**Manual build (fallback, if untrusted import is a hassle):**
1. **Shortcuts → +**, name it *Save Music to Copytele*.
2. **ⓘ** → enable **Show in Share Sheet**, keep **URLs** + **Text** on.
3. Action **Get Contents of URL** → URL `https://music.zum.vn/api/download`,
   **Show More**: Method `POST`; Header `Authorization` = `Bearer YOUR_API_TOKEN`;
   Request Body `JSON` with `url` = **Shortcut Input** and `format` = `m4a`.

---

## Quick API test

```bash
TOKEN=$(grep API_TOKEN .env | cut -d= -f2)
curl -X POST http://127.0.0.1:8077/api/download \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","format":"m4a"}'
```

Response:
```json
{
  "ok": true,
  "filename": "Rick Astley - Never Gonna Give You Up [dQw4w9WgXcQ].m4a",
  "source": "youtube",
  "copytele_url": "https://copytele.zum.vn/music/youtube/Rick%20Astley...m4a"
}
```

---

## About audio quality

- **You can't beat the source.** YouTube/TikTok audio is already lossy
  (~128 kbps AAC/Opus). No tool can add back detail the platform never sent.
- **`m4a` / `opus` are lossless *copies* when they match the source codec.**
  YouTube/TikTok usually serve AAC, so `m4a` just remuxes (ffmpeg `-c copy`) —
  bit-for-bit the same audio you hear in the app. For an Opus source, choose
  `opus` to stay lossless.
- **`mp3` re-encodes** (a second lossy pass) — use it only for compatibility.
- "Sounds better in TikTok" usually means an older tool grabbed a worse format
  or transcoded to a low-bitrate MP3 — avoided here by defaulting to `m4a`.

> Note: MeTube's audio mode always *extracts* to a chosen codec (there's no
> "keep the original container untouched" option), but with `m4a`/`opus` on a
> matching source that extraction is a lossless stream copy, so quality is
> preserved.

---

## Notes / limits

- **Uploads are routed by source**: `/music/youtube/…` and `/music/tiktok/…`
  (anything else → `/music/other/…`). Source is detected from the URL host.
- The endpoint is internet-facing (the Shortcut must reach it), so the
  `API_TOKEN` is the only gate — keep it long and secret.
- A request blocks until MeTube finishes (or `METUBE_TIMEOUT_SEC` elapses);
  long videos may take a while. The shortcut shows a notification when done.
- After a successful upload, the item is removed from MeTube (`/delete`) so its
  history/disk stays clean and re-downloads aren't skipped.
- Playlists/channels: pass a single video URL.
