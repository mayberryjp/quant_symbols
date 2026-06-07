from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import quant_symbols._cli_impl as cli_impl
import quant_symbols.symbol_master.massive_raw_normalize as normalize_module
from quant_symbols.cli import build_parser
from quant_symbols.symbol_master.massive_raw_normalize import MassiveRawNormalizeJob
from quant_symbols.symbol_master.normalization import map_massive_alias_candidates
from quant_symbols.symbol_master.repository import (
    AliasUpsertResult,
    ExchangeUpsertResult,
    RawPayloadRow,
    SymbolVendorIdentityUpsertResult,
)


FIXTURES = Path(__file__).parent / "fixtures" / "massive"


class FakeEngine:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self.repository)


class FakeTransaction:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository

    def __enter__(self) -> FakeRepository:
        return self.repository

    def __exit__(self, *_exc: object) -> None:
        return None


class FakeRepository:
    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.raw_payloads: list[dict[str, Any]] = []
        self.exchanges: list[dict[str, Any]] = []
        self.symbols: list[dict[str, Any]] = []
        self.vendor_ids: list[dict[str, Any]] = []
        self.aliases: list[dict[str, Any]] = []
        self.raw_run_requests: list[int] = []

    def vendor_source_id(self, code: str) -> int:
        assert code == "massive"
        return 1

    def latest_successful_massive_ticker_run_with_payloads(self) -> dict[str, Any] | None:
        candidates = [
            run
            for run in self.runs
            if run["vendor_source_id"] == 1
            and run["endpoint"] == "/v3/reference/tickers"
            and run["status"] == "succeeded"
            and any(row["vendor_api_run_id"] == run["id"] for row in self.raw_payloads)
        ]
        if not candidates:
            return None
        return dict(sorted(candidates, key=lambda run: run["id"])[-1])

    def raw_payload_rows_for_run(
        self,
        *,
        vendor_source_id: int,
        run_id: int,
    ) -> tuple[RawPayloadRow, ...]:
        self.raw_run_requests.append(run_id)
        return tuple(
            RawPayloadRow(
                id=row["id"],
                provider_ticker=row["provider_ticker"],
                payload=dict(row["payload"]),
            )
            for row in self.raw_payloads
            if row["vendor_source_id"] == vendor_source_id and row["vendor_api_run_id"] == run_id
        )

    def upsert_exchange_candidate(self, exchange: object | None) -> ExchangeUpsertResult:
        if exchange is None:
            return ExchangeUpsertResult(exchange_id=None, counts={"exchanges_skipped": 1})
        mic = exchange.mic
        row = next((row for row in self.exchanges if row["mic"] == mic), None)
        if row is None:
            row = {"id": len(self.exchanges) + 1, "mic": mic, "name": exchange.name}
            self.exchanges.append(row)
            return ExchangeUpsertResult(exchange_id=row["id"], counts={"exchanges_inserted": 1})
        if row["name"] != exchange.name and exchange.provisional is False:
            row["name"] = exchange.name
            return ExchangeUpsertResult(exchange_id=row["id"], counts={"exchanges_updated": 1})
        return ExchangeUpsertResult(exchange_id=row["id"], counts={"exchanges_unchanged": 1})

    def upsert_symbol_vendor_identity_candidate(
        self,
        *,
        vendor_source_id: int,
        run_id: int,
        raw_payload_id: int,
        candidate: object,
        primary_exchange_id: int | None = None,
    ) -> SymbolVendorIdentityUpsertResult:
        symbol = self._find_symbol(vendor_source_id, candidate)
        symbol_counts: dict[str, int]
        values = {
            "canonical_ticker": candidate.canonical_ticker,
            "name": candidate.name,
            "market": candidate.market,
            "locale": candidate.locale,
            "primary_exchange_id": primary_exchange_id,
            "active": candidate.active if candidate.active is not None else True,
            "composite_figi": candidate.composite_figi,
            "share_class_figi": candidate.share_class_figi,
            "cik": candidate.cik,
            "last_seen_run_id": run_id,
            "last_seen_payload_id": raw_payload_id,
        }
        if symbol is None:
            symbol = {"id": len(self.symbols) + 1, **values}
            self.symbols.append(symbol)
            symbol_counts = {"symbols_inserted": 1}
        else:
            changed = any(symbol.get(key) != value for key, value in values.items() if not key.startswith("last_"))
            symbol.update(values)
            symbol_counts = {"symbols_updated" if changed else "symbols_unchanged": 1}

        vendor_id = self._find_vendor_id(vendor_source_id, candidate)
        vendor_values = {
            "symbol_id": symbol["id"],
            "vendor_source_id": vendor_source_id,
            "vendor_symbol": candidate.source_ticker,
            "vendor_asset_id": candidate.composite_figi,
            "active": candidate.active if candidate.active is not None else True,
            "last_seen_run_id": run_id,
            "last_seen_payload_id": raw_payload_id,
        }
        if vendor_id is None:
            self.vendor_ids.append({"id": len(self.vendor_ids) + 1, **vendor_values})
            vendor_counts = {"vendor_ids_inserted": 1}
        else:
            changed = any(
                vendor_id.get(key) != value for key, value in vendor_values.items() if not key.startswith("last_")
            )
            vendor_id.update(vendor_values)
            vendor_counts = {"vendor_ids_updated" if changed else "vendor_ids_unchanged": 1}

        return SymbolVendorIdentityUpsertResult(
            symbol_id=symbol["id"],
            counts={**symbol_counts, **vendor_counts},
        )

    def upsert_aliases_for_massive_candidate(
        self,
        *,
        vendor_source_id: int,
        raw_payload_id: int,
        symbol_id: int,
        candidate: object,
    ) -> AliasUpsertResult:
        counts: dict[str, int] = {}
        for alias in map_massive_alias_candidates(candidate):
            row = next(
                (
                    row
                    for row in self.aliases
                    if row["alias_type"] == alias.alias_type
                    and row["alias_value"].lower() == alias.alias_value.lower()
                    and row["active"] is True
                ),
                None,
            )
            if row is None:
                self.aliases.append(
                    {
                        "id": len(self.aliases) + 1,
                        "symbol_id": symbol_id,
                        "alias_type": alias.alias_type,
                        "alias_value": alias.alias_value,
                        "source_vendor_id": vendor_source_id,
                        "source_payload_id": raw_payload_id,
                        "active": True,
                    }
                )
                counts["aliases_inserted"] = counts.get("aliases_inserted", 0) + 1
            else:
                counts["aliases_unchanged"] = counts.get("aliases_unchanged", 0) + 1
        return AliasUpsertResult(counts=counts)

    def _find_symbol(self, vendor_source_id: int, candidate: object) -> dict[str, Any] | None:
        if candidate.composite_figi:
            row = next((row for row in self.symbols if row["composite_figi"] == candidate.composite_figi), None)
            if row is not None:
                return row
        vendor_id = self._find_vendor_id(vendor_source_id, candidate)
        if vendor_id is not None:
            return next(row for row in self.symbols if row["id"] == vendor_id["symbol_id"])
        return next(
            (
                row
                for row in self.symbols
                if row["locale"].lower() == candidate.locale.lower()
                and row["market"].lower() == candidate.market.lower()
                and row["canonical_ticker"].lower() == candidate.canonical_ticker.lower()
            ),
            None,
        )

    def _find_vendor_id(self, vendor_source_id: int, candidate: object) -> dict[str, Any] | None:
        if candidate.composite_figi:
            row = next(
                (
                    row
                    for row in self.vendor_ids
                    if row["vendor_source_id"] == vendor_source_id
                    and row["vendor_asset_id"] == candidate.composite_figi
                ),
                None,
            )
            if row is not None:
                return row
        return next(
            (
                row
                for row in self.vendor_ids
                if row["vendor_source_id"] == vendor_source_id
                and row["vendor_symbol"].lower() == candidate.source_ticker.lower()
            ),
            None,
        )


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def repository_factory(repository: FakeRepository) -> object:
    def factory(_connection: object) -> FakeRepository:
        return repository

    return factory


