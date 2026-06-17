from __future__ import annotations

import os
import shutil

from app.downloader import download_audio
from app.uploader import upload_to_copytele


def source_folder(extractor: str) -> str:
    """Map a yt-dlp extractor key to a destination subfolder.

    e.g. "youtube" / "youtube:tab" -> "youtube", "tiktok" -> "tiktok".
    Anything unrecognised goes into "other" so nothing lands loose at the root.
    """
    e = (extractor or "").lower()
    if "tiktok" in e:
        return "tiktok"
    if "youtube" in e:
        return "youtube"
    return "other"


def process(url: str) -> dict:
    """Blocking pipeline: download best audio → upload to copytele → clean up.

    Runs in a worker thread (see app.jobs). Raises on failure.
    """
    result = download_audio(url)
    workdir = os.path.dirname(result.path)
    folder = source_folder(result.extractor)
    try:
        copytele_url = upload_to_copytele(result.path, result.filename, subfolder=folder)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return {
        "title": result.title,
        "uploader": result.uploader,
        "source": result.extractor,
        "folder": folder,
        "filename": result.filename,
        "copytele_url": copytele_url,
    }
