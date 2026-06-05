from __future__ import annotations

from typing import Any

import quant_symbols.symbol_master.repository as repository_module
from quant_symbols.symbol_master.normalization import (
    MassiveAliasCandidate,
    map_massive_alias_candidates,
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


class FakeAliasConnection:
    def __init__(self) -> None:
        self.aliases: list[dict[str, Any]] = []
        self.next_alias_id = 1
        self.touched_tables: list[str] = []

    def execute(self, statement: object, params: dict[str, Any] | None = None) -> FakeResult:
        sql = " ".join(str(statement).lower().split())
        params = params or {}
        self._record_and_guard_tables(sql)

        if "select id from symbol_master.symbol_aliases" in sql:
            rows = [
                row
                for row in self.aliases
                if row["alias_type"] == params["alias_type"]
                and row["alias_value"].lower() == params["alias_value"].lower()
                and row["active"] is True
            ]
            return FakeResult([{"id": row["id"]} for row in rows[:1]])

        if "insert into symbol_master.symbol_aliases" in sql:
            row = {
                "id": self.next_alias_id,
                "symbol_id": params["symbol_id"],
                "alias_type": params["alias_type"],
                "alias_value": params["alias_value"],
                "source_vendor_id": params["source_vendor_id"],
                "source_payload_id": params["source_payload_id"],
                "active": True,
            }
            self.next_alias_id += 1
            self.aliases.append(row)
            return FakeResult([])

        raise AssertionError(f"unexpected SQL: {statement}")

    def _record_and_guard_tables(self, sql: str) -> None:
        tables = (
            "symbol_master.exchanges",
            "symbol_master.symbols",
            "symbol_master.symbol_vendor_ids",
            "symbol_master.symbol_aliases",
            "symbol_master.raw_vendor_payloads",
            "symbol_master.vendor_api_runs",
        )
        for table in tables:
            if table in sql:
                self.touched_tables.append(table)
        allowed_tables = {"symbol_master.symbol_aliases"}
        touched_forbidden = set(self.touched_tables) - allowed_tables
        if touched_forbidden:
            raise AssertionError(f"alias upsert touched {sorted(touched_forbidden)}")


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


def repository(monkeypatch: Any) -> tuple[SymbolMasterRepository, FakeAliasConnection]:
    monkeypatch.setattr(repository_module, "_text", lambda sql: sql)
    connection = FakeAliasConnection()
    return SymbolMasterRepository(connection), connection


def test_massive_alias_candidates_include_current_lookup_fields() -> None:
    candidate = map_massive_ticker_raw_record(raw_record())

    aliases = map_massive_alias_candidates(candidate)

    assert aliases == (
        MassiveAliasCandidate("ticker", "AAPL"),
        MassiveAliasCandidate("cik", "0000320193"),
        MassiveAliasCandidate("composite_figi", "BBG000B9XRY4"),
        MassiveAliasCandidate("share_class_figi", "BBG001S5N8V8"),
    )


def test_alias_upsert_inserts_aliases_for_existing_symbol(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    candidate = map_massive_ticker_raw_record(raw_record())

    result = repo.upsert_aliases_for_massive_candidate(
        vendor_source_id=1,
        raw_payload_id=100,
        symbol_id=10,
        candidate=candidate,
    )

    assert result.counts == {"aliases_inserted": 4}
    assert [(row["alias_type"], row["alias_value"], row["symbol_id"]) for row in connection.aliases] == [
        ("ticker", "AAPL", 10),
        ("cik", "0000320193", 10),
        ("composite_figi", "BBG000B9XRY4", 10),
        ("share_class_figi", "BBG001S5N8V8", 10),
    ]
    assert {row["source_vendor_id"] for row in connection.aliases} == {1}
    assert {row["source_payload_id"] for row in connection.aliases} == {100}


def test_repeated_alias_upsert_is_idempotent_without_duplicate_rows(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    candidate = map_massive_ticker_raw_record(raw_record())

    repo.upsert_aliases_for_massive_candidate(
        vendor_source_id=1, raw_payload_id=100, symbol_id=10, candidate=candidate
    )
    second = repo.upsert_aliases_for_massive_candidate(
        vendor_source_id=1, raw_payload_id=101, symbol_id=10, candidate=candidate
    )

    assert second.counts == {"aliases_unchanged": 4}
    assert len(connection.aliases) == 4
    assert {row["source_payload_id"] for row in connection.aliases} == {100}


def test_existing_alias_with_different_case_is_noop(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    connection.aliases.append(
        {
            "id": 1,
            "symbol_id": 10,
            "alias_type": "ticker",
            "alias_value": "aapl",
            "source_vendor_id": 1,
            "source_payload_id": 100,
            "active": True,
        }
    )
    connection.next_alias_id = 2
    candidate = map_massive_ticker_raw_record(
        raw_record(cik=None, composite_figi=None, share_class_figi=None)
    )

    result = repo.upsert_aliases_for_massive_candidate(
        vendor_source_id=1,
        raw_payload_id=101,
        symbol_id=10,
        candidate=candidate,
    )

    assert result.counts == {"aliases_unchanged": 1}
    assert connection.aliases == [
        {
            "id": 1,
            "symbol_id": 10,
            "alias_type": "ticker",
            "alias_value": "aapl",
            "source_vendor_id": 1,
            "source_payload_id": 100,
            "active": True,
        }
    ]


def test_missing_alias_fields_do_not_crash_or_write(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    candidate = map_massive_ticker_raw_record(
        raw_record(ticker=None, cik=None, composite_figi=None, share_class_figi=None)
    )

    result = repo.upsert_aliases_for_massive_candidate(
        vendor_source_id=1,
        raw_payload_id=100,
        symbol_id=10,
        candidate=candidate,
    )

    assert map_massive_alias_candidates(candidate) == ()
    assert result.counts == {}
    assert connection.aliases == []
    assert connection.touched_tables == []


def test_alias_upsert_does_not_touch_symbols_vendor_ids_exchanges_or_raw_tables(monkeypatch: Any) -> None:
    repo, connection = repository(monkeypatch)
    candidate = map_massive_ticker_raw_record(raw_record())

    repo.upsert_aliases_for_massive_candidate(
        vendor_source_id=1,
        raw_payload_id=100,
        symbol_id=10,
        candidate=candidate,
    )

    assert set(connection.touched_tables) == {"symbol_master.symbol_aliases"}
