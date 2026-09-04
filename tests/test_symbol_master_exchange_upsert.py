from __future__ import annotations

from typing import Any

import quant_symbols.symbol_master.repository as repository_module
from quant_symbols.symbol_master.normalization import (
    map_massive_exchange_candidate,
    map_massive_ticker_raw_record,
)
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


class FakeExchangeConnection:
    def __init__(self) -> None:
        self.exchanges: list[dict[str, Any]] = []
        self.next_exchange_id = 1
        self.touched_tables: list[str] = []

    def execute(self, statement: object, params: dict[str, Any] | None = None) -> FakeResult:
        sql = str(statement).lower()
        params = params or {}
        self._record_and_guard_tables(sql)

        if "select id, name from symbols.exchanges where mic" in sql:
            rows = [row for row in self.exchanges if row["mic"] == params["mic"]]
            return FakeResult([dict(row) for row in rows])

        if "insert into symbols.exchanges" in sql:
            row = {"id": self.next_exchange_id, "mic": params["mic"], "name": params["name"]}
            self.next_exchange_id += 1
            self.exchanges.append(row)
            return FakeResult([{"id": row["id"]}])

        if "update symbols.exchanges set name" in sql:
            row = next(row for row in self.exchanges if row["id"] == params["id"])
            row["name"] = params["name"]
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
        forbidden_tables = set(tables) - {"symbols.exchanges"}
        touched_forbidden = forbidden_tables.intersection(self.touched_tables)
        if touched_forbidden:
            raise AssertionError(f"exchange-only upsert touched {sorted(touched_forbidden)}")


def raw_record(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "market": "stocks",
        "locale": "us",
        "primary_exchange": "XNAS",
        "type": "CS",
        "active": True,
    }
    payload.update(overrides)
    return payload


def test_exchange_upsert_inserts_new_exchange_from_massive_candidate(monkeypatch: Any) -> None:
    monkeypatch.setattr(repository_module, "_text", lambda sql: sql)
    connection = FakeExchangeConnection()
    repository = SymbolMasterRepository(connection)
    ticker = map_massive_ticker_raw_record(raw_record(primary_exchange="ARCX"))
    exchange = map_massive_exchange_candidate(ticker)

    result = repository.upsert_exchange_candidate(exchange)

    assert result.exchange_id == 1
    assert result.counts == {"exchanges_inserted": 1}
    assert connection.exchanges == [{"id": 1, "mic": "ARCX", "name": "NYSE Arca"}]


def test_repeated_exchange_upsert_does_not_duplicate_exchange(monkeypatch: Any) -> None:
    monkeypatch.setattr(repository_module, "_text", lambda sql: sql)
    connection = FakeExchangeConnection()
    repository = SymbolMasterRepository(connection)
    exchange = map_massive_exchange_candidate(map_massive_ticker_raw_record(raw_record()))

    first = repository.upsert_exchange_candidate(exchange)
    second = repository.upsert_exchange_candidate(exchange)

    assert first.counts == {"exchanges_inserted": 1}
    assert second.exchange_id == 1
    assert second.counts == {"exchanges_unchanged": 1}
    assert len(connection.exchanges) == 1


def test_known_exchange_upsert_updates_existing_exchange_name(monkeypatch: Any) -> None:
    monkeypatch.setattr(repository_module, "_text", lambda sql: sql)
    connection = FakeExchangeConnection()
    connection.exchanges.append({"id": 1, "mic": "XNAS", "name": "Old Nasdaq Name"})
    connection.next_exchange_id = 2
    repository = SymbolMasterRepository(connection)
    exchange = map_massive_exchange_candidate(map_massive_ticker_raw_record(raw_record()))

    result = repository.upsert_exchange_candidate(exchange)

    assert result.exchange_id == 1
    assert result.counts == {"exchanges_updated": 1}
    assert connection.exchanges == [{"id": 1, "mic": "XNAS", "name": "Nasdaq Stock Market"}]


def test_unknown_exchange_code_is_inserted_predictably_as_provisional(monkeypatch: Any) -> None:
    monkeypatch.setattr(repository_module, "_text", lambda sql: sql)
    connection = FakeExchangeConnection()
    repository = SymbolMasterRepository(connection)
    ticker = map_massive_ticker_raw_record(raw_record(primary_exchange="xzzz"))
    exchange = map_massive_exchange_candidate(ticker)

    assert exchange is not None
    assert exchange.mic == "XZZZ"
    assert exchange.name == "Unmapped exchange XZZZ"
    assert exchange.provisional is True

    result = repository.upsert_exchange_candidate(exchange)

    assert result.exchange_id == 1
    assert result.counts == {"exchanges_inserted": 1}
    assert connection.exchanges == [{"id": 1, "mic": "XZZZ", "name": "Unmapped exchange XZZZ"}]


def test_missing_exchange_code_is_skipped_without_database_write(monkeypatch: Any) -> None:
    monkeypatch.setattr(repository_module, "_text", lambda sql: sql)
    connection = FakeExchangeConnection()
    repository = SymbolMasterRepository(connection)
    ticker = map_massive_ticker_raw_record(raw_record(primary_exchange=None))
    exchange = map_massive_exchange_candidate(ticker)

    result = repository.upsert_exchange_candidate(exchange)

    assert exchange is None
    assert result.exchange_id is None
    assert result.counts == {"exchanges_skipped": 1}
    assert connection.exchanges == []
    assert connection.touched_tables == []


def test_exchange_upsert_does_not_touch_symbols_vendor_ids_or_aliases(monkeypatch: Any) -> None:
    monkeypatch.setattr(repository_module, "_text", lambda sql: sql)
    connection = FakeExchangeConnection()
    repository = SymbolMasterRepository(connection)
    exchange = map_massive_exchange_candidate(map_massive_ticker_raw_record(raw_record()))

    repository.upsert_exchange_candidate(exchange)

    assert set(connection.touched_tables) == {"symbols.exchanges"}
