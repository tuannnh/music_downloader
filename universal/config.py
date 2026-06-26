from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # Base URL of the copytele/copyparty folder files are written into. A
    # per-post subfolder "<platform>/<videos|photos>" is appended automatically,
    # giving e.g. source/tiktok/videos/ or source/instagram/photos/.
    # Must end with a slash, e.g. "http://10.1.1.99:11117/source/".
    copytele_upload_url: str = "https://copytele.zum.vn/source/"

    # Optional copyparty password. Empty for an open/no-auth volume.
    copytele_pw: str = ""

    # Where downloads are buffered before upload. Cleared after each job.
    download_dir: str = "/tmp/universal_downloader"

    # Directory holding OPTIONAL per-platform Netscape cookies files, named
    # "<platform>.txt" (instagram.txt, facebook.txt, tiktok.txt). Public
    # profiles/posts download without cookies; add a file only for a private /
    # login-walled item. Missing files are silently ignored.
    cookies_dir: str = "/cookies"

    # Keep at most this many finished jobs in memory for status lookups.
    max_jobs: int = 200

    # Server bind. Behind nginx-proxy-manager you typically expose this port.
    host: str = "0.0.0.0"
    port: int = 8081

    # Overwrite a file on copytele if the same name already exists.
    overwrite: bool = False

    @property
    def upload_base(self) -> str:
        u = self.copytele_upload_url
        return u if u.endswith("/") else u + "/"

    def cookies_for(self, platform: str) -> str | None:
        """Return the cookies file path for `platform` if it exists, else None."""
        if not platform or not self.cookies_dir:
            return None
        path = os.path.join(self.cookies_dir, f"{platform}.txt")
        return path if os.path.isfile(path) else None


settings = Settings()
