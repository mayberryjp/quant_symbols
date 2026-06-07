"""Pure Massive/Polygon ticker-to-symbol mapper."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from quant_symbols.vendors.massive.models import TickerReference


@dataclass(frozen=True)
class ExchangeCandidate:
    mic: str
    name: str
    provisional: bool = False


@dataclass(frozen=True)
class AliasCandidate:
    alias_type: str
    alias_value: str


@dataclass(frozen=True)
class SymbolCandidate:
    canonical_ticker: str
    source_ticker: str
    name: str | None
    market: str
    locale: str
    currency: str
    primary_exchange: ExchangeCandidate | None
    asset_class: str
    security_type: str
    source_security_type: str | None
    active: bool
    cik: str | None
    composite_figi: str | None
    share_class_figi: str | None
    delisted_at: datetime | None
    aliases: tuple[AliasCandidate, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class MapperResult:
    candidate: SymbolCandidate | None
    warnings: tuple[str, ...] = ()
    skipped_reason: str | None = None


KNOWN_EXCHANGES = {
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


def map_ticker_reference(reference: TickerReference) -> MapperResult:
    """Map one Massive ticker reference into the symbol-master domain."""

    warnings: list[str] = []
    canonical_ticker = reference.ticker.strip().upper()
    if not canonical_ticker:
        return MapperResult(candidate=None, skipped_reason="missing ticker")

    market = _normalized_text(reference.market, default="stocks")
    locale = _normalized_text(reference.locale, default="us")
    currency = _currency_code(reference.currency_name, warnings)
    asset_class, security_type = _classification(reference.type, warnings)
    exchange = _exchange(reference.primary_exchange, warnings)
    delisted_at = _parse_provider_datetime(reference.delisted_utc, "delisted_utc", warnings)

    aliases = _aliases(reference, canonical_ticker)
    candidate = SymbolCandidate(
        canonical_ticker=canonical_ticker,
        source_ticker=reference.ticker,
        name=reference.name.strip() if isinstance(reference.name, str) and reference.name.strip() else None,
        market=market,
        locale=locale,
        currency=currency,
        primary_exchange=exchange,
        asset_class=asset_class,
        security_type=security_type,
        source_security_type=reference.type,
        active=reference.active if reference.active is not None else True,
        cik=reference.cik,
        composite_figi=reference.composite_figi,
        share_class_figi=reference.share_class_figi,
        delisted_at=delisted_at,
        aliases=aliases,
        raw=reference.raw,
    )
    return MapperResult(candidate=candidate, warnings=tuple(warnings))


def _normalized_text(value: str | None, *, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return default


def _currency_code(value: str | None, warnings: list[str]) -> str:
    if isinstance(value, str) and len(value.strip()) == 3:
        return value.strip().upper()
    if value:
        warnings.append(f"unsupported currency value preserved in raw payload: {value}")
    return "USD"


def _classification(provider_type: str | None, warnings: list[str]) -> tuple[str, str]:
    normalized = provider_type.strip().upper() if isinstance(provider_type, str) else ""
    if normalized == "ETF":
        return "fund", "etf"
    if normalized == "CS":
        return "equity", "common_stock"
    if normalized in {"ADRC", "ADRP", "ADR"}:
        return "equity", "adr"
    if normalized in {"REIT"}:
        return "equity", "reit"
    if normalized in {"WARRANT", "RIGHT", "WRT"}:
        return "equity", "warrant"
    if normalized in {"UNIT"}:
        return "equity", "unit"
    if normalized in {"PFD"}:
        return "equity", "preferred"
    if normalized in {"FUND", "CEF", "OEF"}:
        return "fund", "fund"
    if normalized in {"ETS", "ETN", "ETV"}:
        return "fund", "etn"
    if normalized in {"SP", "STRUCT"}:
        return "structured", "structured_product"
    if normalized in {"OS"}:
        return "equity", "ordinary_shares"
    if normalized in {"GDR"}:
        return "equity", "gdr"
    if normalized in {"NYR", "NYRS"}:
        return "equity", "nyr"
    if normalized in {"LTD", "LP"}:
        return "equity", "limited_partnership"
    if not normalized:
        warnings.append("missing provider security type mapped to unknown")
        return "other", "unknown"
    warnings.append(f"unsupported provider security type mapped to other: {normalized}")
    return "other", "other"


def _exchange(value: str | None, warnings: list[str]) -> ExchangeCandidate | None:
    if not isinstance(value, str) or not value.strip():
        warnings.append("missing primary exchange")
        return None
    mic = value.strip().upper()
    name = KNOWN_EXCHANGES.get(mic)
    if name is None:
        warnings.append(f"unknown primary exchange mapped provisionally: {mic}")
        return ExchangeCandidate(mic=mic, name=f"Unmapped exchange {mic}", provisional=True)
    return ExchangeCandidate(mic=mic, name=name)


def _parse_provider_datetime(value: str | None, field_name: str, warnings: list[str]) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        warnings.append(f"invalid {field_name} preserved in raw payload: {value}")
        return None


def _aliases(reference: TickerReference, canonical_ticker: str) -> tuple[AliasCandidate, ...]:
    aliases: list[AliasCandidate] = []
    for key in ("previous_ticker", "former_ticker"):
        value = reference.raw.get(key)
        if isinstance(value, str) and value.strip() and value.strip().upper() != canonical_ticker:
            aliases.append(AliasCandidate(key, value.strip().upper()))
    if reference.composite_figi:
        aliases.append(AliasCandidate("composite_figi", reference.composite_figi.strip()))
    if reference.share_class_figi:
        aliases.append(AliasCandidate("share_class_figi", reference.share_class_figi.strip()))
    return tuple(dict.fromkeys(aliases))
