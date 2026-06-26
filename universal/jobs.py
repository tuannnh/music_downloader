from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass, field

from universal.pipeline import process

# Job lifecycle: queued -> running -> done | error
QUEUED, RUNNING, DONE, ERROR = "queued", "running", "done", "error"


@dataclass
class Job:
    id: str
    url: str
    requested_type: str = "auto"
    status: str = QUEUED
    platform: str = ""
    media_type: str = ""
    title: str = ""
    count: int = 0
    files: list[str] = field(default_factory=list)
    copytele_urls: list[str] = field(default_factory=list)
    folder: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def public(self) -> dict:
        return asdict(self)


class JobManager:
    """In-memory queue with a single sequential worker.

    Downloads run one at a time (so we never hammer the box or the source),
    and the HTTP request returns immediately with a job id to poll.

    NOTE: state is in-process — run uvicorn with a single worker.
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

    def enqueue(self, url: str, requested_type: str = "auto") -> Job:
        job = Job(id=uuid.uuid4().hex[:12], url=url, requested_type=requested_type)
        self._jobs[job.id] = job
        self._prune()
        self._queue.put_nowait(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def wait_for(self, job_id: str, timeout: float) -> Job | None:
        """Poll a job until it leaves a non-terminal state or `timeout` elapses."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self._jobs.get(job_id)
            if job is None or job.status in (DONE, ERROR):
                return job
            await asyncio.sleep(0.5)
        return self._jobs.get(job_id)

    def _prune(self) -> None:
        if len(self._jobs) <= self._max_jobs:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.finished_at is not None),
            key=lambda j: j.finished_at,
        )
        for job in finished[: len(self._jobs) - self._max_jobs]:
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
                data = await asyncio.to_thread(process, job.url, job.requested_type)
                job.platform = data["platform"]
                job.media_type = data["media_type"]
                job.title = data["title"]
                job.count = data["count"]
                job.files = data["files"]
                job.copytele_urls = data["copytele_urls"]
                job.folder = data["folder"]
                job.status = DONE
            except Exception as exc:  # noqa: BLE001 - record any failure on the job
                job.error = f"{type(exc).__name__}: {exc}"
                job.status = ERROR
            finally:
                job.finished_at = time.time()
                self._queue.task_done()


jobs = JobManager()
