from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field

from universal import pipeline

# Job lifecycle:
#   process task: queued -> running -> done | error
#   prepare task: queued -> running -> ready -> running(commit) -> done | error
QUEUED, RUNNING, READY, DONE, ERROR = "queued", "running", "ready", "done", "error"

# How long a prepared-but-uncommitted download is kept before its temp files are
# swept (the user loaded a URL but never picked anything).
PREPARE_TTL = 1800.0  # 30 min

# Fields kept server-side only — never sent to the browser.
_PRIVATE = {"workdir", "abs_files"}


@dataclass
class Job:
    id: str
    url: str
    task: str = "process"            # "process" (one-shot) or "prepare"
    requested_type: str = "auto"
    status: str = QUEUED
    platform: str = ""
    media_type: str = ""
    title: str = ""
    count: int = 0
    items: list[dict] = field(default_factory=list)      # prepared media for the UI
    files: list[str] = field(default_factory=list)       # uploaded filenames
    copytele_urls: list[str] = field(default_factory=list)
    folder: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    # server-side only:
    workdir: str = ""
    abs_files: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k not in _PRIVATE}


class JobManager:
    """In-memory queue with a single sequential worker.

    Handles both one-shot downloads (`process`) and the interactive
    prepare → pick → commit flow. State is in-process — run a single uvicorn
    worker.
    """

    def __init__(self, max_jobs: int = 200) -> None:
        self._jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._max_jobs = max_jobs

    def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    def _new(self, url: str, task: str, requested_type: str) -> Job:
        self._sweep_expired()
        job = Job(id=uuid.uuid4().hex[:12], url=url, task=task, requested_type=requested_type)
        self._jobs[job.id] = job
        self._prune()
        self._queue.put_nowait(job.id)
        return job

    def enqueue(self, url: str, requested_type: str = "auto") -> Job:
        return self._new(url, "process", requested_type)

    def enqueue_prepare(self, url: str, requested_type: str = "auto") -> Job:
        return self._new(url, "prepare", requested_type)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def preview_path(self, job_id: str, index: int) -> str | None:
        """Absolute path of prepared item `index`, if it's still on disk."""
        job = self._jobs.get(job_id)
        if job is None or not job.workdir:
            return None
        if 0 <= index < len(job.abs_files):
            path = job.abs_files[index]
            if os.path.isfile(path):
                return path
        return None

    async def commit(self, job_id: str, indices: list[int]) -> Job | None:
        """Upload the chosen prepared items to copytele, then clean up."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status != READY:
            return job
        selected = [job.abs_files[i] for i in indices if 0 <= i < len(job.abs_files)]
        if not selected:
            job.error = "No items selected."
            job.status = ERROR
            job.finished_at = time.time()
            shutil.rmtree(job.workdir, ignore_errors=True)
            job.workdir, job.abs_files = "", []
            return job
        job.status = RUNNING
        workdir = job.workdir
        try:
            names, urls = await asyncio.to_thread(
                pipeline.commit, workdir, job.platform, job.media_type, selected
            )
            job.files, job.copytele_urls, job.count = names, urls, len(urls)
            job.folder = f"{job.platform}/{job.media_type}"
            job.status = DONE
        except Exception as exc:  # noqa: BLE001
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = ERROR
        finally:
            job.workdir, job.abs_files = "", []
            job.finished_at = time.time()
        return job

    async def wait_for(self, job_id: str, timeout: float) -> Job | None:
        """Poll a job until it leaves a non-terminal state or `timeout` elapses."""
        deadline = time.monotonic() + timeout
        terminal = (READY, DONE, ERROR)
        while time.monotonic() < deadline:
            job = self._jobs.get(job_id)
            if job is None or job.status in terminal:
                return job
            await asyncio.sleep(0.5)
        return self._jobs.get(job_id)

    def _sweep_expired(self) -> None:
        now = time.time()
        for jid, job in list(self._jobs.items()):
            if job.status == READY and job.workdir and now - job.created_at > PREPARE_TTL:
                shutil.rmtree(job.workdir, ignore_errors=True)
                self._jobs.pop(jid, None)

    def _prune(self) -> None:
        if len(self._jobs) <= self._max_jobs:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.finished_at is not None),
            key=lambda j: j.finished_at,
        )
        for job in finished[: len(self._jobs) - self._max_jobs]:
            if job.workdir:
                shutil.rmtree(job.workdir, ignore_errors=True)
            self._jobs.pop(job.id, None)

    async def _worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            job = self._jobs.get(job_id)
            if job is None:
                self._queue.task_done()
                continue
            job.status = RUNNING
            try:
                if job.task == "prepare":
                    data = await asyncio.to_thread(pipeline.prepare, job.url, job.requested_type)
                    job.platform = data["platform"]
                    job.media_type = data["media_type"]
                    job.title = data["title"]
                    job.workdir = data["workdir"]
                    job.abs_files = data["files"]
                    job.items = data["items"]
                    job.count = len(data["items"])
                    job.folder = f"{job.platform}/{job.media_type}"
                    job.status = READY
                else:
                    data = await asyncio.to_thread(pipeline.process, job.url, job.requested_type)
                    job.platform = data["platform"]
                    job.media_type = data["media_type"]
                    job.title = data["title"]
                    job.count = data["count"]
                    job.files = data["files"]
                    job.copytele_urls = data["copytele_urls"]
                    job.folder = data["folder"]
                    job.status = DONE
                    job.finished_at = time.time()
            except Exception as exc:  # noqa: BLE001 - record any failure on the job
                job.error = f"{type(exc).__name__}: {exc}"
                job.status = ERROR
                job.finished_at = time.time()
                if job.workdir:
                    shutil.rmtree(job.workdir, ignore_errors=True)
                    job.workdir, job.abs_files = "", []
            finally:
                self._queue.task_done()


jobs = JobManager()
