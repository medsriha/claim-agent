"""Runtime settings: environment, credentials, and outbound endpoints.

Claim policy values do not belong here — they live in `claim_agent.policy`
(FR-0.7, NFR-7). This module is about *how the process runs*, not *how claims
are judged*.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
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

    # ShipBob mock API. Defaults to a local stub so the service boots without
    # credentials; unreachable upstreams surface as handled errors (NFR-6).
    shipbob_base_url: str = "http://localhost:8080"
    shipbob_timeout_seconds: float = 10.0

    # LLM access. Absent key is a handled state, not a crash at import time.
    anthropic_api_key: SecretStr | None = None
    model: str = "claude-opus-5"


@lru_cache
def get_settings() -> Settings:
    """Return the settings for this process.

    Cached, so the environment is read once at startup instead of on every request,
    and every caller sees the same values.
    """
    return Settings()
