from __future__ import annotations

import builtins
import importlib
import sys

from quant_symbols.api.testing import TestClient

from quant_symbols.api.app import create_app
from quant_symbols.api.sync_status import SyncLatestParams, SyncRunListParams
from quant_symbols.api.traceability import VendorRunListParams


SYNC_RUN_SUMMARY = {
    "id": 5,
    "vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
    "endpoint": "/v3/reference/tickers",
    "run_status": "succeeded",
    "started_at": "2026-06-07T09:00:00+00:00",
    "finished_at": "2026-06-07T09:00:10+00:00",
    "records_seen": 5,
    "records_inserted": 5,
    "records_failed": 0,
    "error_message": None,
    "raw_payload_count": 5,
}


SYNC_RUN_DETAIL = {
    **SYNC_RUN_SUMMARY,
    "request_params": {"market": "stocks"},
}


def test_sync_latest_returns_latest_run_from_injected_lookup():
    seen_params: list[SyncLatestParams] = []

    def fake_latest(params: SyncLatestParams) -> dict[str, object] | None:
        seen_params.append(params)
        return SYNC_RUN_SUMMARY

    client = TestClient(create_app(sync_latest=fake_latest))

    response = client.get("/sync/latest?vendor=massive&endpoint=/v3/reference/tickers")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "latest": SYNC_RUN_SUMMARY}
    assert seen_params == [
        SyncLatestParams(vendor="massive", endpoint="/v3/reference/tickers")
    ]


def test_sync_latest_passes_default_filters():
    seen_params: list[SyncLatestParams] = []

    def fake_latest(params: SyncLatestParams) -> dict[str, object] | None:
        seen_params.append(params)
        return SYNC_RUN_SUMMARY

    client = TestClient(create_app(sync_latest=fake_latest))

    response = client.get("/sync/latest")

    assert response.status_code == 200
    assert seen_params == [
        SyncLatestParams(vendor="massive", endpoint="/v3/reference/tickers")
    ]


def test_sync_latest_returns_404_when_missing():
    client = TestClient(create_app(sync_latest=lambda _params: None))

    response = client.get("/sync/latest")

    assert response.status_code == 404
    assert response.json() == {"status": "not_found", "error": "sync run not found"}


def test_sync_runs_parses_filters_and_returns_bounded_list():
    seen_params: list[SyncRunListParams] = []

    def fake_runs(params: SyncRunListParams) -> dict[str, object]:
        seen_params.append(params)
        return {"items": [SYNC_RUN_SUMMARY], "limit": params.limit, "offset": params.offset, "count": 1}

    client = TestClient(create_app(sync_runs=fake_runs))

    response = client.get("/sync/runs")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert seen_params == [
        SyncRunListParams(
            vendor="massive",
            endpoint="/v3/reference/tickers",
            limit=20,
            offset=0,
        )
    ]

    response = client.get(
        "/sync/runs?vendor=massive&endpoint=/v3/reference/tickers"
        "&status=succeeded&limit=5&offset=10"
    )

    assert response.status_code == 200
    assert seen_params[-1] == SyncRunListParams(
        vendor="massive",
        endpoint="/v3/reference/tickers",
        status="succeeded",
        limit=5,
        offset=10,
    )


def test_sync_runs_limit_max_is_enforced():
    def fail_if_called(_params: SyncRunListParams) -> dict[str, object]:
        raise AssertionError("sync run list should not be called")

    client = TestClient(create_app(sync_runs=fail_if_called))

    response = client.get("/sync/runs?limit=101")

    assert response.status_code == 422


def test_sync_runs_rejects_invalid_status():
    def fail_if_called(_params: SyncRunListParams) -> dict[str, object]:
        raise AssertionError("sync run list should not be called")

    client = TestClient(create_app(sync_runs=fail_if_called))

    response = client.get("/sync/runs?status=unknown")

    assert response.status_code == 422


def test_sync_run_detail_returns_one_run_from_injected_lookup():
    seen_ids: list[int] = []

    def fake_detail(run_id: int) -> dict[str, object] | None:
        seen_ids.append(run_id)
        return SYNC_RUN_DETAIL

    client = TestClient(create_app(sync_run_detail=fake_detail))

    response = client.get("/sync/runs/5")

    assert response.status_code == 200
    assert response.json() == SYNC_RUN_DETAIL
    assert seen_ids == [5]


def test_sync_run_detail_returns_404_when_missing():
    client = TestClient(create_app(sync_run_detail=lambda _run_id: None))

    response = client.get("/sync/runs/999999999")

    assert response.status_code == 404
    assert response.json() == {"status": "not_found", "error": "sync run not found"}


def test_sync_repository_error_redacts_secret_bearing_database_url(monkeypatch):
    database_url = "postgresql+psycopg://user:super-secret@db.example.test:5432/quant"
    monkeypatch.setenv("DATABASE_URL", database_url)

    def fail_latest(_params: SyncLatestParams) -> dict[str, object] | None:
        raise RuntimeError(f"could not connect to {database_url}")

    client = TestClient(create_app(sync_latest=fail_latest))

    response = client.get("/sync/latest")

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert "super-secret" not in body["error"]
    assert database_url not in body["error"]
    assert "user:***@db.example.test:5432/quant" in body["error"]


def test_api_import_still_does_not_import_sqlalchemy_or_connect(monkeypatch):
    sys.modules.pop("quant_symbols.api.app", None)
    sys.modules.pop("quant_symbols.api.sync_status", None)
    sys.modules.pop("quant_symbols.api.symbols", None)
    sys.modules.pop("quant_symbols.api.traceability", None)
    sys.modules.pop("quant_symbols.api.readiness", None)
    sys.modules.pop("quant_symbols.api", None)

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "sqlalchemy" or name.startswith("sqlalchemy."):
            raise AssertionError("API import should not import SQLAlchemy")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module("quant_symbols.api.app")

    assert module.app.title == "quant-symbols-api"


def test_sync_routes_preserve_existing_vendor_and_symbol_routes():
    seen: list[str] = []

    def fake_sync_detail(run_id: int) -> dict[str, object] | None:
        seen.append(f"sync:{run_id}")
        return {"id": run_id, "run_status": "succeeded"}

    def fake_vendor_runs(params: VendorRunListParams) -> dict[str, object]:
        seen.append(f"vendor-runs:{params.limit}")
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    def fake_symbol_detail(symbol_id: int) -> dict[str, object] | None:
        seen.append(f"symbol:{symbol_id}")
        return {"id": symbol_id}

    client = TestClient(
        create_app(
            sync_run_detail=fake_sync_detail,
            vendor_runs=fake_vendor_runs,
            symbol_detail=fake_symbol_detail,
        )
    )

    assert client.get("/sync/runs/5").json() == {"id": 5, "run_status": "succeeded"}
    assert client.get("/vendor-runs?limit=3").json() == {
        "items": [],
        "limit": 3,
        "offset": 0,
        "count": 0,
    }
    assert client.get("/symbols/1").json() == {"id": 1}
    assert seen == ["sync:5", "vendor-runs:3", "symbol:1"]