def add_run(repository: FakeRepository, run_id: int, *, endpoint: str, status: str) -> None:
    repository.runs.append(
        {
            "id": run_id,
            "vendor_source_id": 1,
            "endpoint": endpoint,
            "status": status,
        }
    )


def add_raw(repository: FakeRepository, run_id: int, payload_id: int, payload: dict[str, Any]) -> None:
    repository.raw_payloads.append(
        {
            "id": payload_id,
            "vendor_source_id": 1,
            "vendor_api_run_id": run_id,
            "provider_ticker": payload.get("ticker"),
            "payload": payload,
        }
    )


def test_cli_exposes_normalize_raw_commands() -> None:
    parser = build_parser()

    assert parser.parse_args(["symbols", "normalize-raw", "--latest"]).func.__name__ == "symbols_normalize_raw"
    parsed = parser.parse_args(["symbols", "normalize-raw", "--run-id", "123"])
    assert parsed.func.__name__ == "symbols_normalize_raw"
    assert parsed.run_id == 123


def test_cli_normalize_raw_prints_summary_without_massive_api_key(monkeypatch: Any, capsys: Any) -> None:
    class FakeJob:
        def __init__(self, *, engine: object) -> None:
            assert engine == "fake-engine"

        def run(self, *, latest: bool, run_id: int | None) -> object:
            assert latest is True
            assert run_id is None
            return normalize_module.NormalizeRawSummary(run_id=42, raw_records=0)

    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.setattr(cli_impl, "_engine", lambda: "fake-engine")
    monkeypatch.setattr(normalize_module, "MassiveRawNormalizeJob", FakeJob)

    cli_impl.symbols_normalize_raw(argparse.Namespace(latest=True, run_id=None))

    assert capsys.readouterr().out.strip() == (
        "symbols_normalize_raw=ok vendor=massive run_id=42 raw_records=0 "
        "symbols_inserted=0 symbols_updated=0 symbols_unchanged=0 "
        "exchanges_inserted=0 exchanges_updated=0 exchanges_unchanged=0 exchanges_skipped=0 "
        "vendor_ids_inserted=0 vendor_ids_updated=0 vendor_ids_unchanged=0 "
        "aliases_inserted=0 aliases_unchanged=0 skipped=0 errors=0"
    )


