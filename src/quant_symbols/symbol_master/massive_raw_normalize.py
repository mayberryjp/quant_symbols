"""Normalize stored Massive raw payload rows into symbol-master tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from quant_symbols.symbol_master.normalization import (
    MassiveTickerCandidate,
    map_massive_exchange_candidate,
    map_massive_ticker_raw_record,
)
from quant_symbols.symbol_master.repository import RawPayloadRow, SymbolMasterRepository


RepositoryFactory = Callable[[Any], SymbolMasterRepository]


@dataclass
class NormalizeRawSummary:
    """Counters for normalizing one stored Massive raw payload run."""

    status: str = "ok"
    vendor: str = "massive"
    run_id: int | None = None
    raw_records: int = 0
    symbols_inserted: int = 0
    symbols_updated: int = 0
    symbols_unchanged: int = 0
    exchanges_inserted: int = 0
    exchanges_updated: int = 0
    exchanges_unchanged: int = 0
    exchanges_skipped: int = 0
    vendor_ids_inserted: int = 0
    vendor_ids_updated: int = 0
    vendor_ids_unchanged: int = 0
    aliases_inserted: int = 0
    aliases_unchanged: int = 0
    skipped: int = 0
    errors: int = 0

    def merge_counts(self, counts: dict[str, int]) -> None:
        for key, value in counts.items():
            if hasattr(self, key):
                setattr(self, key, getattr(self, key) + value)

    def format_line(self) -> str:
        fields: list[tuple[str, object]] = [
            ("symbols_normalize_raw", self.status),
            ("vendor", self.vendor),
            ("run_id", self.run_id if self.run_id is not None else "none"),
        ]
        fields.extend(
            [
                ("raw_records", self.raw_records),
                ("symbols_inserted", self.symbols_inserted),
                ("symbols_updated", self.symbols_updated),
                ("symbols_unchanged", self.symbols_unchanged),
                ("exchanges_inserted", self.exchanges_inserted),
                ("exchanges_updated", self.exchanges_updated),
                ("exchanges_unchanged", self.exchanges_unchanged),
                ("exchanges_skipped", self.exchanges_skipped),
                ("vendor_ids_inserted", self.vendor_ids_inserted),
                ("vendor_ids_updated", self.vendor_ids_updated),
                ("vendor_ids_unchanged", self.vendor_ids_unchanged),
                ("aliases_inserted", self.aliases_inserted),
                ("aliases_unchanged", self.aliases_unchanged),
                ("skipped", self.skipped),
                ("errors", self.errors),
            ]
        )
        return " ".join(f"{key}={value}" for key, value in fields)


class MassiveRawNormalizeJob:
    """Normalize existing raw Massive ticker-reference rows without provider calls."""

    def __init__(
        self,
        *,
        engine: Any,
        repository_factory: RepositoryFactory = SymbolMasterRepository,
    ) -> None:
        self.engine = engine
        self.repository_factory = repository_factory

    def run(self, *, latest: bool = False, run_id: int | None = None) -> NormalizeRawSummary:
        if latest == (run_id is not None):
            raise ValueError("exactly one of latest=True or run_id must be provided")

        with self.engine.begin() as connection:
            repository = self.repository_factory(connection)
            vendor_source_id = repository.vendor_source_id("massive")
            selected_run_id = run_id
            if latest:
                selected = repository.latest_successful_massive_ticker_run_with_payloads()
                selected_run_id = int(selected["id"]) if selected is not None else None

            summary = NormalizeRawSummary(run_id=selected_run_id)
            if selected_run_id is None:
                return summary

            rows = repository.raw_payload_rows_for_run(
                vendor_source_id=vendor_source_id,
                run_id=selected_run_id,
            )
            for row in rows:
                summary.raw_records += 1
                self._normalize_row(
                    repository=repository,
                    vendor_source_id=vendor_source_id,
                    run_id=selected_run_id,
                    row=row,
                    summary=summary,
                )
            return summary

    def _normalize_row(
        self,
        *,
        repository: SymbolMasterRepository,
        vendor_source_id: int,
        run_id: int,
        row: RawPayloadRow,
        summary: NormalizeRawSummary,
    ) -> None:
        try:
            candidate = map_massive_ticker_raw_record(row.payload)
            if not _candidate_has_required_symbol_fields(candidate):
                summary.skipped += 1
                summary.errors += 1
                return
            exchange = map_massive_exchange_candidate(candidate)
            exchange_result = repository.upsert_exchange_candidate(exchange)
            summary.merge_counts(exchange_result.counts)
            symbol_result = repository.upsert_symbol_vendor_identity_candidate(
                vendor_source_id=vendor_source_id,
                run_id=run_id,
                raw_payload_id=row.id,
                candidate=candidate,
                primary_exchange_id=exchange_result.exchange_id,
            )
            summary.merge_counts(symbol_result.counts)
            alias_result = repository.upsert_aliases_for_massive_candidate(
                vendor_source_id=vendor_source_id,
                raw_payload_id=row.id,
                symbol_id=symbol_result.symbol_id,
                candidate=candidate,
            )
            summary.merge_counts(alias_result.counts)
        except (TypeError, ValueError):
            summary.skipped += 1
            summary.errors += 1


def _candidate_has_required_symbol_fields(candidate: MassiveTickerCandidate) -> bool:
    return all(
        isinstance(value, str) and value.strip()
        for value in (
            candidate.source_ticker,
            candidate.canonical_ticker,
            candidate.market,
            candidate.locale,
        )
    )
