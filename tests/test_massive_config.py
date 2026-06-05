from __future__ import annotations

import pytest

from quant_symbols.vendors.massive.config import (
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_BASE_URL,
    DEFAULT_RETRY_COUNT,
    DEFAULT_TIMEOUT_SECONDS,
    MassiveConfig,
)
from quant_symbols.vendors.massive.errors import MassiveConfigError


MASSIVE_ENV_NAMES = (
    "MASSIVE_API_KEY",
    "MASSIVE_BASE_URL",
    "MASSIVE_TIMEOUT_SECONDS",
    "MASSIVE_RETRY_COUNT",
    "MASSIVE_BACKOFF_SECONDS",
    "MASSIVE_BACKOFF_MULTIPLIER",
)


def clear_massive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in MASSIVE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_used_without_optional_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_massive_env(monkeypatch)

    config = MassiveConfig.from_env()

    assert config.api_key == ""
    assert config.base_url == DEFAULT_BASE_URL
    assert config.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert config.retry_count == DEFAULT_RETRY_COUNT
    assert config.backoff_seconds == DEFAULT_BACKOFF_SECONDS
    assert config.backoff_multiplier == DEFAULT_BACKOFF_MULTIPLIER


def test_api_key_is_read_when_live_config_is_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_massive_env(monkeypatch)
    monkeypatch.setenv("MASSIVE_API_KEY", "live-test-secret")

    config = MassiveConfig.from_env(require_api_key=True)

    assert config.api_key == "live-test-secret"


def test_missing_api_key_is_allowed_for_non_live_config(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_massive_env(monkeypatch)

    config = MassiveConfig.from_env(require_api_key=False)

    assert config.api_key == ""


def test_missing_api_key_raises_for_live_config(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_massive_env(monkeypatch)

    with pytest.raises(MassiveConfigError) as exc_info:
        MassiveConfig.from_env(require_api_key=True)

    assert "MASSIVE_API_KEY is required" in str(exc_info.value)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("MASSIVE_TIMEOUT_SECONDS", "not-a-number", "MASSIVE_TIMEOUT_SECONDS must be a number"),
        ("MASSIVE_TIMEOUT_SECONDS", "0", "MASSIVE_TIMEOUT_SECONDS must be greater than zero"),
        ("MASSIVE_TIMEOUT_SECONDS", "-1", "MASSIVE_TIMEOUT_SECONDS must be non-negative"),
        ("MASSIVE_RETRY_COUNT", "1.5", "MASSIVE_RETRY_COUNT must be an integer"),
        ("MASSIVE_RETRY_COUNT", "-1", "MASSIVE_RETRY_COUNT must be non-negative"),
        ("MASSIVE_BACKOFF_SECONDS", "oops", "MASSIVE_BACKOFF_SECONDS must be a number"),
        ("MASSIVE_BACKOFF_SECONDS", "-0.1", "MASSIVE_BACKOFF_SECONDS must be non-negative"),
        ("MASSIVE_BACKOFF_MULTIPLIER", "0.99", "MASSIVE_BACKOFF_MULTIPLIER must be at least 1"),
    ],
)
def test_invalid_numeric_env_vars_raise_clear_errors(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    clear_massive_env(monkeypatch)
    monkeypatch.setenv("MASSIVE_API_KEY", "live-test-secret")
    monkeypatch.setenv(name, value)

    with pytest.raises(MassiveConfigError) as exc_info:
        MassiveConfig.from_env(require_api_key=True)

    assert str(exc_info.value) == message


def test_repr_redacts_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_massive_env(monkeypatch)
    monkeypatch.setenv("MASSIVE_API_KEY", "live-test-secret")

    config = MassiveConfig.from_env(require_api_key=True)

    assert "live-test-secret" not in repr(config)
    assert "api_key=<redacted>" in repr(config)


def test_config_error_text_does_not_include_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_massive_env(monkeypatch)
    monkeypatch.setenv("MASSIVE_API_KEY", "live-test-secret")
    monkeypatch.setenv("MASSIVE_BACKOFF_MULTIPLIER", "0")

    with pytest.raises(MassiveConfigError) as exc_info:
        MassiveConfig.from_env(require_api_key=True)

    assert "live-test-secret" not in str(exc_info.value)
