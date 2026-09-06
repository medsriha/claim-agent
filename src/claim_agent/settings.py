from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration, read from the environment or a local `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    json_logs: bool = False

    shipbob_base_url: str = "http://localhost:8080"
    shipbob_timeout_seconds: float = 10.0
    shipbob_max_attempts: int = Field(
        default=3,
        ge=1,
        description="Tries per ShipBob read before giving up, first attempt included (NFR-6).",
    )

    database_path: Path = Path("claim_agent.db")

    attachment_timeout_seconds: float = 20.0
    attachment_max_bytes: int = Field(
        default=20 * 1024 * 1024,
        gt=0,
        description="Largest attachment we will download. Bigger ones are unreadable (NFR-6).",
    )
    attachment_allowed_hosts: tuple[str, ...] = Field(
        default=("blob.core.windows.net", "localhost", "127.0.0.1"),
        description="Host suffixes an attachment may be fetched from. Anything else is refused "
        "without a request being made.",
    )
    attachment_cache_dir: Path | None = Path(".attachment-cache")
    """Where downloaded images are kept so the same one is never fetched twice."""

    anthropic_api_key: SecretStr | None = None
    model: str = "claude-opus-5"
    model_timeout_seconds: float = 120.0
    model_max_attempts: int = Field(
        default=2,
        ge=1,
        description="Tries per model call before failing toward the rep, first attempt "
        "included. Kept small because a run has its own step budget on top (FR-1.3, NFR-4).",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the settings for this process."""
    return Settings()
