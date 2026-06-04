import os
from pydantic_settings import BaseSettings
from pydantic import Field


def _default_db_path() -> str:
    """Railway volume bo'lsa /data, aks holda joriy papkada."""
    path = os.getenv("DATABASE_PATH", "")
    if path:
        return path
    # /data papkasi mavjud bo'lsa (Railway volume)
    if os.path.isdir("/data"):
        return "/data/mafia.db"
    return "mafia.db"


class Settings(BaseSettings):
    BOT_TOKEN: str
    DATABASE_PATH: str = _default_db_path()

    # Bot egasining Telegram ID si (statistika uchun)
    # Telegram da @userinfobot ga /start yozib ID ni bilib oling
    OWNER_ID: int = 0

    DEFAULT_DAY_TIME: int = Field(default=300, ge=30, le=3600)
    DEFAULT_VOTE_TIME: int = Field(default=120, ge=30, le=600)
    DEFAULT_NIGHT_TIME: int = Field(default=60, ge=30, le=300)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
