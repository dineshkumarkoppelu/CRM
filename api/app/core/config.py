"""Typed loader for api/config.yaml (business tunables).

The file is read once and cached. Every key is required, unknown keys are rejected, and
types are strict (e.g. `true` or `"0.5"` are not accepted as numbers). An invalid file raises
`ConfigError` with a message naming each bad key, which stops the API from starting.

The path comes from the `APP_CONFIG_PATH` environment variable, defaulting to `config.yaml`
next to the `app/` package (i.e. `api/config.yaml`).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
CONFIG_PATH_ENV = "APP_CONFIG_PATH"

WEIGHT_SUM_TOLERANCE = 1e-9

# Reusable constrained types
PositiveInt = Annotated[int, Field(ge=1)]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]  # [0, 1]
OpenUnitInterval = Annotated[float, Field(gt=0.0, lt=1.0)]  # (0, 1)


class ConfigError(RuntimeError):
    """config.yaml is missing, unreadable or invalid."""


class _Group(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class AnalyticsConfig(_Group):
    lookback_months: PositiveInt
    stalled_days: PositiveInt


class ExpertiseConfig(_Group):
    min_deals_per_domain: PositiveInt


class SimilarityConfig(_Group):
    similarity_tolerance: OpenUnitInterval
    similarity_min_domains: PositiveInt


class AssignmentConfig(_Group):
    weight_fit: UnitInterval
    weight_availability: UnitInterval
    peer_discount: UnitInterval
    capacity_default: PositiveInt
    max_candidates: PositiveInt

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> AssignmentConfig:
        total = self.weight_fit + self.weight_availability
        if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                "weight_fit + weight_availability must equal 1.0 "
                f"(got {self.weight_fit} + {self.weight_availability} = {total})"
            )
        return self


class ForecastConfig(_Group):
    forecast_commit_threshold: OpenUnitInterval
    forecast_best_case_threshold: OpenUnitInterval

    @model_validator(mode="after")
    def _commit_not_below_best_case(self) -> ForecastConfig:
        if self.forecast_commit_threshold < self.forecast_best_case_threshold:
            raise ValueError(
                "forecast_commit_threshold must be >= forecast_best_case_threshold "
                f"(got {self.forecast_commit_threshold} < {self.forecast_best_case_threshold})"
            )
        return self


class DomainsConfig(_Group):
    embedding_model: Annotated[str, Field(min_length=1, pattern=r"\S")]
    related_top_k: PositiveInt
    related_min_similarity: OpenUnitInterval
    related_discount: UnitInterval


class SchedulerConfig(_Group):
    recompute_cron: Annotated[str, Field(min_length=1, pattern=r"\S")]


class SeedConfig(_Group):
    seed_random_seed: PositiveInt


class AppConfig(_Group):
    """Mirrors the groups in config.yaml."""

    analytics: AnalyticsConfig
    expertise: ExpertiseConfig
    similarity: SimilarityConfig
    assignment: AssignmentConfig
    forecast: ForecastConfig
    domains: DomainsConfig
    scheduler: SchedulerConfig
    seed: SeedConfig


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        key = ".".join(str(part) for part in err["loc"]) or "<root>"
        message = err["msg"].removeprefix("Value error, ")
        # Group-level rules already quote the values in their message; don't dump the group.
        if err["type"] in {"missing", "extra_forbidden"} or isinstance(err.get("input"), dict):
            lines.append(f"  - {key}: {message}")
        else:
            lines.append(f"  - {key}: {message} (got {err.get('input')!r})")
    return "\n".join(lines)


def resolve_config_path() -> Path:
    override = os.environ.get(CONFIG_PATH_ENV, "").strip()
    return Path(override) if override else DEFAULT_CONFIG_PATH


def load_config(path: Path) -> AppConfig:
    """Read and validate a config file. Raises ConfigError with a readable message."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid config file {path}: expected a mapping of groups at the top")
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config file {path}:\n{_format_errors(exc)}") from exc


@lru_cache
def get_config() -> AppConfig:
    """Plain accessor for services (loaded once, cached)."""
    return load_config(resolve_config_path())


def config_dependency() -> AppConfig:
    """FastAPI dependency: `config: AppConfig = Depends(config_dependency)`."""
    return get_config()
