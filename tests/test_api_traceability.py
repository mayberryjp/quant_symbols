from __future__ import annotations

import builtins
import importlib
import sys

from quant_symbols.api.testing import TestClient

from quant_symbols.api.app import create_app
from quant_symbols.api.symbols import SymbolTickerLookupParams
from quant_symbols.api.traceability import RawPayloadListParams, VendorRunListParams


ALIAS_RESPONSE = {
    "symbol_id": 1,
    "items": [
        {
            "id": 10,
            "alias_type": "ticker",
            "alias_value": "AAPL",
            "active": True,
            "source_vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
            "source_payload_id": 100,
            "valid_from": None,
            "valid_to": None,
        }
    ],
    "count": 1,
}


VENDOR_IDS_RESPONSE = {
    "symbol_id": 1,
    "items": [
        {
            "id": 20,
            "vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
            "vendor_symbol": "AAPL",
            "vendor_asset_id": "BBG000B9XRY4",
            "active": True,
            "first_seen_run_id": 5,
            "first_seen_payload_id": 100,
            "last_seen_run_id": 5,
            "last_seen_payload_id": 100,
        }
    ],
    "count": 1,
}


RAW_PAYLOADS_RESPONSE = {
    "symbol_id": 1,
    "items": [
        {
            "id": 100,
            "vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
            "vendor_api_run_id": 5,
            "provider_record_id": "AAPL",
            "provider_ticker": "AAPL",
            "received_at": "2026-06-07T09:00:00+00:00",
            "payload": {"ticker": "AAPL"},
        }
    ],
    "limit": 50,
    "offset": 0,
    "count": 1,
}


VENDOR_RUN_RESPONSE = {
    "id": 5,
    "vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
    "endpoint": "/v3/reference/tickers",
    "status": "succeeded",
    "started_at": "2026-06-07T09:00:00+00:00",
    "finished_at": "2026-06-07T09:00:10+00:00",
    "records_seen": 5,
    "records_inserted": 5,
    "records_failed": 0,
    "error_message": None,
}


def test_symbol_aliases_route_returns_aliases_from_injected_lookup():
    seen_ids: list[int] = []

    def fake_aliases(symbol_id: int) -> dict[str, object] | None:
        seen_ids.append(symbol_id)
        return ALIAS_RESPONSE

    client = TestClient(create_app(symbol_aliases=fake_aliases))

    response = client.get("/symbols/1/aliases")

    assert response.status_code == 200
    assert response.json() == ALIAS_RESPONSE
    assert seen_ids == [1]


def test_symbol_vendor_ids_route_returns_vendor_ids_from_injected_lookup():
    seen_ids: list[int] = []

    def fake_vendor_ids(symbol_id: int) -> dict[str, object] | None:
        seen_ids.append(symbol_id)
        return VENDOR_IDS_RESPONSE

    client = TestClient(create_app(symbol_vendor_ids=fake_vendor_ids))

    response = client.get("/symbols/1/vendor-ids")

    assert response.status_code == 200
    assert response.json() == VENDOR_IDS_RESPONSE
    assert seen_ids == [1]


def test_symbol_raw_payloads_route_returns_paginated_payloads_from_injected_lookup():
    seen_params: list[RawPayloadListParams] = []

    def fake_raw_payloads(params: RawPayloadListParams) -> dict[str, object] | None:
        seen_params.append(params)
        return {**RAW_PAYLOADS_RESPONSE, "limit": params.limit, "offset": params.offset}

    client = TestClient(create_app(symbol_raw_payloads=fake_raw_payloads))

    response = client.get("/symbols/1/raw-payloads?limit=5&offset=10")

    assert response.status_code == 200
    assert response.json()["limit"] == 5
    assert response.json()["offset"] == 10
    assert seen_params == [RawPayloadListParams(symbol_id=1, limit=5, offset=10)]


def test_symbol_raw_payloads_limit_max_is_enforced():
    def fail_if_called(_params: RawPayloadListParams) -> dict[str, object] | None:
        raise AssertionError("raw payload lookup should not be called")

    client = TestClient(create_app(symbol_raw_payloads=fail_if_called))

    response = client.get("/symbols/1/raw-payloads?limit=101")

    assert response.status_code == 422


def test_vendor_runs_route_parses_filters_and_defaults():
    seen_params: list[VendorRunListParams] = []

    def fake_vendor_runs(params: VendorRunListParams) -> dict[str, object]:
        seen_params.append(params)
        return {"items": [VENDOR_RUN_RESPONSE], "limit": params.limit, "offset": params.offset, "count": 1}

    client = TestClient(create_app(vendor_runs=fake_vendor_runs))

    response = client.get("/vendor-runs")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert seen_params == [VendorRunListParams(vendor="massive", limit=20, offset=0)]

    response = client.get(
        "/vendor-runs?vendor=massive&endpoint=/v3/reference/tickers"
        "&status=succeeded&limit=5&offset=10"
    )

    assert response.status_code == 200
    assert seen_params[-1] == VendorRunListParams(
        vendor="massive",
        endpoint="/v3/reference/tickers",
        status="succeeded",
        limit=5,
        offset=10,
    )


