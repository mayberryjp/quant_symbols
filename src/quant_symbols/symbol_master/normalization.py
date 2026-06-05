"""Pure raw Massive/Polygon payload normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class MassiveTickerCandidate:
    """Normalized candidate fields derived from one raw Massive ticker record."""

    source_ticker: str | None
    canonical_ticker: str | None
    name: str | None
    market: str | None
    locale: str | None
    primary_exchange_code: str | None
    currency_name: str | None
    asset_type: str
    security_type: str
    provider_type: str | None
    active: bool | None
    cik: str | None
    composite_figi: str | None
    share_class_figi: str | None
    last_updated_utc: datetime | None
    delisted_utc: datetime | None
    raw_record: dict[str, Any]


def map_massive_ticker_raw_record(raw_record: dict[str, Any]) -> MassiveTickerCandidate:
    """Map one raw Massive ticker dictionary to a normalized candidate.

    The mapper is intentionally pure: it does not call HTTP services, touch the
    database, or mutate the provider dictionary passed by the caller.
    """

    source_ticker = _optional_str(raw_record.get("ticker"))
    asset_type, security_type = _map_security_type(_optional_str(raw_record.get("type")))
    return MassiveTickerCandidate(
        source_ticker=source_ticker,
        canonical_ticker=source_ticker.upper() if source_ticker is not None else None,
        name=_optional_str(raw_record.get("name")),
        market=_optional_str(raw_record.get("market")),
        locale=_optional_str(raw_record.get("locale")),
        primary_exchange_code=_optional_str(raw_record.get("primary_exchange")),
        currency_name=_optional_str(raw_record.get("currency_name")),
        asset_type=asset_type,
        security_type=security_type,
        provider_type=_optional_str(raw_record.get("type")),
        active=raw_record.get("active") if isinstance(raw_record.get("active"), bool) else None,
        cik=_optional_str(raw_record.get("cik")),
        composite_figi=_optional_str(raw_record.get("composite_figi")),
        share_class_figi=_optional_str(raw_record.get("share_class_figi")),
        last_updated_utc=_parse_timestamp(_optional_str(raw_record.get("last_updated_utc"))),
        delisted_utc=_parse_timestamp(_optional_str(raw_record.get("delisted_utc"))),
        raw_record=dict(raw_record),
    )


def _map_security_type(provider_type: str | None) -> tuple[str, str]:
    normalized = provider_type.upper() if provider_type is not None else None
    if normalized == "CS":
        return "equity", "common_stock"
    if normalized == "ETF":
        return "fund", "etf"
    return "unknown", "unknown"


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
