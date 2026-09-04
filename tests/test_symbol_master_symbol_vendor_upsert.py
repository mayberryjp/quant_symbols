from __future__ import annotations

from typing import Any

import quant_symbols.symbol_master.repository as repository_module
from quant_symbols.symbol_master.normalization import map_massive_ticker_raw_record
from quant_symbols.symbol_master.repository import SymbolMasterRepository


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeResult:
        return self

    def first(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def one(self) -> dict[str, Any]:
        if len(self.rows) != 1:
            raise AssertionError(f"expected one row, got {len(self.rows)}")
        return self.rows[0]


class FakeSymbolConnection:
    def __init__(self) -> None:
        self.symbols: list[dict[str, Any]] = []
        self.vendor_ids: list[dict[str, Any]] = []
        self.next_symbol_id = 1
        self.next_vendor_id = 1
        self.touched_tables: list[str] = []

    def execute(self, statement: object, params: dict[str, Any] | None = None) -> FakeResult:
        sql = " ".join(str(statement).lower().split())
        params = params or {}
        self._record_and_guard_tables(sql)

        if "select * from symbols.symbols where composite_figi = :figi" in sql:
            return FakeResult(
                [dict(row) for row in self.symbols if row["composite_figi"] == params["figi"]]
            )

        if "from symbols.symbol_vendor_ids v join symbols.symbols s" in sql:
            matching_vendor_ids = [
                row
                for row in self.vendor_ids
                if row["vendor_source_id"] == params["vendor_source_id"]
                and row["vendor_symbol"].lower() == params["vendor_symbol"].lower()
            ]
            matching_vendor_ids.sort(key=lambda row: (not row["active"], row["id"]))
            rows = []
            for vendor_id in matching_vendor_ids:
                symbol = next(row for row in self.symbols if row["id"] == vendor_id["symbol_id"])
                rows.append(dict(symbol))
            return FakeResult(rows[:1])

        if "select * from symbols.symbols where lower(locale)" in sql:
            rows = [
                row
                for row in self.symbols
                if row["locale"].lower() == params["locale"].lower()
                and row["market"].lower() == params["market"].lower()
                and row["canonical_ticker"].lower() == params["ticker"].lower()
            ]
            rows.sort(key=lambda row: (not row["active"], row["id"]))
            return FakeResult([dict(row) for row in rows[:1]])

        if "insert into symbols.symbols" in sql:
            row = {
                "id": self.next_symbol_id,
                "canonical_ticker": params["canonical_ticker"],
                "name": params["name"],
                "market": params["market"],
                "locale": params["locale"],
                "currency": params["currency"],
                "primary_exchange_id": params["primary_exchange_id"],
                "asset_class": params["asset_class"],
                "security_type": params["security_type"],
                "active": params["active"],
                "cik": params["cik"],
                "composite_figi": params["composite_figi"],
                "share_class_figi": params["share_class_figi"],
                "first_seen_run_id": params["run_id"],
                "first_seen_payload_id": params["payload_id"],
                "last_seen_run_id": params["run_id"],
                "last_seen_payload_id": params["payload_id"],
                "delisted_at": params["delisted_at"],
            }
            self.next_symbol_id += 1
            self.symbols.append(row)
            return FakeResult([{"id": row["id"]}])

        if "update symbols.symbols set canonical_ticker" in sql:
            row = next(row for row in self.symbols if row["id"] == params["id"])
            for key in (
                "canonical_ticker",
                "name",
                "market",
                "locale",
                "currency",
                "primary_exchange_id",
                "asset_class",
                "security_type",
                "active",
                "cik",
                "composite_figi",
                "share_class_figi",
                "delisted_at",
            ):
                row[key] = params[key]
            row["last_seen_run_id"] = params["run_id"]
            row["last_seen_payload_id"] = params["payload_id"]
            return FakeResult([])

        if "from symbols.symbol_vendor_ids" in sql and "vendor_asset_id = :vendor_asset_id" in sql:
            rows = [
                row
                for row in self.vendor_ids
                if row["vendor_source_id"] == params["vendor_source_id"]
                and row["vendor_asset_id"] == params["vendor_asset_id"]
            ]
            rows.sort(key=lambda row: (not row["active"], row["id"]))
            return FakeResult([dict(row) for row in rows[:1]])

        if "from symbols.symbol_vendor_ids" in sql and "lower(vendor_symbol)" in sql:
            rows = [
                row
                for row in self.vendor_ids
                if row["vendor_source_id"] == params["vendor_source_id"]
                and row["vendor_symbol"].lower() == params["vendor_symbol"].lower()
            ]
            rows.sort(key=lambda row: (not row["active"], row["id"]))
            return FakeResult([dict(row) for row in rows[:1]])

        if "insert into symbols.symbol_vendor_ids" in sql:
            row = {
                "id": self.next_vendor_id,
                "symbol_id": params["symbol_id"],
                "vendor_source_id": params["vendor_source_id"],
                "vendor_symbol": params["vendor_symbol"],
                "vendor_asset_id": params["vendor_asset_id"],
                "first_seen_run_id": params["run_id"],
                "first_seen_payload_id": params["payload_id"],
                "last_seen_run_id": params["run_id"],
                "last_seen_payload_id": params["payload_id"],
                "active": params["active"],
            }
            self.next_vendor_id += 1
            self.vendor_ids.append(row)
            return FakeResult([])

        if "update symbols.symbol_vendor_ids set symbol_id" in sql:
            row = next(row for row in self.vendor_ids if row["id"] == params["id"])
            row["symbol_id"] = params["symbol_id"]
            row["vendor_symbol"] = params["vendor_symbol"]
            row["vendor_asset_id"] = params["vendor_asset_id"]
            row["last_seen_run_id"] = params["run_id"]
            row["last_seen_payload_id"] = params["payload_id"]
            row["active"] = params["active"]
            return FakeResult([])

        raise AssertionError(f"unexpected SQL: {statement}")

    def _record_and_guard_tables(self, sql: str) -> None:
        tables = (
            "symbols.exchanges",
            "symbols.symbols",
            "symbols.symbol_vendor_ids",
            "symbols.symbol_aliases",
            "symbols.raw_vendor_payloads",
            "symbols.vendor_api_runs",
        )
        for table in tables:
            if table in sql:
                self.touched_tables.append(table)
        allowed_tables = {"symbols.symbols", "symbols.symbol_vendor_ids"}
        touched_forbidden = set(self.touched_tables) - allowed_tables
        if touched_forbidden:
            raise AssertionError(f"symbol/vendor upsert touched {sorted(touched_forbidden)}")


def raw_record(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "market": "stocks",
        "locale": "us",
        "primary_exchange": "XNAS",
        "currency_name": "usd",
        "type": "CS",
        "active": True,
        "cik": "0000320193",
        "composite_figi": "BBG000B9XRY4",
        "share_class_figi": "BBG001S5N8V8",
    }
    payload.update(overrides)
    return payload


def repository(monkeypatch: Any) -> tuple[SymbolMasterRepository, FakeSymbolConnection]:
    monkeypatch.setattr(repository_module, "_text", lambda sql: sql)
    connection = FakeSymbolConnection()
    return SymbolMasterRepository(connection), connection


def test_upsert_inserts_symbol_and_massive_vendor_id(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    candidate = map_massive_ticker_raw_record(raw_record())

    result = repo.upsert_symbol_vendor_identity_candidate(
        vendor_source_id=1,
        run_id=10,
        raw_payload_id=100,
        candidate=candidate,
        primary_exchange_id=5,
    )

    assert result.symbol_id == 1
    assert result.counts == {"symbols_inserted": 1, "vendor_ids_inserted": 1}
    assert len(connection.symbols) == 1
    assert connection.symbols[0]["canonical_ticker"] == "AAPL"
    assert connection.symbols[0]["asset_class"] == "equity"
    assert connection.symbols[0]["security_type"] == "common_stock"
    assert connection.symbols[0]["primary_exchange_id"] == 5
    assert connection.vendor_ids == [
        {
            "id": 1,
            "symbol_id": 1,
            "vendor_source_id": 1,
            "vendor_symbol": "AAPL",
            "vendor_asset_id": "BBG000B9XRY4",
            "first_seen_run_id": 10,
            "first_seen_payload_id": 100,
            "last_seen_run_id": 10,
            "last_seen_payload_id": 100,
            "active": True,
        }
    ]


def test_repeated_upsert_is_idempotent_without_duplicate_rows(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    candidate = map_massive_ticker_raw_record(raw_record())

    repo.upsert_symbol_vendor_identity_candidate(
        vendor_source_id=1, run_id=10, raw_payload_id=100, candidate=candidate
    )
    second = repo.upsert_symbol_vendor_identity_candidate(
        vendor_source_id=1, run_id=11, raw_payload_id=101, candidate=candidate
    )

    assert second.symbol_id == 1
    assert second.counts == {"symbols_unchanged": 1, "vendor_ids_unchanged": 1}
    assert len(connection.symbols) == 1
    assert len(connection.vendor_ids) == 1
    assert connection.symbols[0]["last_seen_run_id"] == 11
    assert connection.vendor_ids[0]["last_seen_payload_id"] == 101


def test_composite_figi_match_updates_existing_symbol_without_duplicate(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    existing = map_massive_ticker_raw_record(raw_record(ticker="OLD"))
    repo.upsert_symbol_vendor_identity_candidate(
        vendor_source_id=1, run_id=10, raw_payload_id=100, candidate=existing
    )
    renamed = map_massive_ticker_raw_record(raw_record(ticker="NEW"))

    result = repo.upsert_symbol_vendor_identity_candidate(
        vendor_source_id=1, run_id=11, raw_payload_id=101, candidate=renamed
    )

    assert result.symbol_id == 1
    assert result.counts == {"symbols_updated": 1, "vendor_ids_updated": 1}
    assert len(connection.symbols) == 1
    assert connection.symbols[0]["canonical_ticker"] == "NEW"
    assert connection.vendor_ids[0]["vendor_symbol"] == "NEW"


def test_vendor_symbol_match_is_used_before_canonical_fallback(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    existing = map_massive_ticker_raw_record(raw_record(ticker="OLD", composite_figi=None))
    repo.upsert_symbol_vendor_identity_candidate(
        vendor_source_id=1, run_id=10, raw_payload_id=100, candidate=existing
    )
    connection.vendor_ids[0]["vendor_symbol"] = "MSFT"
    candidate = map_massive_ticker_raw_record(raw_record(ticker="MSFT", composite_figi=None))

    result = repo.upsert_symbol_vendor_identity_candidate(
        vendor_source_id=1, run_id=11, raw_payload_id=101, candidate=candidate
    )

    assert result.symbol_id == 1
    assert result.counts == {"symbols_updated": 1, "vendor_ids_unchanged": 1}
    assert len(connection.symbols) == 1
    assert connection.symbols[0]["canonical_ticker"] == "MSFT"


def test_unknown_type_is_stored_with_safe_schema_fallback(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    candidate = map_massive_ticker_raw_record(raw_record(type="RIGHT"))

    result = repo.upsert_symbol_vendor_identity_candidate(
        vendor_source_id=1, run_id=10, raw_payload_id=100, candidate=candidate
    )

    assert result.counts == {"symbols_inserted": 1, "vendor_ids_inserted": 1}
    assert connection.symbols[0]["asset_class"] == "other"
    assert connection.symbols[0]["security_type"] == "unknown"


def test_symbol_vendor_upsert_does_not_touch_exchanges_aliases_or_raw_tables(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    candidate = map_massive_ticker_raw_record(raw_record())

    repo.upsert_symbol_vendor_identity_candidate(
        vendor_source_id=1, run_id=10, raw_payload_id=100, candidate=candidate
    )

    assert set(connection.touched_tables) == {
        "symbols.symbols",
        "symbols.symbol_vendor_ids",
    }
