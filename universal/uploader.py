from __future__ import annotations

from urllib.parse import quote

import httpx


def upload_to_copytele(local_path: str, filename: str, subfolder: str = "") -> str:
    """PUT `local_path` onto the copytele/copyparty volume.

    copyparty accepts a plain HTTP PUT where the URL path becomes the stored
    filename; intermediate folders (e.g. tiktok/videos/) are created
    automatically. Returns the resulting file URL.
    """
    from universal.config import settings

    prefix = ""
    if subfolder:
        # Quote each path segment but keep the slashes between them.
        prefix = "/".join(quote(seg) for seg in subfolder.strip("/").split("/")) + "/"
    target = settings.upload_base + prefix + quote(filename)
    params = {}
    if settings.copytele_pw:
        params["pw"] = settings.copytele_pw
    if settings.overwrite:
        # copyparty: don't auto-rename on collision, replace instead.
        params["replace"] = "1"

    with open(local_path, "rb") as f:
        resp = httpx.put(target, params=params, content=f, timeout=300.0)

    # copyparty returns 201/200 on a successful PUT.
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"copytele upload failed: HTTP {resp.status_code} — {resp.text[:300]}"
        )

    return target
