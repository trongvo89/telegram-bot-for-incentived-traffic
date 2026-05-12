from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = Field(..., alias="BOT_TOKEN")
    google_application_credentials: Path | None = Field(
        default=None, alias="GOOGLE_APPLICATION_CREDENTIALS"
    )
    control_sheet_id: str = Field(default="", alias="CONTROL_SHEET_ID")
    super_admin_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list, alias="SUPER_ADMIN_IDS"
    )
    sqlite_path: Path = Field(default=Path("/data/app.db"), alias="SQLITE_PATH")
    campaign_cache_ttl_sec: int = Field(default=300, alias="CAMPAIGN_CACHE_TTL_SEC")
    tz: str = Field(default="Asia/Ho_Chi_Minh", alias="TZ")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("super_admin_ids", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        return v


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
