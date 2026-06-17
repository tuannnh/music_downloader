from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


@dataclass
class DownloadResult:
    path: str          # absolute path to the produced audio file
    filename: str      # basename used for upload
    title: str
    uploader: str
    extractor: str     # "youtube", "tiktok", ...


def _build_opts(workdir: str) -> dict:
    """yt-dlp options tuned for best-quality audio with no lossy re-encode.

    We grab the best available audio stream and only *extract*/remux it to a
    sane container (preferredcodec="best" tells ffmpeg to copy the codec when
    it can, so YouTube's opus/m4a and TikTok's original sound stay lossless).
    """
    from app.config import settings

    opts: dict = {
        # Prefer a real audio-only stream (YouTube). For TikTok there is none,
        # and its HEVC/bytevc1 formats LIE — they advertise aac but download as
        # video-only (no audio), so we must prefer h264, which is genuinely
        # muxed with audio. Order: audio-only → h264 → anything claiming audio →
        # anything.
        "format": "bestaudio/best[vcodec^=h264]/best[acodec!=none]/best",
        "outtmpl": os.path.join(workdir, "%(title).200B [%(id)s].%(ext)s"),
        "restrictfilenames": False,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "writethumbnail": True,
        "postprocessors": [
            # Extract audio, copying the source codec when possible (lossless).
            {"key": "FFmpegExtractAudio", "preferredcodec": "best"},
            # Write title/artist/etc. into the file tags.
            {"key": "FFmpegMetadata", "add_metadata": True},
            # Embed the cover art (album art in players).
            {"key": "EmbedThumbnail", "already_have_thumbnail": False},
        ],
    }

    # Cookies help with TikTok links that require a session, and with
    # age/region-restricted YouTube. Resolve a relative path against the
    # project root so it isn't silently ignored when cwd differs.
    if settings.cookies_file:
        cf = settings.cookies_file
        if not os.path.isabs(cf):
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cf = os.path.join(project_root, cf)
        if os.path.isfile(cf):
            opts["cookiefile"] = cf

    # Force browser impersonation on every request (needs curl_cffi). TikTok
    # 403s / JS-challenges plain HTTP clients; impersonating Chrome avoids that.
    # Harmless for YouTube. Best-effort: skip silently if unavailable.
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget

        opts["impersonate"] = ImpersonateTarget.from_str("chrome")
    except Exception:
        pass

    return opts


def download_audio(url: str) -> DownloadResult:
    """Download the best audio for `url` into a fresh per-job directory.

    Raises yt_dlp.utils.DownloadError (or other yt-dlp errors) on failure.
    """
    from app.config import settings

    os.makedirs(settings.download_dir, exist_ok=True)
    workdir = os.path.join(settings.download_dir, uuid.uuid4().hex)
    os.makedirs(workdir, exist_ok=True)

    def _audio_files() -> list[str]:
        audio_exts = {".m4a", ".mp3", ".opus", ".ogg", ".webm", ".aac", ".flac", ".wav"}
        return [
            os.path.join(workdir, f)
            for f in os.listdir(workdir)
            if os.path.splitext(f)[1].lower() in audio_exts
        ]

    try:
        return _run(url, workdir, _audio_files)
    except BaseException:
        # Never leave a failed job's temp files (incl. multi-hundred-MB videos)
        # lying around — only the caller keeps the dir, and only on success.
        shutil.rmtree(workdir, ignore_errors=True)
        raise


def _run(url: str, workdir: str, _audio_files) -> DownloadResult:
    with YoutubeDL(_build_opts(workdir)) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except DownloadError as exc:
            # The audio is extracted *before* the cover-art/metadata steps, so a
            # post-processing failure (e.g. thumbnail embed) shouldn't lose the
            # file. If the audio is already on disk, keep it; otherwise figure
            # out why nothing was produced.
            if _audio_files():
                info = ydl.extract_info(url, download=False)
            elif "audio codec" in str(exc):
                # The only stream available had no audio track (e.g. a TikTok
                # photo slideshow, or a video-only upload).
                raise RuntimeError("This link has no audio track to extract.") from exc
            else:
                raise

    candidates = _audio_files()
    if not candidates:
        raise RuntimeError("Download finished but no audio file was produced.")

    # Pick the largest file (the real audio, not a leftover thumbnail/fragment).
    path = max(candidates, key=os.path.getsize)

    return DownloadResult(
        path=path,
        filename=os.path.basename(path),
        title=info.get("title") or "unknown",
        uploader=info.get("uploader") or info.get("channel") or "",
        extractor=info.get("extractor_key", info.get("extractor", "")).lower(),
    )