def test_latest_chooses_latest_successful_massive_ticker_run_with_payloads() -> None:
    repository = FakeRepository()
    add_run(repository, 10, endpoint="/v3/reference/tickers", status="succeeded")
    add_run(repository, 11, endpoint="/v3/reference/tickers", status="failed")
    add_run(repository, 12, endpoint="/v2/aggs/ticker", status="succeeded")
    add_run(repository, 13, endpoint="/v3/reference/tickers", status="succeeded")
    add_raw(repository, 11, 101, fixture("active_stock.json"))
    add_raw(repository, 12, 102, fixture("etf.json"))
    add_raw(repository, 13, 103, fixture("active_stock.json"))
    job = MassiveRawNormalizeJob(engine=FakeEngine(repository), repository_factory=repository_factory(repository))

    summary = job.run(latest=True)

    assert summary.run_id == 13
    assert summary.raw_records == 1
    assert repository.raw_run_requests == [13]
    assert summary.symbols_inserted == 1
    assert summary.vendor_ids_inserted == 1
    assert summary.aliases_inserted == 4
    assert summary.errors == 0


def test_run_id_uses_requested_run_without_switching_to_latest() -> None:
    repository = FakeRepository()
    add_run(repository, 1, endpoint="/v3/reference/tickers", status="succeeded")
    add_run(repository, 2, endpoint="/v3/reference/tickers", status="succeeded")
    add_raw(repository, 1, 101, fixture("active_stock.json"))
    add_raw(repository, 2, 102, fixture("etf.json"))
    job = MassiveRawNormalizeJob(engine=FakeEngine(repository), repository_factory=repository_factory(repository))

    summary = job.run(run_id=1)

    assert summary.run_id == 1
    assert summary.raw_records == 1
    assert repository.raw_run_requests == [1]
    assert [row["canonical_ticker"] for row in repository.symbols] == ["AAPL"]