def test_vendor_runs_limit_max_and_status_values_are_enforced():
    def fail_if_called(_params: VendorRunListParams) -> dict[str, object]:
        raise AssertionError("vendor run list should not be called")

    client = TestClient(create_app(vendor_runs=fail_if_called))

    assert client.get("/vendor-runs?limit=101").status_code == 422
    assert client.get("/vendor-runs?status=unknown").status_code == 422


def test_vendor_run_detail_returns_one_run_and_404_when_missing():
    seen_ids: list[int] = []

    def fake_detail(run_id: int) -> dict[str, object] | None:
        seen_ids.append(run_id)
        if run_id == 5:
            return {**VENDOR_RUN_RESPONSE, "request_params": {"market": "stocks"}, "raw_payload_count": 5}
        return None

    client = TestClient(create_app(vendor_run_detail=fake_detail))

    response = client.get("/vendor-runs/5")

    assert response.status_code == 200
    assert response.json()["raw_payload_count"] == 5
    assert response.json()["request_params"] == {"market": "stocks"}

    response = client.get("/vendor-runs/999")

    assert response.status_code == 404
    assert response.json() == {"status": "not_found", "error": "vendor run not found"}
    assert seen_ids == [5, 999]


def test_symbol_traceability_missing_symbol_and_empty_rows_are_consistent():
    client = TestClient(
        create_app(
            symbol_aliases=lambda symbol_id: None if symbol_id == 404 else {"symbol_id": symbol_id, "items": [], "count": 0},
            symbol_vendor_ids=lambda symbol_id: None if symbol_id == 404 else {"symbol_id": symbol_id, "items": [], "count": 0},
            symbol_raw_payloads=lambda params: None
            if params.symbol_id == 404
            else {
                "symbol_id": params.symbol_id,
                "items": [],
                "limit": params.limit,
                "offset": params.offset,
                "count": 0,
            },
        )
    )

    assert client.get("/symbols/404/aliases").status_code == 404
    assert client.get("/symbols/404/vendor-ids").status_code == 404
    assert client.get("/symbols/404/raw-payloads").status_code == 404

    assert client.get("/symbols/1/aliases").json() == {"symbol_id": 1, "items": [], "count": 0}
    assert client.get("/symbols/1/vendor-ids").json() == {"symbol_id": 1, "items": [], "count": 0}
    assert client.get("/symbols/1/raw-payloads").json() == {
        "symbol_id": 1,
        "items": [],
        "limit": 50,
        "offset": 0,
        "count": 0,
    }


def test_traceability_repository_error_redacts_secret_bearing_database_url(monkeypatch):
    database_url = "postgresql+psycopg://user:super-secret@db.example.test:5432/quant"
    monkeypatch.setenv("DATABASE_URL", database_url)

    def fail_aliases(_symbol_id: int) -> dict[str, object] | None:
        raise RuntimeError(f"could not connect to {database_url}")

    client = TestClient(create_app(symbol_aliases=fail_aliases))

    response = client.get("/symbols/1/aliases")

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert "super-secret" not in body["error"]
    assert database_url not in body["error"]
    assert "user:***@db.example.test:5432/quant" in body["error"]


def test_api_import_still_does_not_import_sqlalchemy_or_connect(monkeypatch):
    sys.modules.pop("quant_symbols.api.app", None)
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


def test_traceability_routes_preserve_existing_symbol_routes():
    seen: list[str] = []

    def fake_detail(symbol_id: int) -> dict[str, object] | None:
        seen.append(f"id:{symbol_id}")
        return {"id": symbol_id}

    def fake_by_ticker(params: SymbolTickerLookupParams) -> dict[str, object] | None:
        seen.append(f"ticker:{params.ticker}")
        return {"canonical_ticker": params.ticker}

    def fake_aliases(symbol_id: int) -> dict[str, object] | None:
        seen.append(f"aliases:{symbol_id}")
        return {"symbol_id": symbol_id, "items": [], "count": 0}

    client = TestClient(
        create_app(
            symbol_detail=fake_detail,
            symbol_by_ticker=fake_by_ticker,
            symbol_aliases=fake_aliases,
        )
    )

    assert client.get("/symbols/1").json() == {"id": 1}
    assert client.get("/symbols/by-ticker/AAPL").json() == {"canonical_ticker": "AAPL"}
    assert client.get("/symbols/1/aliases").json() == {"symbol_id": 1, "items": [], "count": 0}
    assert seen == ["id:1", "ticker:AAPL", "aliases:1"]
