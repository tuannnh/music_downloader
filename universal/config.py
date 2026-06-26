from __future__ import annotations

import base64
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

    # --- Cookies (optional, per platform) ---------------------------------
    # Instagram & Facebook redirect anonymous requests to a login page, so a
    # logged-in session cookie is needed even for "public" profiles. TikTok
    # usually works without. Provide cookies in whichever form is convenient;
    # resolution order per platform (first hit wins): _COOKIES_B64 env → _COOKIES
    # env (raw Netscape text) → a "<platform>.txt" file in COOKIES_DIR.
    #
    # The *_B64 vars are base64 of a Netscape cookies.txt — a single line, so
    # they paste cleanly into Portainer / Infisical. Tip: base64 -w0 cookies.txt
    cookies_dir: str = "/cookies"
    instagram_cookies_b64: str = ""
    instagram_cookies: str = ""
    facebook_cookies_b64: str = ""
    facebook_cookies: str = ""
    tiktok_cookies_b64: str = ""
    tiktok_cookies: str = ""

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
        """Resolve a Netscape cookies file path for `platform`, or None.

        Order: <platform>_COOKIES_B64 → <platform>_COOKIES (raw) → a
        <platform>.txt file in COOKIES_DIR. Env-provided cookies are written to
        a private temp file so yt-dlp and gallery-dl can both consume them.
        """
        if not platform:
            return None

        content = ""
        b64 = getattr(self, f"{platform}_cookies_b64", "") or ""
        raw = getattr(self, f"{platform}_cookies", "") or ""
        if b64.strip():
            try:
                content = base64.b64decode(b64.strip()).decode("utf-8", "replace")
            except Exception:
                content = ""
        elif raw.strip():
            content = raw

        if content.strip():
            d = os.path.join(self.download_dir, "_cookies")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, f"{platform}.txt")
            if not content.endswith("\n"):
                content += "\n"
            with open(path, "w") as f:
                f.write(content)
            os.chmod(path, 0o600)
            return path

        # Fallback: a mounted cookies file.
        if self.cookies_dir:
            path = os.path.join(self.cookies_dir, f"{platform}.txt")
            if os.path.isfile(path):
                return path
        return None


settings = Settings()
