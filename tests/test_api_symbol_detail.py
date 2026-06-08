from __future__ import annotations

import builtins
import importlib
import sys

from quant_symbols.api.testing import TestClient

from quant_symbols.api.app import create_app
from quant_symbols.api.symbols import SymbolTickerLookupParams


SYMBOL_DETAIL = {
    "id": 1,
    "canonical_ticker": "AAPL",
    "name": "Apple Inc.",
    "market": "stocks",
    "locale": "us",
    "currency": "USD",
    "asset_class": "equity",
    "security_type": "common_stock",
    "active": True,
    "cik": "0000320193",
    "composite_figi": "BBG000B9XRY4",
    "share_class_figi": "BBG001S5N8V8",
    "delisted_at": None,
    "primary_exchange": {
        "id": 2,
        "mic": "XNAS",
        "name": "Nasdaq Stock Market",
    },
}


def test_symbol_detail_by_id_returns_one_record_from_injected_lookup():
    seen_ids: list[int] = []

    def fake_detail(symbol_id: int) -> dict[str, object] | None:
        seen_ids.append(symbol_id)
        return SYMBOL_DETAIL

    client = TestClient(create_app(symbol_detail=fake_detail))

    response = client.get("/symbols/1")

    assert response.status_code == 200
    assert response.json() == SYMBOL_DETAIL
    assert seen_ids == [1]


def test_symbol_detail_by_id_returns_404_when_missing():
    client = TestClient(create_app(symbol_detail=lambda _symbol_id: None))

    response = client.get("/symbols/999999999")

    assert response.status_code == 404
    assert response.json() == {"status": "not_found", "error": "symbol not found"}


def test_symbol_detail_invalid_id_does_not_call_lookup():
    def fail_if_called(_symbol_id: int) -> dict[str, object] | None:
        raise AssertionError("symbol detail lookup should not be called")

    client = TestClient(create_app(symbol_detail=fail_if_called))

    response = client.get("/symbols/not-an-int")

    assert response.status_code == 422


def test_symbol_by_ticker_returns_one_record_from_injected_lookup():
    seen_params: list[SymbolTickerLookupParams] = []

    def fake_by_ticker(params: SymbolTickerLookupParams) -> dict[str, object] | None:
        seen_params.append(params)
        return SYMBOL_DETAIL

    client = TestClient(create_app(symbol_by_ticker=fake_by_ticker))

    response = client.get("/symbols/by-ticker/AAPL")

    assert response.status_code == 200
    assert response.json() == SYMBOL_DETAIL
    assert seen_params == [
        SymbolTickerLookupParams(ticker="AAPL", market="stocks", locale="us", active=True)
    ]


def test_symbol_by_ticker_passes_explicit_filters():
    seen_params: list[SymbolTickerLookupParams] = []

    def fake_by_ticker(params: SymbolTickerLookupParams) -> dict[str, object] | None:
        seen_params.append(params)
        return SYMBOL_DETAIL

    client = TestClient(create_app(symbol_by_ticker=fake_by_ticker))

    response = client.get("/symbols/by-ticker/META?market=otc&locale=global&active=false")

    assert response.status_code == 200
    assert seen_params == [
        SymbolTickerLookupParams(ticker="META", market="otc", locale="global", active=False)
    ]


def test_symbol_by_ticker_handles_lowercase_request_ticker():
    seen_params: list[SymbolTickerLookupParams] = []

    def fake_by_ticker(params: SymbolTickerLookupParams) -> dict[str, object] | None:
        seen_params.append(params)
        return {**SYMBOL_DETAIL, "canonical_ticker": "AAPL"}

    client = TestClient(create_app(symbol_by_ticker=fake_by_ticker))

    response = client.get("/symbols/by-ticker/aapl")

    assert response.status_code == 200
    assert response.json()["canonical_ticker"] == "AAPL"
    assert seen_params == [
        SymbolTickerLookupParams(ticker="aapl", market="stocks", locale="us", active=True)
    ]


def test_symbol_by_ticker_returns_404_when_missing():
    client = TestClient(create_app(symbol_by_ticker=lambda _params: None))

    response = client.get("/symbols/by-ticker/MISSING")

    assert response.status_code == 404
    assert response.json() == {"status": "not_found", "error": "symbol not found"}


def test_symbol_detail_primary_exchange_may_be_null():
    client = TestClient(
        create_app(symbol_detail=lambda _symbol_id: {**SYMBOL_DETAIL, "primary_exchange": None})
    )

    response = client.get("/symbols/4")

    assert response.status_code == 200
    assert response.json()["primary_exchange"] is None


def test_symbol_detail_repository_error_redacts_secret_bearing_database_url(monkeypatch):
    database_url = "postgresql+psycopg://user:super-secret@db.example.test:5432/quant"
    monkeypatch.setenv("DATABASE_URL", database_url)

    def fail_detail(_symbol_id: int) -> dict[str, object] | None:
        raise RuntimeError(f"could not connect to {database_url}")

    client = TestClient(create_app(symbol_detail=fail_detail))

    response = client.get("/symbols/1")

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert "super-secret" not in body["error"]
    assert database_url not in body["error"]
    assert "user:***@db.example.test:5432/quant" in body["error"]


def test_symbol_by_ticker_repository_error_redacts_secret_bearing_database_url(monkeypatch):
    database_url = "postgresql+psycopg://user:super-secret@db.example.test:5432/quant"
    monkeypatch.setenv("DATABASE_URL", database_url)

    def fail_by_ticker(_params: SymbolTickerLookupParams) -> dict[str, object] | None:
        raise RuntimeError(f"could not connect to {database_url}")

    client = TestClient(create_app(symbol_by_ticker=fail_by_ticker))

    response = client.get("/symbols/by-ticker/AAPL")

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert "super-secret" not in body["error"]
    assert database_url not in body["error"]
    assert "user:***@db.example.test:5432/quant" in body["error"]


def test_api_import_still_does_not_import_sqlalchemy_or_connect(monkeypatch):
    sys.modules.pop("quant_symbols.api.app", None)
    sys.modules.pop("quant_symbols.api.symbols", None)
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
