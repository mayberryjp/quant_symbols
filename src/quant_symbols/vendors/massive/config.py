"""Configuration for the Massive/Polygon vendor client."""

from __future__ import annotations

from dataclasses import dataclass
import os

from quant_symbols.vendors.massive.errors import MassiveConfigError


DEFAULT_BASE_URL = "https://api.polygon.io"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_RETRY_COUNT = 3
DEFAULT_BACKOFF_SECONDS = 0.5
DEFAULT_BACKOFF_MULTIPLIER = 2.0


def _float_from_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise MassiveConfigError(f"{name} must be a number") from exc
    if parsed < 0:
        raise MassiveConfigError(f"{name} must be non-negative")
    return parsed


def _int_from_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise MassiveConfigError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise MassiveConfigError(f"{name} must be non-negative")
    return parsed


@dataclass(frozen=True)
class MassiveConfig:
    """Runtime settings for Massive/Polygon HTTP access.

    The API key is intentionally excluded from repr output so accidental logs do
    not expose credentials.
    """

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    retry_count: int = DEFAULT_RETRY_COUNT
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER

    def __post_init__(self) -> None:
        if not self.api_key:
            raise MassiveConfigError("MASSIVE_API_KEY is required")
        if not self.base_url:
            raise MassiveConfigError("MASSIVE_BASE_URL is required")
        if self.timeout_seconds <= 0:
            raise MassiveConfigError("MASSIVE_TIMEOUT_SECONDS must be greater than zero")
        if self.retry_count < 0:
            raise MassiveConfigError("MASSIVE_RETRY_COUNT must be non-negative")
        if self.backoff_seconds < 0:
            raise MassiveConfigError("MASSIVE_BACKOFF_SECONDS must be non-negative")
        if self.backoff_multiplier < 1:
            raise MassiveConfigError("MASSIVE_BACKOFF_MULTIPLIER must be at least 1")

    def __repr__(self) -> str:
        return (
            "MassiveConfig("
            "api_key=<redacted>, "
            f"base_url={self.base_url!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"retry_count={self.retry_count!r}, "
            f"backoff_seconds={self.backoff_seconds!r}, "
            f"backoff_multiplier={self.backoff_multiplier!r})"
        )

    @classmethod
    def from_env(cls) -> "MassiveConfig":
        """Build config from environment variables."""

        return cls(
            api_key=os.environ.get("MASSIVE_API_KEY", ""),
            base_url=os.environ.get("MASSIVE_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            timeout_seconds=_float_from_env("MASSIVE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
            retry_count=_int_from_env("MASSIVE_RETRY_COUNT", DEFAULT_RETRY_COUNT),
            backoff_seconds=_float_from_env("MASSIVE_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS),
            backoff_multiplier=_float_from_env(
                "MASSIVE_BACKOFF_MULTIPLIER",
                DEFAULT_BACKOFF_MULTIPLIER,
            ),
        )
