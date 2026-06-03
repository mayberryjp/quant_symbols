"""Typed Massive/Polygon response models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict

from quant_symbols.vendors.massive.errors import MassiveMalformedPayloadError


JsonObject = Dict[str, Any]


@dataclass(frozen=True)
class RawVendorPayload:
    """Raw provider payload prepared for later ingestion persistence."""

    vendor: str
    endpoint: str
    provider_id: str
    fetched_at: datetime
    request_url: str
    payload: JsonObject


@dataclass(frozen=True)
class TickerReference:
    """Single `/v3/reference/tickers` result with provider fields preserved."""

    ticker: str
    raw: JsonObject
    name: str | None = None
    market: str | None = None
    locale: str | None = None
    primary_exchange: str | None = None
    type: str | None = None
    active: bool | None = None
    currency_name: str | None = None
    cik: str | None = None
    composite_figi: str | None = None
    share_class_figi: str | None = None
    last_updated_utc: str | None = None
    delisted_utc: str | None = None

    @classmethod
    def from_payload(cls, payload: JsonObject) -> "TickerReference":
        if not isinstance(payload, dict):
            raise MassiveMalformedPayloadError("ticker result must be an object")
        ticker = payload.get("ticker")
        if not isinstance(ticker, str) or not ticker.strip():
            raise MassiveMalformedPayloadError("ticker result is missing ticker")
        return cls(
            ticker=ticker,
            raw=dict(payload),
            name=_optional_str(payload, "name"),
            market=_optional_str(payload, "market"),
            locale=_optional_str(payload, "locale"),
            primary_exchange=_optional_str(payload, "primary_exchange"),
            type=_optional_str(payload, "type"),
            active=_optional_bool(payload, "active"),
            currency_name=_optional_str(payload, "currency_name"),
            cik=_optional_str(payload, "cik"),
            composite_figi=_optional_str(payload, "composite_figi"),
            share_class_figi=_optional_str(payload, "share_class_figi"),
            last_updated_utc=_optional_str(payload, "last_updated_utc"),
            delisted_utc=_optional_str(payload, "delisted_utc"),
        )

    def as_raw_vendor_payload(self, *, request_url: str, fetched_at: datetime | None = None) -> RawVendorPayload:
        return RawVendorPayload(
            vendor="massive",
            endpoint="/v3/reference/tickers",
            provider_id=self.ticker,
            fetched_at=fetched_at or datetime.now(timezone.utc),
            request_url=request_url,
            payload=self.raw,
        )


@dataclass(frozen=True)
class TickerReferencePage:
    """One provider page from `/v3/reference/tickers`."""

    request_url: str
    raw: JsonObject
    results: tuple[TickerReference, ...]
    next_url: str | None = None
    status: str | None = None
    count: int | None = None
    request_id: str | None = None
    fetched_at: datetime | None = None

    @classmethod
    def from_payload(
        cls,
        payload: JsonObject,
        *,
        request_url: str,
        fetched_at: datetime | None = None,
    ) -> "TickerReferencePage":
        if not isinstance(payload, dict):
            raise MassiveMalformedPayloadError("ticker page payload must be an object")
        results_payload = payload.get("results")
        if not isinstance(results_payload, list):
            raise MassiveMalformedPayloadError("ticker page payload is missing results list")
        results = tuple(TickerReference.from_payload(item) for item in results_payload)
        next_url = payload.get("next_url")
        if next_url is not None and not isinstance(next_url, str):
            raise MassiveMalformedPayloadError("ticker page next_url must be a string when present")
        return cls(
            request_url=request_url,
            raw=dict(payload),
            results=results,
            next_url=next_url,
            status=_optional_str(payload, "status"),
            count=_optional_int(payload, "count"),
            request_id=_optional_str(payload, "request_id"),
            fetched_at=fetched_at or datetime.now(timezone.utc),
        )

    def raw_vendor_payloads(self) -> tuple[RawVendorPayload, ...]:
        fetched_at = self.fetched_at or datetime.now(timezone.utc)
        return tuple(
            result.as_raw_vendor_payload(request_url=self.request_url, fetched_at=fetched_at)
            for result in self.results
        )


def _optional_str(payload: JsonObject, key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _optional_bool(payload: JsonObject, key: str) -> bool | None:
    value = payload.get(key)
    return value if isinstance(value, bool) else None


def _optional_int(payload: JsonObject, key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) else None
