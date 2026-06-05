"""Massive/Polygon symbol sync orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_symbols.symbol_master.data_quality import (
    ActiveState,
    SymbolQualityChecker,
    active_state_from_candidate,
    calculate_active_inactive_diffs,
)
from quant_symbols.symbol_master.fixtures import load_massive_fixture_pages
from quant_symbols.symbol_master.massive_mapper import map_ticker_reference
from quant_symbols.symbol_master.repository import SymbolMasterRepository
from quant_symbols.symbol_master.summary import SyncSummary
from quant_symbols.vendors.massive import MassiveClient
from quant_symbols.vendors.massive.models import TickerReferencePage


@dataclass(frozen=True)
class SyncOptions:
    fixture: Path | None = None
    dry_run: bool = False
    max_pages: int | None = None
    active: bool | None = None
    market: str = "stocks"
    locale: str = "us"
    limit: int = 1000


class MassiveSymbolSyncJob:
    """Run one Massive ticker-reference sync."""

    endpoint = "/v3/reference/tickers"

    def __init__(self, *, engine: Any | None = None, client: MassiveClient | None = None) -> None:
        self.engine = engine
        self.client = client

    def run(self, options: SyncOptions) -> SyncSummary:
        mode = "fixture" if options.fixture is not None else "live"
        summary = SyncSummary(mode=mode)
        if options.dry_run:
            pages = self._pages(options)
            self._process_pages(pages, summary, repository=None, run_id=None, vendor_source_id=None)
            return summary
        if self.engine is None:
            raise RuntimeError("DATABASE_URL/SQLAlchemy engine is required unless --dry-run is used")
        with self.engine.begin() as connection:
            repository = SymbolMasterRepository(connection)
            vendor_source_id = repository.vendor_source_id("massive")
            run_id = repository.start_run(
                vendor_source_id=vendor_source_id,
                endpoint=self.endpoint,
                request_params=_request_params(options),
            )
            summary.run_id = run_id
            previous_active_states = repository.latest_successful_active_states(
                vendor_source_id=vendor_source_id,
                endpoint=self.endpoint,
                before_run_id=run_id,
            )
            try:
                pages = self._pages(options)
                self._process_pages(
                    pages,
                    summary,
                    repository=repository,
                    run_id=run_id,
                    vendor_source_id=vendor_source_id,
                    previous_active_states=previous_active_states,
                )
            except Exception as exc:
                summary.status = "failed"
                summary.errors += 1
                summary.error_message = str(exc)
                repository.finish_run(
                    run_id=run_id,
                    status="failed",
                    records_seen=summary.records_seen,
                    records_inserted=summary.raw_payloads,
                    records_failed=summary.errors,
                    error_message=summary.error_message,
                    sync_summary=summary.health_payload(),
                    quality_findings=summary.quality_findings_payload(),
                )
                return summary
            repository.finish_run(
                run_id=run_id,
                status="succeeded",
                records_seen=summary.records_seen,
                records_inserted=summary.raw_payloads,
                records_failed=summary.errors,
                sync_summary=summary.health_payload(),
                quality_findings=summary.quality_findings_payload(),
            )
        return summary

    def latest_summary(self) -> dict[str, Any] | None:
        if self.engine is None:
            raise RuntimeError("DATABASE_URL/SQLAlchemy engine is required for sync-summary")
        with self.engine.connect() as connection:
            return SymbolMasterRepository(connection).latest_run_summary()

    def latest_health(self) -> dict[str, Any] | None:
        if self.engine is None:
            raise RuntimeError("DATABASE_URL/SQLAlchemy engine is required for symbol sync health")
        with self.engine.connect() as connection:
            return SymbolMasterRepository(connection).latest_symbol_sync_health()

    def _pages(self, options: SyncOptions) -> Iterable[TickerReferencePage]:
        if options.fixture is not None:
            pages = load_massive_fixture_pages(options.fixture)
            if options.max_pages is not None:
                return pages[: options.max_pages]
            return pages
        client = self.client or MassiveClient.from_env()
        return client.iter_ticker_pages(
            market=options.market,
            locale=options.locale,
            active=options.active,
            limit=options.limit,
            max_pages=options.max_pages,
        )

    def _process_pages(
        self,
        pages: Iterable[TickerReferencePage],
        summary: SyncSummary,
        *,
        repository: SymbolMasterRepository | None,
        run_id: int | None,
        vendor_source_id: int | None,
        previous_active_states: dict[tuple[str, str, str], ActiveState] | None = None,
    ) -> None:
        quality_checker = SymbolQualityChecker()
        current_active_states: dict[tuple[str, str, str], ActiveState] = {}
        dry_run_symbols: set[tuple[str, str, str]] = set()
        dry_run_exchanges: set[str] = set()
        dry_run_vendor_ids: set[str] = set()
        dry_run_aliases: set[tuple[str, str]] = set()
        for page in pages:
            summary.pages += 1
            for reference in page.results:
                summary.records_seen += 1
                mapped = map_ticker_reference(reference)
                for finding in quality_checker.check(
                    reference=reference,
                    candidate=mapped.candidate,
                    mapper_warnings=mapped.warnings,
                ):
                    summary.add_finding(finding)
                if mapped.candidate is None:
                    summary.skipped += 1
                    if mapped.skipped_reason:
                        summary.add_warning(f"{reference.ticker}: skipped: {mapped.skipped_reason}")
                    continue
                active_state = active_state_from_candidate(mapped.candidate)
                current_active_states[active_state.key] = active_state
                if repository is None:
                    symbol_key = (
                        mapped.candidate.locale.lower(),
                        mapped.candidate.market.lower(),
                        mapped.candidate.canonical_ticker.lower(),
                    )
                    if symbol_key not in dry_run_symbols:
                        summary.symbols_inserted += 1
                        dry_run_symbols.add(symbol_key)
                    if mapped.candidate.primary_exchange is not None:
                        exchange_key = mapped.candidate.primary_exchange.mic.lower()
                        if exchange_key not in dry_run_exchanges:
                            summary.exchanges_inserted += 1
                            dry_run_exchanges.add(exchange_key)
                    vendor_key = mapped.candidate.source_ticker.lower()
                    if vendor_key not in dry_run_vendor_ids:
                        summary.vendor_ids_inserted += 1
                        dry_run_vendor_ids.add(vendor_key)
                    for alias in mapped.candidate.aliases:
                        alias_key = (alias.alias_type, alias.alias_value.lower())
                        if alias_key not in dry_run_aliases:
                            summary.aliases_inserted += 1
                            dry_run_aliases.add(alias_key)
                    continue
                assert run_id is not None
                assert vendor_source_id is not None
                raw_link = repository.insert_raw_payload(
                    vendor_source_id=vendor_source_id,
                    run_id=run_id,
                    provider_ticker=reference.ticker,
                    payload=reference.raw,
                )
                summary.raw_payloads += 1
                summary.merge_repository_counts(
                    repository.upsert_candidate(
                        vendor_source_id=vendor_source_id,
                        run_id=run_id,
                        raw_payload_id=raw_link.id,
                        candidate=mapped.candidate,
                    )
                )
        if previous_active_states:
            summary.add_active_inactive_diffs(
                calculate_active_inactive_diffs(
                    previous=previous_active_states,
                    current=current_active_states,
                )
            )


def _request_params(options: SyncOptions) -> dict[str, Any]:
    params: dict[str, Any] = {
        "mode": "fixture" if options.fixture is not None else "live",
        "market": options.market,
        "locale": options.locale,
        "limit": options.limit,
    }
    if options.fixture is not None:
        params["fixture"] = str(options.fixture)
    if options.active is not None:
        params["active"] = options.active
    if options.max_pages is not None:
        params["max_pages"] = options.max_pages
    return params
