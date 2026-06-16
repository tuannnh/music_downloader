from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Secret bearer token the web UI / iOS Shortcut must send.
    api_token: str

    # Public URL of THIS app, baked into the generated iOS shortcut, e.g.
    # "https://music.zum.vn". If blank, derived from the incoming request.
    public_base_url: str = ""

    # MeTube instance that performs the actual download.
    metube_base: str = "https://metube.zum.vn"
    # Max seconds to wait for MeTube to finish a download.
    metube_timeout_sec: int = 600
    # How often to poll MeTube's /history while waiting.
    metube_poll_interval_sec: float = 2.0

    # Copytele (copyparty) target.
    copytele_base: str = "https://copytele.zum.vn"
    # Base folder/volume to upload into. Must start and end with "/".
    # A per-source subfolder (youtube/ or tiktok/) is appended automatically.
    copytele_upload_path: str = "/music/"
    # Copyparty upload password, sent as the "PW" header. Leave blank if the
    # upload volume requires no password.
    copytele_pw: str = ""

    def normalized_upload_path(self) -> str:
        path = self.copytele_upload_path
        if not path.startswith("/"):
            path = "/" + path
        if not path.endswith("/"):
            path = path + "/"
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
