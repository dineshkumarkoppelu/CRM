"""Unit tests for app.core.config (no database)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core import config as config_module
from app.core.config import DEFAULT_CONFIG_PATH, AppConfig, ConfigError, load_config

# Defaults from domain-rules.md section 0.
EXPECTED_DEFAULTS: dict[str, dict[str, Any]] = {
    "analytics": {"lookback_months": 12, "stalled_days": 21},
    "expertise": {"min_deals_per_domain": 3},
    "similarity": {"similarity_tolerance": 0.10, "similarity_min_domains": 3},
    "assignment": {
        "weight_fit": 0.7,
        "weight_availability": 0.3,
        "peer_discount": 0.8,
        "capacity_default": 8,
        "max_candidates": 5,
    },
    "forecast": {"forecast_commit_threshold": 0.70, "forecast_best_case_threshold": 0.30},
    "domains": {
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "related_top_k": 3,
        "related_min_similarity": 0.65,
        "related_discount": 0.7,
    },
    "scheduler": {"recompute_cron": "0 2 * * *"},
    "seed": {"seed_random_seed": 42},
}


@pytest.fixture
def base() -> dict[str, dict[str, Any]]:
    """A deep copy of the shipped config.yaml as a plain dict, ready to be broken."""
    return yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _load_broken(tmp_path: Path, data: Any) -> str:
    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, data))
    return str(info.value)


# ---- valid config ----


def test_shipped_config_loads_with_documented_defaults() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)
    assert isinstance(config, AppConfig)
    assert config.model_dump() == EXPECTED_DEFAULTS


def test_shipped_config_has_exactly_the_documented_keys(base: dict[str, Any]) -> None:
    assert {group: set(keys) for group, keys in base.items()} == {
        group: set(keys) for group, keys in EXPECTED_DEFAULTS.items()
    }


def test_int_is_accepted_for_float_fields(tmp_path: Path, base: dict[str, Any]) -> None:
    base["assignment"]["weight_fit"] = 1
    base["assignment"]["weight_availability"] = 0
    config = load_config(_write(tmp_path, base))
    assert config.assignment.weight_fit == 1.0


def test_weights_sum_within_tolerance(tmp_path: Path, base: dict[str, Any]) -> None:
    base["assignment"]["weight_fit"] = 0.1 + 0.2  # 0.30000000000000004
    base["assignment"]["weight_availability"] = 0.7
    load_config(_write(tmp_path, base))  # no error


def test_commit_equal_to_best_case_is_allowed(tmp_path: Path, base: dict[str, Any]) -> None:
    base["forecast"]["forecast_commit_threshold"] = 0.5
    base["forecast"]["forecast_best_case_threshold"] = 0.5
    load_config(_write(tmp_path, base))  # no error


# ---- each validation rule rejects a bad value and names the key ----


@pytest.mark.parametrize(
    ("group", "key", "value", "expected_in_message"),
    [
        # weights must sum to 1.0
        ("assignment", "weight_availability", 0.4, "weight_fit + weight_availability"),
        # weights in [0, 1]
        ("assignment", "weight_fit", 1.2, "assignment.weight_fit"),
        ("assignment", "peer_discount", -0.1, "assignment.peer_discount"),
        # tolerance in (0, 1)
        ("similarity", "similarity_tolerance", 0, "similarity.similarity_tolerance"),
        ("similarity", "similarity_tolerance", 1.0, "similarity.similarity_tolerance"),
        # integers >= 1
        ("analytics", "lookback_months", 0, "analytics.lookback_months"),
        ("expertise", "min_deals_per_domain", -3, "expertise.min_deals_per_domain"),
        ("assignment", "max_candidates", 0, "assignment.max_candidates"),
        ("seed", "seed_random_seed", 0, "seed.seed_random_seed"),
        # thresholds in (0, 1) and commit >= best case
        ("forecast", "forecast_commit_threshold", 0.2, "forecast_commit_threshold must be >="),
        ("forecast", "forecast_best_case_threshold", 0, "forecast.forecast_best_case_threshold"),
        ("forecast", "forecast_commit_threshold", 1.0, "forecast.forecast_commit_threshold"),
        # cron string non-empty
        ("scheduler", "recompute_cron", "", "scheduler.recompute_cron"),
        ("scheduler", "recompute_cron", "   ", "scheduler.recompute_cron"),
        # strict types
        ("analytics", "stalled_days", True, "analytics.stalled_days"),
        ("analytics", "stalled_days", 21.0, "analytics.stalled_days"),
        ("similarity", "similarity_tolerance", "0.1", "similarity.similarity_tolerance"),
    ],
)
def test_invalid_value_is_rejected(
    tmp_path: Path,
    base: dict[str, Any],
    group: str,
    key: str,
    value: Any,
    expected_in_message: str,
) -> None:
    broken = copy.deepcopy(base)
    broken[group][key] = value
    message = _load_broken(tmp_path, broken)
    assert expected_in_message in message


def test_missing_key_is_rejected(tmp_path: Path, base: dict[str, Any]) -> None:
    del base["assignment"]["peer_discount"]
    assert "assignment.peer_discount: Field required" in _load_broken(tmp_path, base)


def test_missing_group_is_rejected(tmp_path: Path, base: dict[str, Any]) -> None:
    del base["seed"]
    assert "seed: Field required" in _load_broken(tmp_path, base)


def test_unknown_key_is_rejected(tmp_path: Path, base: dict[str, Any]) -> None:
    base["similarity"]["similarity_tolerence"] = 0.1  # typo
    assert "similarity.similarity_tolerence" in _load_broken(tmp_path, base)


def test_non_mapping_file_is_rejected(tmp_path: Path) -> None:
    assert "expected a mapping" in _load_broken(tmp_path, ["not", "a", "mapping"])


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("analytics: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="Cannot read config file"):
        load_config(path)


# ---- path resolution and caching ----


def test_app_config_path_env_overrides_default(
    tmp_path: Path, base: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    base["seed"]["seed_random_seed"] = 7
    monkeypatch.setenv("APP_CONFIG_PATH", str(_write(tmp_path, base)))
    config_module.get_config.cache_clear()
    try:
        assert config_module.get_config().seed.seed_random_seed == 7
    finally:
        config_module.get_config.cache_clear()


def test_default_path_is_next_to_app_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_CONFIG_PATH", raising=False)
    assert config_module.resolve_config_path() == DEFAULT_CONFIG_PATH
    assert DEFAULT_CONFIG_PATH.parent.joinpath("app").is_dir()


def test_config_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_CONFIG_PATH", raising=False)
    config_module.get_config.cache_clear()
    assert config_module.get_config() is config_module.get_config()
