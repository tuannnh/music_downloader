"""FastAPI app: download audio from a video URL and push it to copytele."""

from __future__ import annotations

import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, HttpUrl

from .config import Settings, get_settings
from .metube import MetubeClient, MetubeError, source_for_url
from .shortcut import build_shortcut
from .uploader import UploadError, upload_file

# Audio formats MeTube produces (download_type "audio").
AudioFormat = Literal["m4a", "mp3", "opus"]

app = FastAPI(title="Music Downloader → Copytele")

STATIC_DIR = Path(__file__).parent / "static"


class DownloadRequest(BaseModel):
    url: HttpUrl
    format: AudioFormat = "m4a"


class DownloadResponse(BaseModel):
    ok: bool
    filename: str
    source: str
    copytele_url: str


def require_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate the Bearer token using a constant-time comparison."""
    expected = f"Bearer {settings.api_token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing token.")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/download", response_model=DownloadResponse)
def api_download(
    req: DownloadRequest,
    _: None = Depends(require_token),
    settings: Settings = Depends(get_settings),
) -> DownloadResponse:
    url = str(req.url)
    source = source_for_url(url)
    metube = MetubeClient(settings.metube_base)
    tmp_dir = tempfile.mkdtemp(prefix="musicdl-")
    try:
        # Clear any stale finished entry so re-downloads aren't skipped, then add.
        metube.delete_done(url)
        try:
            metube.add(url, req.format)
            item = metube.wait_until_done(
                url,
                timeout=settings.metube_timeout_sec,
                poll=settings.metube_poll_interval_sec,
            )
            local_path = str(Path(tmp_dir) / "audio")
            filename = metube.download_finished_file(item, local_path)
        except MetubeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        # Route into a per-source subfolder, e.g. /music/youtube/ or /music/tiktok/.
        upload_path = f"{settings.normalized_upload_path()}{source}/"
        try:
            copytele_url = upload_file(
                local_path=local_path,
                filename=filename,
                base=settings.copytele_base,
                upload_path=upload_path,
                password=settings.copytele_pw,
            )
        except UploadError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        # Tidy up MeTube now that the file is safely on copytele.
        metube.delete_done(url)

        return DownloadResponse(
            ok=True,
            filename=filename,
            source=source,
            copytele_url=copytele_url,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/shortcut")
def get_shortcut(
    request: Request,
    token: str | None = None,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Download a ready-to-import iOS Shortcut with the token baked in.

    Auth via ?token=<API_TOKEN> (so a plain browser link works) or a Bearer
    header. The shortcut posts shared URLs to this app's /api/download.
    """
    supplied = token or (
        authorization[len("Bearer ") :]
        if authorization and authorization.startswith("Bearer ")
        else None
    )
    if not supplied or not secrets.compare_digest(supplied, settings.api_token):
        raise HTTPException(status_code=401, detail="Invalid or missing token.")

    base = settings.public_base_url.rstrip("/") or str(request.base_url).rstrip("/")
    data = build_shortcut(api_url=f"{base}/api/download", token=settings.api_token)

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="Save Music to Copytele.shortcut"'
        },
    )