def test_raw_payload_rows_are_written_through_exchange_symbol_vendor_and_alias_layers() -> None:
    repository = FakeRepository()
    add_run(repository, 20, endpoint="/v3/reference/tickers", status="succeeded")
    add_raw(repository, 20, 201, fixture("active_stock.json"))
    add_raw(repository, 20, 202, fixture("etf.json"))
    job = MassiveRawNormalizeJob(engine=FakeEngine(repository), repository_factory=repository_factory(repository))

    summary = job.run(run_id=20)

    assert summary.raw_records == 2
    assert summary.symbols_inserted == 2
    assert summary.exchanges_inserted == 2
    assert summary.vendor_ids_inserted == 2
    assert summary.aliases_inserted == 7
    assert summary.errors == 0
    assert len(repository.exchanges) == 2
    assert len(repository.symbols) == 2
    assert len(repository.vendor_ids) == 2
    assert len(repository.aliases) == 7


def test_repeated_normalize_raw_run_is_idempotent() -> None:
    repository = FakeRepository()
    add_run(repository, 20, endpoint="/v3/reference/tickers", status="succeeded")
    add_raw(repository, 20, 201, fixture("active_stock.json"))
    add_raw(repository, 20, 202, fixture("etf.json"))
    job = MassiveRawNormalizeJob(engine=FakeEngine(repository), repository_factory=repository_factory(repository))

    first = job.run(run_id=20)
    second = job.run(run_id=20)

    assert first.symbols_inserted == 2
    assert second.raw_records == 2
    assert second.symbols_unchanged == 2
    assert second.exchanges_unchanged == 2
    assert second.vendor_ids_unchanged == 2
    assert second.aliases_unchanged == 7
    assert second.errors == 0
    assert len(repository.exchanges) == 2
    assert len(repository.symbols) == 2
    assert len(repository.vendor_ids) == 2
    assert len(repository.aliases) == 7


def test_empty_selected_run_returns_zero_raw_record_summary() -> None:
    repository = FakeRepository()
    add_run(repository, 30, endpoint="/v3/reference/tickers", status="succeeded")
    job = MassiveRawNormalizeJob(engine=FakeEngine(repository), repository_factory=repository_factory(repository))

    summary = job.run(run_id=30)

    assert summary.format_line().startswith("symbols_normalize_raw=ok vendor=massive run_id=30 raw_records=0")
    assert summary.errors == 0
    assert repository.exchanges == []
    assert repository.symbols == []
    assert repository.vendor_ids == []
    assert repository.aliases == []


def test_bad_raw_row_is_counted_and_skipped_before_database_writes() -> None:
    repository = FakeRepository()
    add_run(repository, 40, endpoint="/v3/reference/tickers", status="succeeded")
    add_raw(repository, 40, 401, {"ticker": None, "market": "stocks", "locale": "us", "primary_exchange": "XNAS"})
    job = MassiveRawNormalizeJob(engine=FakeEngine(repository), repository_factory=repository_factory(repository))

    summary = job.run(run_id=40)

    assert summary.raw_records == 1
    assert summary.skipped == 1
    assert summary.errors == 1
    assert repository.exchanges == []
    assert repository.symbols == []
    assert repository.vendor_ids == []
    assert repository.aliases == []
