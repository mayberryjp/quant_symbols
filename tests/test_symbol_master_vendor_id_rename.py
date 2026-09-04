from __future__ import annotations

from typing import Any

import quant_symbols.symbol_master.repository as repository_module
from quant_symbols.symbol_master.massive_mapper import SymbolCandidate
from quant_symbols.symbol_master.repository import SymbolMasterRepository


class FakeUniqueViolation(Exception):
    """Stand-in for psycopg.errors.UniqueViolation raised by the fake connection."""


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


class ConstraintEnforcingConnection:
    """Fake connection for the live ``upsert_candidate`` path.

    Models the ``symbol_vendor_ids_vendor_asset_unique_idx`` partial unique index
    so a duplicate ``(vendor_source_id, vendor_asset_id)`` insert raises, exactly as
    PostgreSQL would. This lets the renamed-ticker regression fail loudly if the
    repository ever reverts to looking up vendor identities by symbol only.
    """

    def __init__(self) -> None:
        self.symbols: list[dict[str, Any]] = []
        self.vendor_ids: list[dict[str, Any]] = []
        self.next_symbol_id = 1
        self.next_vendor_id = 1

    def execute(self, statement: object, params: dict[str, Any] | None = None) -> FakeResult:
        sql = " ".join(str(statement).lower().split())
        params = params or {}

        if "select * from symbols.symbols where composite_figi = :figi" in sql:
            return FakeResult(
                [dict(row) for row in self.symbols if row["composite_figi"] == params["figi"]]
            )

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
                "delisted_at": params["delisted_at"],
            }
            self.next_symbol_id += 1
            self.symbols.append(row)
            return FakeResult([{"id": row["id"]}])

        if "update symbols.symbols set name" in sql:
            row = next(row for row in self.symbols if row["id"] == params["id"])
            for key in (
                "name",
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
            self._enforce_vendor_asset_unique(params)
            row = {
                "id": self.next_vendor_id,
                "symbol_id": params["symbol_id"],
                "vendor_source_id": params["vendor_source_id"],
                "vendor_symbol": params["vendor_symbol"],
                "vendor_asset_id": params["vendor_asset_id"],
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
            row["active"] = params["active"]
            return FakeResult([])

        raise AssertionError(f"unexpected SQL: {statement}")

    def _enforce_vendor_asset_unique(self, params: dict[str, Any]) -> None:
        asset_id = params["vendor_asset_id"]
        if asset_id is None:
            return
        for row in self.vendor_ids:
            if (
                row["vendor_source_id"] == params["vendor_source_id"]
                and row["vendor_asset_id"] == asset_id
            ):
                raise FakeUniqueViolation(
                    'duplicate key value violates unique constraint '
                    '"symbol_vendor_ids_vendor_asset_unique_idx"'
                )


def _candidate(*, source_ticker: str, composite_figi: str | None) -> SymbolCandidate:
    return SymbolCandidate(
        canonical_ticker=source_ticker.upper(),
        source_ticker=source_ticker,
        name="Example Corp",
        market="stocks",
        locale="us",
        currency="USD",
        primary_exchange=None,
        asset_class="equity",
        security_type="common_stock",
        source_security_type="CS",
        active=True,
        cik=None,
        composite_figi=composite_figi,
        share_class_figi=None,
        delisted_at=None,
        aliases=(),
        raw={},
    )


def _repository(monkeypatch: Any) -> tuple[SymbolMasterRepository, ConstraintEnforcingConnection]:
    monkeypatch.setattr(repository_module, "_text", lambda sql: sql)
    connection = ConstraintEnforcingConnection()
    return SymbolMasterRepository(connection), connection


def test_renamed_ticker_updates_vendor_identity_instead_of_duplicate_insert(monkeypatch: Any) -> None:
    """A ticker rename keeps the same composite_figi; the live sync must update the
    existing vendor identity rather than insert a duplicate that violates
    ``symbol_vendor_ids_vendor_asset_unique_idx`` (the production failure)."""
    repo, connection = _repository(monkeypatch)

    original = _candidate(source_ticker="OLD", composite_figi="BBG00W5F8CQ7")
    repo.upsert_candidate(vendor_source_id=1, run_id=61, raw_payload_id=1000, candidate=original)

    renamed = _candidate(source_ticker="AFGR", composite_figi="BBG00W5F8CQ7")
    counts = repo.upsert_candidate(vendor_source_id=1, run_id=62, raw_payload_id=1001, candidate=renamed)

    assert len(connection.vendor_ids) == 1
    assert connection.vendor_ids[0]["symbol_id"] == 1
    assert connection.vendor_ids[0]["vendor_symbol"] == "AFGR"
    assert connection.vendor_ids[0]["vendor_asset_id"] == "BBG00W5F8CQ7"
    assert counts["vendor_ids_updated"] == 1


def test_repeated_upsert_candidate_is_idempotent(monkeypatch: Any) -> None:
    repo, connection = _repository(monkeypatch)
    candidate = _candidate(source_ticker="AAPL", composite_figi="BBG000B9XRY4")

    repo.upsert_candidate(vendor_source_id=1, run_id=1, raw_payload_id=1, candidate=candidate)
    counts = repo.upsert_candidate(vendor_source_id=1, run_id=2, raw_payload_id=2, candidate=candidate)

    assert len(connection.vendor_ids) == 1
    assert counts["vendor_ids_unchanged"] == 1
