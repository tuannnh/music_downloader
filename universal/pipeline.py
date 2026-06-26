from __future__ import annotations

import os
import shutil
from urllib.parse import urlparse

from universal.downloader import download_photos, download_video
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


def process(url: str, media_type: str = AUTO) -> dict:
    """Blocking pipeline: download → upload every file to copytele → clean up.

    Runs in a worker thread (see universal.jobs). Raises on failure.
    """
    from universal.config import settings

    platform = detect_platform(url)
    cookies = settings.cookies_for(platform)

    want = (media_type or AUTO).lower()
    if want == AUTO:
        want = infer_type(url)

    if want == VIDEO:
        result, folder_type = download_video(url, cookies), "videos"
    elif want == PHOTO:
        result, folder_type = download_photos(url, cookies), "photos"
    else:
        # Ambiguous: try video first, fall back to photos.
        try:
            result, folder_type = download_video(url, cookies), "videos"
        except Exception:
            result, folder_type = download_photos(url, cookies), "photos"

    subfolder = f"{platform}/{folder_type}"
    urls: list[str] = []
    names: list[str] = []
    try:
        for path in result.files:
            name = os.path.basename(path)
            urls.append(upload_to_copytele(path, name, subfolder=subfolder))
            names.append(name)
    finally:
        shutil.rmtree(result.workdir, ignore_errors=True)

    return {
        "platform": platform,
        "media_type": folder_type,
        "title": result.title,
        "count": len(urls),
        "files": names,
        "copytele_urls": urls,
        "folder": subfolder,
    }
