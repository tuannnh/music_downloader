from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass

from yt_dlp import YoutubeDL

# Media we keep from a download; sidecar .json/.txt/.sqlite files are ignored.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


@dataclass
class DownloadResult:
    workdir: str        # per-job temp dir (caller deletes it after upload)
    files: list[str]    # absolute paths to produced media files
    title: str


def _make_workdir() -> str:
    from universal.config import settings

    os.makedirs(settings.download_dir, exist_ok=True)
    workdir = os.path.join(settings.download_dir, uuid.uuid4().hex)
    os.makedirs(workdir, exist_ok=True)
    return workdir


def _media_files(workdir: str) -> list[str]:
    out: list[str] = []
    for root, _dirs, names in os.walk(workdir):
        for n in names:
            if os.path.splitext(n)[1].lower() in MEDIA_EXTS:
                out.append(os.path.join(root, n))
    return sorted(out)


def download_video(url: str, cookies_file: str | None = None) -> DownloadResult:
    """Download the original (non-re-encoded) video for `url` via yt-dlp."""
    workdir = _make_workdir()
    opts: dict = {
        # Best video+audio, merged to mp4. TikTok is already muxed (-> "best").
        "format": "bv*+ba/best",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(workdir, "%(title).180B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if cookies_file:
        opts["cookiefile"] = cookies_file

    # Browser impersonation is required for TikTok (avoids 403 / JS challenge)
    # and harmless elsewhere. Best-effort: skip silently if curl_cffi is absent.
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget

        opts["impersonate"] = ImpersonateTarget.from_str("chrome")
    except Exception:
        pass

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        files = _media_files(workdir)
        if not files:
            raise RuntimeError("Download finished but no video file was produced.")
        return DownloadResult(workdir, files, info.get("title") or "video")
    except BaseException:
        # Never leave a failed job's temp files (possibly large) behind.
        shutil.rmtree(workdir, ignore_errors=True)
        raise


def download_photos(url: str, cookies_file: str | None = None) -> DownloadResult:
    """Download a photo post / slideshow / carousel via gallery-dl.

    yt-dlp cannot fetch Facebook/Instagram photos, so we shell out to gallery-dl
    which handles image posts across TikTok/Instagram/Facebook and accepts the
    same Netscape cookies file.
    """
    workdir = _make_workdir()
    # Invoke as a module with the current interpreter so it's found whether
    # installed system-wide (container) or only in a venv (dev box).
    cmd = [sys.executable, "-m", "gallery_dl", "--dest", workdir, "--range", "1-60"]
    if cookies_file:
        cmd += ["--cookies", cookies_file]
    cmd.append(url)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        files = _media_files(workdir)
        if not files:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            detail = tail[-1] if tail else f"gallery-dl exited {proc.returncode}"
            raise RuntimeError(f"No photos downloaded — {detail}")
        # gallery-dl gives no clean post title via --dest; use the first file's
        # stem so the result is still recognisable.
        title = os.path.splitext(os.path.basename(files[0]))[0]
        return DownloadResult(workdir, files, title)
    except FileNotFoundError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise RuntimeError("gallery-dl is not installed in this image.") from exc
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
