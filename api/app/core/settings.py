"""Environment settings (connection info and secrets). Business tunables live in config.yaml."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# api/.env - found no matter which folder the API or pytest is started from.
# Real environment variables always win over values in this file.
_API_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_API_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str
    AS_OF_DATE: date | None = None
    LOG_LEVEL: str = "INFO"
    SCHEDULER_ENABLED: bool = True
    TEST_NEO4J_URI: str | None = None

    # Postgres source of truth (the "Host db" API). When SOURCE_API_URL is set, Neo4j becomes a
    # live copy of it and UI writes go through that API. Leave empty for the standalone
    # Neo4j-only mode (synthetic seed, used by the tests).
    SOURCE_API_URL: str | None = None
    SOURCE_API_KEY: str | None = None
    # Direct Postgres connection used only for LISTEN crm_changes (real-time). Without it the
    # app polls the API every SYNC_POLL_SECONDS instead.
    SOURCE_PG_DSN: str | None = None
    SYNC_POLL_SECONDS: float = 5.0
    SYNC_RECONCILE_SECONDS: float = 300.0
    SYNC_RECOMPUTE_DEBOUNCE_SECONDS: float = 3.0

    @field_validator(
        "AS_OF_DATE",
        "TEST_NEO4J_URI",
        "SOURCE_API_URL",
        "SOURCE_API_KEY",
        "SOURCE_PG_DSN",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        # `AS_OF_DATE=` in .env means "not set" (use the real date).
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def source_enabled(self) -> bool:
        return bool(self.SOURCE_API_URL and self.SOURCE_API_KEY)

    @field_validator("LOG_LEVEL")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        return level


@lru_cache
def get_settings() -> Settings:
    """Cached singleton. Tests call `get_settings.cache_clear()` after changing env vars."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment
