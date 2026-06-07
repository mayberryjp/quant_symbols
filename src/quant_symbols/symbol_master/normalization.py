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


@dataclass(frozen=True)
class MassiveExchangeCandidate:
    """Exchange row candidate derived from a normalized Massive ticker record."""

    mic: str
    name: str
    provisional: bool = False


@dataclass(frozen=True)
class MassiveAliasCandidate:
    """Alias row candidate derived from a normalized Massive ticker record."""

    alias_type: str
    alias_value: str


KNOWN_MASSIVE_EXCHANGES = {
    "XNYS": "New York Stock Exchange",
    "XNAS": "Nasdaq Stock Market",
    "ARCX": "NYSE Arca",
    "BATS": "Cboe BZX Exchange",
    "OTCM": "OTC Markets",
    "XASE": "NYSE American",
    "XCHI": "Chicago Stock Exchange",
    "XPHL": "Nasdaq PHLX",
    "XBOS": "Nasdaq BX",
    "XCIS": "NYSE National",
    "IEXG": "IEX Exchange",
    "EDGA": "Cboe EDGA Exchange",
    "EDGX": "Cboe EDGX Exchange",
    "XNMS": "Nasdaq Global Select",
    "XNCM": "Nasdaq Capital Market",
    "XNGS": "Nasdaq Global Market",
}


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


def map_massive_exchange_candidate(candidate: MassiveTickerCandidate) -> MassiveExchangeCandidate | None:
    """Map primary exchange data from a ticker candidate to an exchange candidate."""

    if candidate.primary_exchange_code is None:
        return None
    mic = candidate.primary_exchange_code.strip().upper()
    if not mic:
        return None
    name = KNOWN_MASSIVE_EXCHANGES.get(mic)
    if name is None:
        return MassiveExchangeCandidate(mic=mic, name=f"Unmapped exchange {mic}", provisional=True)
    return MassiveExchangeCandidate(mic=mic, name=name)


def map_massive_alias_candidates(candidate: MassiveTickerCandidate) -> tuple[MassiveAliasCandidate, ...]:
    """Map lookup aliases from a Massive ticker candidate.

    Alias derivation is pure and intentionally limited to fields already present
    on the Slice 1 candidate. Empty optional identifiers are skipped.
    """

    aliases = (
        _alias("ticker", candidate.source_ticker),
        _alias("cik", candidate.cik),
        _alias("composite_figi", candidate.composite_figi),
        _alias("share_class_figi", candidate.share_class_figi),
    )
    return tuple(dict.fromkeys(alias for alias in aliases if alias is not None))


def _map_security_type(provider_type: str | None) -> tuple[str, str]:
    normalized = provider_type.upper() if provider_type is not None else None
    if normalized == "CS":
        return "equity", "common_stock"
    if normalized == "ETF":
        return "fund", "etf"
    return "unknown", "unknown"


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _alias(alias_type: str, value: str | None) -> MassiveAliasCandidate | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return MassiveAliasCandidate(alias_type=alias_type, alias_value=value.strip())


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
