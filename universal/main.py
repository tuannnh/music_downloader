from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from universal.config import settings
from universal.jobs import jobs

VALID_TYPES = {"auto", "video", "photo"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    jobs.start()
    try:
        yield
    finally:
        await jobs.stop()


app = FastAPI(title="Universal Downloader → copytele", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# How long /api/save?wait=1 will block before handing back a still-running job.
WAIT_TIMEOUT = 240.0


class DownloadRequest(BaseModel):
    url: str
    type: str = "auto"


class CommitRequest(BaseModel):
    indices: list[int]


def _clean_type(media_type: str) -> str:
    media_type = (media_type or "auto").strip().lower()
    return media_type if media_type in VALID_TYPES else "auto"


def _need_url(url: str):
    url = (url or "").strip()
    if not url:
        return None, JSONResponse({"status": "error", "error": "Missing url"}, status_code=400)
    return url, None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"target": settings.upload_base})


# --- Interactive flow (web UI): prepare → pick → commit -----------------------

@app.post("/api/prepare")
async def api_prepare(payload: DownloadRequest):
    """Download media to the server WITHOUT uploading. Poll /api/jobs/{id} until
    status is `ready`, show the items, then POST /api/jobs/{id}/commit."""
    url, err = _need_url(payload.url)
    if err:
        return err
    job = jobs.enqueue_prepare(url, _clean_type(payload.type))
    return JSONResponse(job.public(), status_code=202)


@app.get("/api/jobs/{job_id}/file/{index}")
async def api_preview_file(job_id: str, index: int):
    """Serve a prepared item so the browser can show it as a thumbnail."""
    path = jobs.preview_path(job_id, index)
    if not path:
        return JSONResponse({"status": "error", "error": "Not found"}, status_code=404)
    return FileResponse(path, filename=os.path.basename(path))


@app.post("/api/jobs/{job_id}/commit")
async def api_commit(job_id: str, payload: CommitRequest):
    """Upload the chosen prepared items to copytele."""
    job = await jobs.commit(job_id, payload.indices)
    if job is None:
        return JSONResponse({"status": "error", "error": "Unknown job id"}, status_code=404)
    return JSONResponse(job.public())


# --- One-shot flow (iOS Shortcut / API): download + upload everything ---------

@app.post("/api/download")
async def api_download_json(payload: DownloadRequest):
    url, err = _need_url(payload.url)
    if err:
        return err
    job = jobs.enqueue(url, _clean_type(payload.type))
    return JSONResponse(job.public(), status_code=202)


@app.post("/api/download-form")
async def api_download_form(url: str = Form(...), type: str = Form("auto")):
    url, err = _need_url(url)
    if err:
        return err
    job = jobs.enqueue(url, _clean_type(type))
    return JSONResponse(job.public(), status_code=202)


@app.get("/api/save")
async def api_save(url: str = "", type: str = "auto", wait: int = 0):
    """iOS-Shortcut endpoint: GET /api/save?url=...&type=video|photo|auto

    Downloads and uploads everything (no interactive picking). Add &wait=1 to
    block until it finishes so a Shortcut notification can show the result.
    """
    url, err = _need_url(url)
    if err:
        return err
    job = jobs.enqueue(url, _clean_type(type))
    if wait:
        job = await jobs.wait_for(job.id, WAIT_TIMEOUT)
    status = 202 if job.status in ("queued", "running") else 200
    return JSONResponse(job.public(), status_code=status)


@app.get("/api/jobs/{job_id}")
async def api_job_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        return JSONResponse({"status": "error", "error": "Unknown job id"}, status_code=404)
    return JSONResponse(job.public())


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
