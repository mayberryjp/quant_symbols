from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


VALID_DIRECTIONS = frozenset(("long", "short", "neutral"))
MAX_TAGS = 20
MAX_REASON_LENGTH = 2000
MAX_METADATA_KEYS = 100


class SignalValidationError(ValueError):
    """Raised when signal/watchlist input does not satisfy the public contract."""


@dataclass(frozen=True)
class SignalSubmission:
    source: str
    idempotency_key: str
    ticker: str
    signal_type: str
    reason: str
    market: str = "stocks"
    locale: str = "us"
    direction: str | None = None
    score: float | None = None
    confidence: float | None = None
    horizon: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ManualWatchlistRequest:
    ticker: str
    source: str
    reason: str
    market: str = "stocks"
    locale: str = "us"
    signal_type: str = "manual_watchlist"
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by: str | None = None


@dataclass(frozen=True)
class WatchlistPatch:
    active: bool | None = None
    status: str | None = None
    reason: str | None = None
    tags: tuple[str, ...] | None = None
    metadata: dict[str, Any] | None = None
    update_reason: str | None = None


@dataclass(frozen=True)
class SignalListParams:
    source: str | None = None
    ticker: str | None = None
    status: str | None = None
    signal_type: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class WatchlistListParams:
    active: bool | None = True
    source: str | None = None
    ticker: str | None = None
    market: str | None = None
    locale: str | None = None
    tag: str | None = None
    signal_type: str | None = None
    limit: int = 100
    offset: int = 0


def signal_submission_from_payload(payload: Any) -> SignalSubmission:
    if not isinstance(payload, dict):
        raise SignalValidationError("request body must be a JSON object")

    metadata = _metadata(payload.get("metadata"))
    reason = _string(payload.get("reason"), "reason", required=False)
    if reason is None:
        reason = _string(metadata.get("reason"), "metadata.reason", required=False)
    if reason is None:
        raise SignalValidationError("reason is required")

    submission = SignalSubmission(
        source=_string(payload.get("source"), "source"),
        idempotency_key=_string(payload.get("idempotency_key"), "idempotency_key"),
        ticker=_ticker(payload.get("ticker")),
        market=_string(payload.get("market", "stocks"), "market"),
        locale=_string(payload.get("locale", "us"), "locale"),
        signal_type=_string(payload.get("signal_type"), "signal_type"),
        direction=_direction(payload.get("direction")),
        score=_unit_interval(payload.get("score"), "score"),
        confidence=_unit_interval(payload.get("confidence"), "confidence"),
        horizon=_optional_string(payload.get("horizon"), "horizon"),
        reason=_bounded_reason(reason),
        tags=_tags(payload.get("tags")),
        metadata=metadata,
    )
    return submission


def manual_watchlist_from_payload(payload: Any) -> ManualWatchlistRequest:
    if not isinstance(payload, dict):
        raise SignalValidationError("request body must be a JSON object")
    return ManualWatchlistRequest(
        ticker=_ticker(payload.get("ticker")),
        source=_string(payload.get("source", "operator"), "source"),
        market=_string(payload.get("market", "stocks"), "market"),
        locale=_string(payload.get("locale", "us"), "locale"),
        signal_type=_string(payload.get("signal_type", "manual_watchlist"), "signal_type"),
        reason=_bounded_reason(_string(payload.get("reason"), "reason")),
        tags=_tags(payload.get("tags")),
        metadata=_metadata(payload.get("metadata")),
        created_by=_optional_string(payload.get("created_by"), "created_by"),
    )


def watchlist_patch_from_payload(payload: Any) -> WatchlistPatch:
    if not isinstance(payload, dict):
        raise SignalValidationError("request body must be a JSON object")
    active = payload.get("active")
    if active is not None and not isinstance(active, bool):
        raise SignalValidationError("active must be a boolean")
    status = _optional_string(payload.get("status"), "status")
    if status is not None and status not in {"active", "updated", "expired", "rejected", "superseded", "inactive"}:
        raise SignalValidationError("status is invalid")
    reason = _optional_string(payload.get("reason"), "reason")
    update_reason = _optional_string(payload.get("update_reason"), "update_reason")
    tags = None if "tags" not in payload else _tags(payload.get("tags"))
    metadata = None if "metadata" not in payload else _metadata(payload.get("metadata"))
    return WatchlistPatch(
        active=active,
        status=status,
        reason=_bounded_reason(reason) if reason is not None else None,
        tags=tags,
        metadata=metadata,
        update_reason=update_reason,
    )


def _string(value: Any, field_name: str, *, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise SignalValidationError(f"{field_name} is required")
        return None
    if not isinstance(value, str) or not value.strip():
        raise SignalValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field_name: str) -> str | None:
    return _string(value, field_name, required=False)


def _ticker(value: Any) -> str:
    ticker = _string(value, "ticker")
    assert ticker is not None
    return ticker.upper()


def _direction(value: Any) -> str | None:
    direction = _optional_string(value, "direction")
    if direction is None:
        return None
    if direction not in VALID_DIRECTIONS:
        raise SignalValidationError("direction must be long, short, or neutral")
    return direction


def _unit_interval(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SignalValidationError(f"{field_name} must be a number between 0 and 1")
    parsed = float(value)
    if parsed < 0 or parsed > 1:
        raise SignalValidationError(f"{field_name} must be between 0 and 1")
    return parsed


def _tags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SignalValidationError("tags must be an array of strings")
    if len(value) > MAX_TAGS:
        raise SignalValidationError(f"tags may contain at most {MAX_TAGS} values")
    tags = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SignalValidationError("tags must be non-empty strings")
        tags.append(item.strip())
    return tuple(tags)


def _metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SignalValidationError("metadata must be an object")
    if len(value) > MAX_METADATA_KEYS:
        raise SignalValidationError(f"metadata may contain at most {MAX_METADATA_KEYS} top-level keys")
    return dict(value)


def _bounded_reason(value: str) -> str:
    if len(value) > MAX_REASON_LENGTH:
        raise SignalValidationError(f"reason may contain at most {MAX_REASON_LENGTH} characters")
    return value
