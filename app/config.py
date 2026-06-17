from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # Base URL of the copytele/copyparty folder that files are written into.
    # A per-source subfolder (youtube/ tiktok/ ...) is appended automatically.
    # Must end with a slash, e.g. "https://copytele.zum.vn/music/"
    copytele_upload_url: str = "https://copytele.zum.vn/music/"

    # Optional copyparty password. Empty for an open/no-auth volume.
    copytele_pw: str = ""

    # Where downloads are buffered before upload. Cleared after each job.
    download_dir: str = "/tmp/music_downloader"

    # Optional Netscape-format cookies.txt. Needed for some TikTok links
    # (and age/region-restricted YouTube). Empty = no cookies.
    cookies_file: str = ""

    # Keep at most this many finished jobs in memory for status lookups.
    max_jobs: int = 200

    # Server bind. Behind nginx-proxy-manager you typically expose this port.
    host: str = "0.0.0.0"
    port: int = 8080

    # Overwrite a file on copytele if the same name already exists.
    overwrite: bool = False

    @property
    def upload_base(self) -> str:
        return self.copytele_upload_url if self.copytele_upload_url.endswith("/") else self.copytele_upload_url + "/"


settings = Settings()
