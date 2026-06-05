from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from quant_symbols.symbol_master.massive_raw_storage import MassiveRawPayloadStorageJob
from quant_symbols.vendors.massive.models import TickerReferencePage


FIXTURES = Path(__file__).parent / "fixtures" / "massive"
REQUEST_URL = "fixture://massive/raw-storage"


class FakeEngine:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {
            "vendor_sources": {},
            "runs": [],
            "raw_payloads": [],
            "next_run_id": 1,
            "next_payload_id": 1,
            "insert_error": None,
        }

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self.state)


@dataclass
class FakeConnection:
    state: dict[str, Any]


class FakeTransaction:
    def __init__(self, state: dict[str, Any]) -> None:
        self.connection = FakeConnection(state)

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *_exc: object) -> None:
        return None


class FakeRepository:
    def __init__(self, connection: FakeConnection) -> None:
        self.state = connection.state

    def ensure_vendor_source(self, *, code: str, name: str, base_url: str | None = None) -> int:
        self.state["vendor_sources"][code] = {"id": 1, "code": code, "name": name, "base_url": base_url}
        return 1

    def start_run(self, *, vendor_source_id: int, endpoint: str, request_params: dict[str, Any]) -> int:
        run_id = self.state["next_run_id"]
        self.state["next_run_id"] += 1
        self.state["runs"].append(
            {
                "id": run_id,
                "vendor_source_id": vendor_source_id,
                "endpoint": endpoint,
                "request_params": request_params,
                "status": "running",
                "records_seen": 0,
                "records_inserted": 0,
                "records_failed": 0,
                "error_message": None,
            }
        )
        return run_id

    def insert_raw_payload(
        self,
        *,
        vendor_source_id: int,
        run_id: int,
        provider_ticker: str,
        payload: dict[str, Any],
    ) -> object:
        error = self.state["insert_error"]
        if error is not None:
            raise RuntimeError(error)
        payload_id = self.state["next_payload_id"]
        self.state["next_payload_id"] += 1
        row = {
            "id": payload_id,
            "vendor_source_id": vendor_source_id,
            "vendor_api_run_id": run_id,
            "provider_record_id": provider_ticker,
            "provider_ticker": provider_ticker,
            "payload": dict(payload),
        }
        self.state["raw_payloads"].append(row)
        return object()

    def finish_run(
        self,
        *,
        run_id: int,
        status: str,
        records_seen: int,
        records_inserted: int,
        records_failed: int,
        error_message: str | None = None,
    ) -> None:
        run = next(row for row in self.state["runs"] if row["id"] == run_id)
        run.update(
            {
                "status": status,
                "records_seen": records_seen,
                "records_inserted": records_inserted,
                "records_failed": records_failed,
                "error_message": error_message,
            }
        )


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def page(*records: dict[str, object]) -> TickerReferencePage:
    return TickerReferencePage.from_payload(
        {"status": "OK", "request_id": "fixture", "count": len(records), "results": list(records)},
        request_url=REQUEST_URL,
    )


def test_raw_storage_creates_run_and_inserts_raw_payload_rows() -> None:
    engine = FakeEngine()
    aapl = fixture("active_stock.json")
    spy = fixture("etf.json")
    job = MassiveRawPayloadStorageJob(engine=engine, repository_factory=FakeRepository)

    summary = job.store_pages(
        [page(aapl, spy)],
        request_params={"mode": "fixture", "ticker": "AAPL", "limit": 2, "apiKey": "test-secret"},
    )

    assert summary.status == "ok"
    assert summary.run_id == 1
    assert summary.pages == 1
    assert summary.records_seen == 2
    assert summary.raw_payloads_inserted == 2
    assert engine.state["vendor_sources"]["massive"]["name"] == "Massive / Polygon"
    assert engine.state["runs"] == [
        {
            "id": 1,
            "vendor_source_id": 1,
            "endpoint": "/v3/reference/tickers",
            "request_params": {"mode": "fixture", "ticker": "AAPL", "limit": 2, "apiKey": "<redacted>"},
            "status": "succeeded",
            "records_seen": 2,
            "records_inserted": 2,
            "records_failed": 0,
            "error_message": None,
        }
    ]
    assert [row["provider_ticker"] for row in engine.state["raw_payloads"]] == ["AAPL", "SPY"]
    assert [row["vendor_api_run_id"] for row in engine.state["raw_payloads"]] == [1, 1]
    assert engine.state["raw_payloads"][0]["payload"] == aapl
    assert engine.state["raw_payloads"][1]["payload"] == spy
    assert "test-secret" not in repr(engine.state["runs"])


def test_raw_storage_failure_marks_run_failed_without_leaking_secrets(monkeypatch) -> None:
    monkeypatch.setenv("MASSIVE_API_KEY", "env-secret")
    engine = FakeEngine()
    engine.state["insert_error"] = "insert failed apiKey=env-secret token=request-secret"
    job = MassiveRawPayloadStorageJob(engine=engine, repository_factory=FakeRepository)

    summary = job.store_pages(
        [page(fixture("active_stock.json"))],
        request_params={"mode": "fixture", "api_key": "request-secret"},
    )

    run = engine.state["runs"][0]
    assert summary.status == "failed"
    assert summary.run_id == 1
    assert summary.records_seen == 1
    assert summary.raw_payloads_inserted == 0
    assert summary.errors == 1
    assert run["status"] == "failed"
    assert run["records_seen"] == 1
    assert run["records_inserted"] == 0
    assert run["records_failed"] == 1
    assert "env-secret" not in str(run["error_message"])
    assert "request-secret" not in str(run["error_message"])
    assert "apiKey=<redacted>" in str(run["error_message"])
    assert "token=<redacted>" in str(run["error_message"])
    assert run["request_params"] == {"mode": "fixture", "api_key": "<redacted>"}
    assert engine.state["raw_payloads"] == []


def test_raw_storage_is_append_only_across_repeated_runs() -> None:
    engine = FakeEngine()
    job = MassiveRawPayloadStorageJob(engine=engine, repository_factory=FakeRepository)

    first = job.store_pages([page(fixture("active_stock.json"))], request_params={"mode": "fixture"})
    second = job.store_pages([page(fixture("active_stock.json"))], request_params={"mode": "fixture"})

    assert first.run_id == 1
    assert second.run_id == 2
    assert [run["status"] for run in engine.state["runs"]] == ["succeeded", "succeeded"]
    assert [row["vendor_api_run_id"] for row in engine.state["raw_payloads"]] == [1, 2]
