"""Upload a file to copytele (copyparty) via an authenticated HTTP PUT."""

from __future__ import annotations

import os
from urllib.parse import quote

import httpx


class UploadError(Exception):
    pass


def upload_file(
    local_path: str,
    filename: str,
    base: str,
    upload_path: str,
    password: str,
    timeout: float = 300.0,
) -> str:
    """PUT `local_path` to copyparty at `{base}{upload_path}{filename}`.

    Returns the resulting public URL on success.
    """
    base = base.rstrip("/")
    # upload_path is already normalized to start+end with "/".
    dest_url = f"{base}{upload_path}{quote(filename)}"

    headers = {"Content-Type": "application/octet-stream"}
    if password:
        # Only sent when the upload volume is password-protected.
        headers["PW"] = password

    def file_reader():
        with open(local_path, "rb") as fh:
            while chunk := fh.read(1024 * 1024):
                yield chunk

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.put(
                dest_url,
                content=file_reader(),
                headers={**headers, "Content-Length": str(os.path.getsize(local_path))},
            )
    except httpx.HTTPError as exc:
        raise UploadError(f"Upload request failed: {exc}") from exc

    if resp.status_code >= 400:
        raise UploadError(
            f"Copytele rejected upload ({resp.status_code}): {resp.text[:500]}"
        )

    return dest_url
