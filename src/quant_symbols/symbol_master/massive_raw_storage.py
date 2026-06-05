"""Raw Massive/Polygon payload storage for symbol-master traceability."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os
import re
from typing import Any, Callable

from quant_symbols.symbol_master.repository import SymbolMasterRepository
from quant_symbols.vendors.massive.models import TickerReferencePage


RepositoryFactory = Callable[[Any], SymbolMasterRepository]

SENSITIVE_KEY_PARTS = ("apikey", "api_key", "api-key", "key", "secret", "token", "password")
REDACTED = "<redacted>"


@dataclass
class RawStorageSummary:
    """Counters for a raw-only Massive ticker-reference persistence run."""

    status: str = "ok"
    run_id: int | None = None
    pages: int = 0
    records_seen: int = 0
    raw_payloads_inserted: int = 0
    errors: int = 0
    error_message: str | None = None


class MassiveRawPayloadStorageJob:
    """Store Massive ticker-reference records without normalized symbol writes."""

    endpoint = "/v3/reference/tickers"

    def __init__(
        self,
        *,
        engine: Any,
        repository_factory: RepositoryFactory = SymbolMasterRepository,
    ) -> None:
        self.engine = engine
        self.repository_factory = repository_factory

    def store_pages(
        self,
        pages: Iterable[TickerReferencePage],
        *,
        request_params: dict[str, Any],
    ) -> RawStorageSummary:
        summary = RawStorageSummary()
        safe_request_params = sanitize_request_params(request_params)
        with self.engine.begin() as connection:
            repository = self.repository_factory(connection)
            vendor_source_id = repository.ensure_vendor_source(
                code="massive",
                name="Massive / Polygon",
                base_url="https://api.polygon.io",
            )
            run_id = repository.start_run(
                vendor_source_id=vendor_source_id,
                endpoint=self.endpoint,
                request_params=safe_request_params,
            )
            summary.run_id = run_id
            try:
                for page in pages:
                    summary.pages += 1
                    for reference in page.results:
                        summary.records_seen += 1
                        repository.insert_raw_payload(
                            vendor_source_id=vendor_source_id,
                            run_id=run_id,
                            provider_ticker=reference.ticker,
                            payload=reference.raw,
                        )
                        summary.raw_payloads_inserted += 1
            except Exception as exc:
                summary.status = "failed"
                summary.errors += 1
                summary.error_message = safe_error_message(str(exc), request_params=request_params)
                repository.finish_run(
                    run_id=run_id,
                    status="failed",
                    records_seen=summary.records_seen,
                    records_inserted=summary.raw_payloads_inserted,
                    records_failed=summary.errors,
                    error_message=summary.error_message,
                )
                return summary

            repository.finish_run(
                run_id=run_id,
                status="succeeded",
                records_seen=summary.records_seen,
                records_inserted=summary.raw_payloads_inserted,
                records_failed=summary.errors,
            )
        return summary


def sanitize_request_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return request metadata with secret-like values redacted."""

    return {key: _sanitize_value(key, value) for key, value in params.items()}


def safe_error_message(message: str, *, request_params: dict[str, Any]) -> str:
    safe = message
    for value in _secret_values(request_params):
        if value:
            safe = safe.replace(value, REDACTED)
    env_key = os.environ.get("MASSIVE_API_KEY")
    if env_key:
        safe = safe.replace(env_key, REDACTED)
    safe = re.sub(r"(?i)(api[_-]?key|apikey|token|secret|password)=([^&\s]+)", rf"\1={REDACTED}", safe)
    return safe.strip().replace("\n", " ").replace("\r", " ")[:500]


def _sanitize_value(key: str, value: Any) -> Any:
    if _sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return sanitize_request_params(value)
    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(key, item) for item in value]
    return value


def _secret_values(params: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key, value in params.items():
        if _sensitive_key(key):
            if isinstance(value, str):
                values.append(value)
            continue
        if isinstance(value, dict):
            values.extend(_secret_values(value))
    return tuple(values)


def _sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)
