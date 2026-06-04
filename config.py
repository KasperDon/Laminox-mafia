import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    BOT_TOKEN: str

    # Railway Volume /data ga mount qilinadi, local da oddiy fayl
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "/data/mafia.db"
                                    if os.path.isdir("/data") else "mafia.db")

    DEFAULT_DAY_TIME: int = Field(default=300, ge=30, le=3600)
    DEFAULT_VOTE_TIME: int = Field(default=120, ge=30, le=600)
    DEFAULT_NIGHT_TIME: int = Field(default=60, ge=30, le=300)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
