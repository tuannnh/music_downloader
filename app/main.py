from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import settings
from app.jobs import jobs


@asynccontextmanager
async def lifespan(_: FastAPI):
    jobs.start()
    try:
        yield
    finally:
        await jobs.stop()


app = FastAPI(title="Music Downloader → copytele", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# How long /api/save?wait=1 will block before handing back a still-running job.
WAIT_TIMEOUT = 180.0


class DownloadRequest(BaseModel):
    url: str


def _enqueue(url: str):
    """Validate + queue. Returns (job, error_response)."""
    url = (url or "").strip()
    if not url:
        return None, JSONResponse({"status": "error", "error": "Missing url"}, status_code=400)
    return jobs.enqueue(url), None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"target": settings.upload_base}
    )


@app.post("/api/download")
async def api_download_json(payload: DownloadRequest):
    """Queue a job. Body: {"url": "..."}. Returns the job immediately (202)."""
    job, err = _enqueue(payload.url)
    if err:
        return err
    return JSONResponse(job.public(), status_code=202)


@app.post("/api/download-form")
async def api_download_form(url: str = Form(...)):
    """Form-encoded variant. Queues and returns the job immediately."""
    job, err = _enqueue(url)
    if err:
        return err
    return JSONResponse(job.public(), status_code=202)


@app.get("/api/save")
async def api_save(url: str = "", wait: int = 0):
    """iOS-Shortcut endpoint: GET /api/save?url=...

    Default: returns instantly with a queued job (the download runs in the
    background). Add &wait=1 to block until it finishes so a Shortcut
    notification can show the real ✅/❌ result.
    """
    job, err = _enqueue(url)
    if err:
        return err
    if wait:
        job = await jobs.wait_for(job.id, WAIT_TIMEOUT)
    return JSONResponse(job.public(), status_code=202 if job.status in ("queued", "running") else 200)


@app.get("/api/jobs/{job_id}")
async def api_job_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        return JSONResponse({"status": "error", "error": "Unknown job id"}, status_code=404)
    return JSONResponse(job.public())


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
