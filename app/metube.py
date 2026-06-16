"""Client for a MeTube instance (https://github.com/alexta69/metube).

MeTube is a yt-dlp web frontend. We drive it over HTTP:
  1. POST /add        -> enqueue an audio download
  2. GET  /history    -> poll until our item is "finished" (or "error")
  3. GET  /audio_download/<filename> -> fetch the finished file
  4. POST /delete     -> remove the finished item from MeTube (cleanup)

MeTube saves into its AUDIO_DOWNLOAD_DIR; we don't ask it to use subfolders
(`folder`) so we stay independent of its CUSTOM_DIRS config — organisation
into /music/<source>/ happens on the copytele side.
"""

from __future__ import annotations

import os
import time
from urllib.parse import quote, urlparse

import httpx

# Audio formats MeTube accepts for download_type "audio".
ALLOWED_FORMATS = {"m4a", "mp3", "opus", "wav", "flac"}


class MetubeError(Exception):
    pass


def source_for_url(url: str) -> str:
    """Map a URL to an upload subfolder name based on its host."""
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    if "youtube" in host or host.endswith("youtu.be") or host == "youtu.be":
        return "youtube"
    if "tiktok" in host:
        return "tiktok"
    return "other"


class MetubeClient:
    def __init__(self, base: str, timeout: float = 30.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    def add(self, url: str, audio_format: str) -> None:
        """Enqueue an audio download. Raises MetubeError on rejection."""
        payload = {
            "url": url,
            "quality": "best",
            "format": audio_format,
            "download_type": "audio",
            "auto_start": True,
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self._url("add"), json=payload)
        except httpx.HTTPError as exc:
            raise MetubeError(f"MeTube /add request failed: {exc}") from exc

        if resp.status_code >= 400:
            raise MetubeError(f"MeTube /add rejected ({resp.status_code}): {resp.text[:300]}")
        # On success MeTube returns {"status": "ok"}; otherwise an error message.
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if isinstance(data, dict) and data.get("status") == "error":
            raise MetubeError(f"MeTube error: {data.get('msg', 'unknown error')}")

    def _history(self) -> dict:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(self._url("history"))
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            raise MetubeError(f"MeTube /history request failed: {exc}") from exc

    def find(self, url: str, where: str) -> dict | None:
        """Return the download item matching `url` in 'done'/'queue'/'pending'."""
        for item in self._history().get(where, []):
            if isinstance(item, dict) and item.get("url") == url:
                return item
        return None

    def wait_until_done(self, url: str, timeout: float, poll: float) -> dict:
        """Poll until the item for `url` is finished. Returns the done item."""
        deadline = time.monotonic() + timeout
        while True:
            done = self.find(url, "done")
            if done is not None:
                if done.get("status") == "finished":
                    return done
                raise MetubeError(
                    f"MeTube download failed: {done.get('msg') or done.get('status')}"
                )
            # Not done yet — make sure it's still being worked on.
            still_active = self.find(url, "queue") or self.find(url, "pending")
            if still_active is None and time.monotonic() > deadline:
                raise MetubeError("Download not found in MeTube (did it accept the URL?).")
            if time.monotonic() > deadline:
                raise MetubeError(f"Timed out waiting for MeTube after {timeout:.0f}s.")
            time.sleep(poll)

    def download_finished_file(self, item: dict, dest_path: str) -> str:
        """Stream the finished audio file from MeTube to `dest_path`."""
        filename = item.get("filename")
        if not filename:
            raise MetubeError("MeTube reported no filename for the finished download.")
        file_url = self._url("audio_download/" + quote(filename, safe="/"))
        try:
            with httpx.Client(timeout=None, follow_redirects=True) as client:
                with client.stream("GET", file_url) as resp:
                    resp.raise_for_status()
                    with open(dest_path, "wb") as fh:
                        for chunk in resp.iter_bytes(1024 * 1024):
                            fh.write(chunk)
        except httpx.HTTPError as exc:
            raise MetubeError(f"Fetching file from MeTube failed: {exc}") from exc
        return os.path.basename(filename)

    def delete_done(self, url: str) -> None:
        """Best-effort removal of a finished item from MeTube's history."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                client.post(self._url("delete"), json={"ids": [url], "where": "done"})
        except httpx.HTTPError:
            pass  # cleanup is non-critical
