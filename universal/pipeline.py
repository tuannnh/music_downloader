from __future__ import annotations

import os
import shutil
from urllib.parse import urlparse

from universal.downloader import (
    IMAGE_EXTS,
    VIDEO_EXTS,
    download_photos,
    download_video,
)
from universal.uploader import upload_to_copytele

VIDEO, PHOTO, AUTO = "video", "photo", "auto"


def detect_platform(url: str) -> str:
    """Map a URL host to a platform folder name."""
    host = (urlparse(url).hostname or "").lower()
    if "tiktok" in host:
        return "tiktok"
    if "instagram" in host:
        return "instagram"
    if "facebook" in host or host in ("fb.watch", "fb.com") or host.endswith(".fb.com"):
        return "facebook"
    return "other"


def infer_type(url: str) -> str:
    """Best-effort media type from the URL path. Returns VIDEO, PHOTO or AUTO."""
    path = (urlparse(url).path or "").lower()
    if "/photo" in path or "photo.php" in path or "/media/set" in path:
        return PHOTO
    if any(seg in path for seg in ("/video", "/reel", "/watch", "/tv/", "/videos/")):
        return VIDEO
    return AUTO  # e.g. Instagram /p/<id> — could be either


def media_kind(path: str) -> str:
    """Classify a downloaded file for the UI preview."""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return "file"


def _download(url: str, media_type: str):
    """Resolve platform/type and download. Returns (platform, folder_type, result)."""
    from universal.config import settings

    platform = detect_platform(url)
    cookies = settings.cookies_for(platform)

    want = (media_type or AUTO).lower()
    if want == AUTO:
        want = infer_type(url)

    if want == PHOTO:
        return platform, "photos", download_photos(url, cookies)

    # VIDEO (explicit) or AUTO: try video, then fall back to photos — a TikTok
    # "video" link is often actually a photo slideshow. If both fail, surface the
    # original video error (it's the more relevant one for the user's choice).
    try:
        return platform, "videos", download_video(url, cookies)
    except Exception as video_err:
        try:
            return platform, "photos", download_photos(url, cookies)
        except Exception:
            raise video_err


def prepare(url: str, media_type: str = AUTO) -> dict:
    """Download media to a temp dir WITHOUT uploading. Caller commits later.

    Returns the platform/type, the temp workdir (kept), absolute file paths, and
    a UI-friendly `items` list. The workdir must be cleaned by commit() or by the
    job manager's TTL sweep.
    """
    platform, folder_type, result = _download(url, media_type)
    items = [
        {"index": i, "filename": os.path.basename(p), "kind": media_kind(p),
         "size": os.path.getsize(p)}
        for i, p in enumerate(result.files)
    ]
    return {
        "platform": platform,
        "media_type": folder_type,
        "title": result.title,
        "workdir": result.workdir,
        "files": result.files,
        "items": items,
    }


def commit(workdir: str, platform: str, media_type: str, files: list[str]) -> tuple[list, list]:
    """Upload the selected `files` to copytele, then delete the whole workdir."""
    subfolder = f"{platform}/{media_type}"
    urls: list[str] = []
    names: list[str] = []
    try:
        for path in files:
            name = os.path.basename(path)
            urls.append(upload_to_copytele(path, name, subfolder=subfolder))
            names.append(name)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return names, urls


def process(url: str, media_type: str = AUTO) -> dict:
    """One-shot: download → upload EVERYTHING → clean up (used by /api/save)."""
    p = prepare(url, media_type)
    names, urls = commit(p["workdir"], p["platform"], p["media_type"], p["files"])
    return {
        "platform": p["platform"],
        "media_type": p["media_type"],
        "title": p["title"],
        "count": len(urls),
        "files": names,
        "copytele_urls": urls,
        "folder": f"{p['platform']}/{p['media_type']}",
    }
