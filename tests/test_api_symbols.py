from __future__ import annotations

import builtins
import importlib
import sys

from fastapi.testclient import TestClient

from quant_symbols.api.app import create_app
from quant_symbols.api.symbols import SymbolListParams


def test_symbols_route_returns_list_from_injected_repository():
    def fake_list(params: SymbolListParams) -> dict[str, object]:
        assert params == SymbolListParams(
            active=True,
            market="stocks",
            locale="us",
            q="AAPL",
            limit=100,
            offset=0,
        )
        return {
            "items": [
                {
                    "id": 1,
                    "canonical_ticker": "AAPL",
                    "name": "Apple Inc.",
                    "market": "stocks",
                    "locale": "us",
                    "currency": "USD",
                    "asset_class": "equity",
                    "security_type": "common_stock",
                    "active": True,
                    "primary_exchange": {
                        "id": 2,
                        "mic": "XNAS",
                        "name": "Nasdaq Stock Market",
                    },
                }
            ],
            "limit": params.limit,
            "offset": params.offset,
            "count": 1,
        }

    client = TestClient(create_app(symbol_list=fake_list))

    response = client.get(
        "/symbols",
        params={
            "active": "true",
            "market": "stocks",
            "locale": "us",
            "q": "AAPL",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": 1,
                "canonical_ticker": "AAPL",
                "name": "Apple Inc.",
                "market": "stocks",
                "locale": "us",
                "currency": "USD",
                "asset_class": "equity",
                "security_type": "common_stock",
                "active": True,
                "primary_exchange": {
                    "id": 2,
                    "mic": "XNAS",
                    "name": "Nasdaq Stock Market",
                },
            }
        ],
        "limit": 100,
        "offset": 0,
        "count": 1,
    }


def test_symbols_defaults_limit_and_offset_when_omitted():
    seen_params: list[SymbolListParams] = []

    def fake_list(params: SymbolListParams) -> dict[str, object]:
        seen_params.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(symbol_list=fake_list))

    response = client.get("/symbols")

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 100, "offset": 0, "count": 0}
    assert seen_params == [SymbolListParams(limit=100, offset=0)]


def test_symbols_parses_filters_and_pagination():
    seen_params: list[SymbolListParams] = []

    def fake_list(params: SymbolListParams) -> dict[str, object]:
        seen_params.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(symbol_list=fake_list))

    response = client.get(
        "/symbols?active=false&market=otc&locale=us&q=bank&limit=25&offset=50"
    )

    assert response.status_code == 200
    assert seen_params == [
        SymbolListParams(
            active=False,
            market="otc",
            locale="us",
            q="bank",
            limit=25,
            offset=50,
        )
    ]


def test_symbols_limit_max_is_enforced():
    def fail_if_called(_params: SymbolListParams) -> dict[str, object]:
        raise AssertionError("symbol list should not be called for invalid params")

    client = TestClient(create_app(symbol_list=fail_if_called))

    response = client.get("/symbols?limit=501")

    assert response.status_code == 422


def test_symbols_empty_result_shape_is_stable():
    client = TestClient(
        create_app(
            symbol_list=lambda params: {
                "items": [],
                "limit": params.limit,
                "offset": params.offset,
                "count": 0,
            }
        )
    )

    response = client.get("/symbols?limit=5")

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 5, "offset": 0, "count": 0}


def test_symbols_primary_exchange_may_be_null():
    def fake_list(params: SymbolListParams) -> dict[str, object]:
        return {
            "items": [
                {
                    "id": 4,
                    "canonical_ticker": "SBNY",
                    "name": "Signature Bank",
                    "market": "stocks",
                    "locale": "us",
                    "currency": "USD",
                    "asset_class": "equity",
                    "security_type": "common_stock",
                    "active": False,
                    "primary_exchange": None,
                }
            ],
            "limit": params.limit,
            "offset": params.offset,
            "count": 1,
        }

    client = TestClient(create_app(symbol_list=fake_list))

    response = client.get("/symbols?active=false")

    assert response.status_code == 200
    assert response.json()["items"][0]["primary_exchange"] is None


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


def test_symbols_repository_error_redacts_secret_bearing_database_url(monkeypatch):
    database_url = "postgresql+psycopg://user:super-secret@db.example.test:5432/quant"
    monkeypatch.setenv("DATABASE_URL", database_url)

    def fail_list(_params: SymbolListParams) -> dict[str, object]:
        raise RuntimeError(f"could not connect to {database_url}")

    client = TestClient(create_app(symbol_list=fail_list))

    response = client.get("/symbols")

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert "super-secret" not in body["error"]
    assert database_url not in body["error"]
    assert "user:***@db.example.test:5432/quant" in body["error"]
