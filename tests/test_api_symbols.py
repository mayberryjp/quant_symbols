from __future__ import annotations

import builtins
import importlib
import sys

from quant_symbols.api.testing import TestClient

from quant_symbols.api.app import create_app
from quant_symbols.api.symbols import (
    SymbolCountParams,
    SymbolDelistedParams,
    SymbolHistoryParams,
    SymbolListParams,
    SymbolRecentParams,
    count_symbols,
)


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


def test_symbols_count_route_returns_default_count_from_injected_repository():
    seen_params: list[SymbolCountParams] = []

    def fake_count(params: SymbolCountParams) -> dict[str, object]:
        seen_params.append(params)
        return {
            "total": 12345,
            "filters": {
                "active": params.active,
                "market": params.market,
                "locale": params.locale,
                "q": params.q,
            },
        }

    client = TestClient(create_app(symbol_count=fake_count))

    response = client.get("/symbols/count")

    assert response.status_code == 200
    assert response.json() == {
        "total": 12345,
        "filters": {
            "active": None,
            "market": None,
            "locale": None,
            "q": None,
        },
    }
    assert seen_params == [SymbolCountParams()]


def test_symbols_count_route_parses_supported_filters():
    seen_params: list[SymbolCountParams] = []

    def fake_count(params: SymbolCountParams) -> dict[str, object]:
        seen_params.append(params)
        return {
            "total": 7,
            "filters": {
                "active": params.active,
                "market": params.market,
                "locale": params.locale,
                "q": params.q,
            },
        }

    client = TestClient(create_app(symbol_count=fake_count))

    response = client.get("/symbols/count?active=true&market=stocks&locale=us&q=AAPL")

    assert response.status_code == 200
    assert response.json() == {
        "total": 7,
        "filters": {
            "active": True,
            "market": "stocks",
            "locale": "us",
            "q": "AAPL",
        },
    }
    assert seen_params == [
        SymbolCountParams(active=True, market="stocks", locale="us", q="AAPL")
    ]


def test_symbols_count_route_strips_blank_text_query_to_null():
    seen_params: list[SymbolCountParams] = []

    def fake_count(params: SymbolCountParams) -> dict[str, object]:
        seen_params.append(params)
        return {
            "total": 2,
            "filters": {
                "active": params.active,
                "market": params.market,
                "locale": params.locale,
                "q": params.q,
            },
        }

    client = TestClient(create_app(symbol_count=fake_count))

    response = client.get("/symbols/count?q=%20%20")

    assert response.status_code == 200
    assert response.json()["filters"]["q"] is None
    assert seen_params == [SymbolCountParams()]


def test_symbols_count_route_rejects_pagination_params():
    def fail_if_called(_params: SymbolCountParams) -> dict[str, object]:
        raise AssertionError("symbol count should not be called for pagination params")

    client = TestClient(create_app(symbol_count=fail_if_called))

    response = client.get("/symbols/count?limit=1&offset=0")

    assert response.status_code == 422
    assert response.json() == {"detail": "limit and offset are not supported for symbol counts"}


def _fake_mapping_engine(rows: list[dict[str, object]], calls: list[dict[str, object]]):
    class FakeResult:
        def mappings(self) -> "FakeResult":
            return self

        def all(self) -> list[dict[str, object]]:
            return rows

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def execute(self, statement: object, values: dict[str, object]) -> FakeResult:
            calls.append({"statement": str(statement), "values": values})
            return FakeResult()

    class FakeEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

        def dispose(self) -> None:
            calls.append({"disposed": True})

    return FakeEngine()


def test_symbols_count_history_route_passes_params_and_returns_points():
    seen: list[SymbolHistoryParams] = []

    def fake_history(params: SymbolHistoryParams) -> dict[str, object]:
        seen.append(params)
        return {
            "bucket": "day",
            "filters": {"days": params.days, "market": params.market, "locale": params.locale},
            "points": [
                {"date": "2026-06-01", "total_symbols": 100, "new_symbols": 10, "delisted_symbols": 2},
            ],
        }

    client = TestClient(create_app(symbol_count_history=fake_history))

    response = client.get("/symbols/count/history?days=30&market=stocks&locale=us")

    assert response.status_code == 200
    assert seen == [SymbolHistoryParams(days=30, market="stocks", locale="us")]
    body = response.json()
    assert body["bucket"] == "day"
    assert body["points"] == [
        {"date": "2026-06-01", "total_symbols": 100, "new_symbols": 10, "delisted_symbols": 2}
    ]


def test_symbols_count_history_defaults_to_full_history_when_days_omitted():
    seen: list[SymbolHistoryParams] = []

    def fake_history(params: SymbolHistoryParams) -> dict[str, object]:
        seen.append(params)
        return {"bucket": "day", "filters": {"days": params.days}, "points": []}

    client = TestClient(create_app(symbol_count_history=fake_history))

    response = client.get("/symbols/count/history")

    assert response.status_code == 200
    assert seen == [SymbolHistoryParams(days=None, market=None, locale=None)]


def test_symbols_count_history_rejects_invalid_days():
    def fail(_params: SymbolHistoryParams) -> dict[str, object]:
        raise AssertionError("history should not be called for invalid days")

    client = TestClient(create_app(symbol_count_history=fail))

    response = client.get("/symbols/count/history?days=0")

    assert response.status_code == 422


def test_symbols_recent_route_passes_params_and_returns_items():
    seen: list[SymbolRecentParams] = []

    def fake_recent(params: SymbolRecentParams) -> dict[str, object]:
        seen.append(params)
        return {
            "items": [
                {
                    "id": 5,
                    "canonical_ticker": "NEWCO",
                    "name": "New Co",
                    "market": "stocks",
                    "locale": "us",
                    "currency": "USD",
                    "asset_class": "equity",
                    "security_type": "common_stock",
                    "active": True,
                    "primary_exchange": None,
                    "created_at": "2026-07-06T12:00:00+00:00",
                }
            ],
            "days": params.days,
            "limit": params.limit,
            "offset": params.offset,
            "count": 1,
        }

    client = TestClient(create_app(symbol_recent=fake_recent))

    response = client.get("/symbols/recent?days=14&market=stocks&limit=50&offset=5")

    assert response.status_code == 200
    assert seen == [
        SymbolRecentParams(days=14, market="stocks", locale=None, limit=50, offset=5)
    ]
    body = response.json()
    assert body["count"] == 1
    assert body["days"] == 14
    assert body["items"][0]["created_at"] == "2026-07-06T12:00:00+00:00"


def test_symbols_recent_defaults_days_to_seven():
    seen: list[SymbolRecentParams] = []

    def fake_recent(params: SymbolRecentParams) -> dict[str, object]:
        seen.append(params)
        return {
            "items": [],
            "days": params.days,
            "limit": params.limit,
            "offset": params.offset,
            "count": 0,
        }

    client = TestClient(create_app(symbol_recent=fake_recent))

    response = client.get("/symbols/recent")

    assert response.status_code == 200
    assert seen == [SymbolRecentParams(days=7, market=None, locale=None, limit=100, offset=0)]


def test_symbols_recent_rejects_invalid_days():
    def fail(_params: SymbolRecentParams) -> dict[str, object]:
        raise AssertionError("recent should not be called for invalid days")

    client = TestClient(create_app(symbol_recent=fail))

    response = client.get("/symbols/recent?days=-1")

    assert response.status_code == 422


def test_get_symbol_count_history_builds_windowed_series_query(monkeypatch):
    from datetime import date

    from quant_symbols.api.symbols import get_symbol_count_history

    calls: list[dict[str, object]] = []
    rows = [
        {"bucket_date": date(2026, 6, 1), "new_symbols": 10, "delisted_symbols": 1, "total_symbols": 100},
        {"bucket_date": date(2026, 6, 2), "new_symbols": 5, "delisted_symbols": 0, "total_symbols": 105},
    ]

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db/quant")
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: _fake_mapping_engine(rows, calls))

    result = get_symbol_count_history(SymbolHistoryParams(days=30, market="stocks", locale="us"))

    assert result["bucket"] == "day"
    assert result["filters"] == {"days": 30, "market": "stocks", "locale": "us"}
    assert result["points"] == [
        {"date": "2026-06-01", "total_symbols": 100, "new_symbols": 10, "delisted_symbols": 1},
        {"date": "2026-06-02", "total_symbols": 105, "new_symbols": 5, "delisted_symbols": 0},
    ]
    statement = str(calls[0]["statement"])
    assert "generate_series" in statement
    assert "s.market = :market" in statement
    assert "s.locale = :locale" in statement
    assert calls[0]["values"] == {"days": 30, "market": "stocks", "locale": "us"}


def test_get_symbol_count_history_without_days_or_filters(monkeypatch):
    from quant_symbols.api.symbols import get_symbol_count_history

    calls: list[dict[str, object]] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db/quant")
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: _fake_mapping_engine([], calls))

    result = get_symbol_count_history(SymbolHistoryParams())

    assert result["points"] == []
    assert result["filters"] == {"days": None, "market": None, "locale": None}
    statement = str(calls[0]["statement"])
    assert "s.market = :market" not in statement
    assert "s.locale = :locale" not in statement
    assert calls[0]["values"] == {"days": None}


def test_list_recent_symbols_builds_window_query_and_includes_created_at(monkeypatch):
    from datetime import datetime, timezone

    from quant_symbols.api.symbols import list_recent_symbols

    calls: list[dict[str, object]] = []
    rows = [
        {
            "id": 5,
            "canonical_ticker": "NEWCO",
            "name": "New Co",
            "market": "stocks",
            "locale": "us",
            "currency": "USD",
            "asset_class": "equity",
            "security_type": "common_stock",
            "active": True,
            "created_at": datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc),
            "exchange_id": None,
            "exchange_mic": None,
            "exchange_name": None,
        }
    ]

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db/quant")
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: _fake_mapping_engine(rows, calls))

    result = list_recent_symbols(SymbolRecentParams(days=14, market="stocks", limit=50, offset=5))

    assert result["days"] == 14
    assert result["count"] == 1
    assert result["items"][0]["canonical_ticker"] == "NEWCO"
    assert result["items"][0]["created_at"] == "2026-07-06T12:00:00+00:00"
    assert result["items"][0]["primary_exchange"] is None
    statement = str(calls[0]["statement"])
    assert "now() - (CAST(:days AS int) * interval '1 day')" in statement
    assert "ORDER BY s.created_at DESC" in statement
    assert "s.market = :market" in statement
    assert calls[0]["values"] == {"days": 14, "market": "stocks", "limit": 50, "offset": 5}


def test_symbols_delisted_route_passes_params_and_returns_items():
    seen: list[SymbolDelistedParams] = []

    def fake_delisted(params: SymbolDelistedParams) -> dict[str, object]:
        seen.append(params)
        return {
            "items": [
                {
                    "id": 9,
                    "canonical_ticker": "SBNY",
                    "name": "Signature Bank",
                    "market": "stocks",
                    "locale": "us",
                    "currency": "USD",
                    "asset_class": "equity",
                    "security_type": "common_stock",
                    "active": False,
                    "primary_exchange": None,
                    "delisted_at": "2026-07-05T00:00:00+00:00",
                }
            ],
            "days": params.days,
            "limit": params.limit,
            "offset": params.offset,
            "count": 1,
        }

    client = TestClient(create_app(symbol_delisted=fake_delisted))

    response = client.get("/symbols/delisted?days=30&market=stocks&limit=25&offset=10")

    assert response.status_code == 200
    assert seen == [
        SymbolDelistedParams(days=30, market="stocks", locale=None, limit=25, offset=10)
    ]
    body = response.json()
    assert body["count"] == 1
    assert body["days"] == 30
    assert body["items"][0]["delisted_at"] == "2026-07-05T00:00:00+00:00"


def test_symbols_delisted_defaults_days_to_seven():
    seen: list[SymbolDelistedParams] = []

    def fake_delisted(params: SymbolDelistedParams) -> dict[str, object]:
        seen.append(params)
        return {
            "items": [],
            "days": params.days,
            "limit": params.limit,
            "offset": params.offset,
            "count": 0,
        }

    client = TestClient(create_app(symbol_delisted=fake_delisted))

    response = client.get("/symbols/delisted")

    assert response.status_code == 200
    assert seen == [SymbolDelistedParams(days=7, market=None, locale=None, limit=100, offset=0)]


def test_symbols_delisted_rejects_invalid_days():
    def fail(_params: SymbolDelistedParams) -> dict[str, object]:
        raise AssertionError("delisted should not be called for invalid days")

    client = TestClient(create_app(symbol_delisted=fail))

    response = client.get("/symbols/delisted?days=0")

    assert response.status_code == 422


def test_list_delisted_symbols_builds_window_query_and_includes_delisted_at(monkeypatch):
    from datetime import datetime, timezone

    from quant_symbols.api.symbols import list_delisted_symbols

    calls: list[dict[str, object]] = []
    rows = [
        {
            "id": 9,
            "canonical_ticker": "SBNY",
            "name": "Signature Bank",
            "market": "stocks",
            "locale": "us",
            "currency": "USD",
            "asset_class": "equity",
            "security_type": "common_stock",
            "active": False,
            "delisted_at": datetime(2026, 7, 5, 0, 0, 0, tzinfo=timezone.utc),
            "exchange_id": None,
            "exchange_mic": None,
            "exchange_name": None,
        }
    ]

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db/quant")
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: _fake_mapping_engine(rows, calls))

    result = list_delisted_symbols(SymbolDelistedParams(days=30, market="stocks", limit=25, offset=10))

    assert result["days"] == 30
    assert result["count"] == 1
    assert result["items"][0]["canonical_ticker"] == "SBNY"
    assert result["items"][0]["delisted_at"] == "2026-07-05T00:00:00+00:00"
    assert result["items"][0]["primary_exchange"] is None
    statement = str(calls[0]["statement"])
    assert "s.delisted_at IS NOT NULL" in statement
    assert "now() - (CAST(:days AS int) * interval '1 day')" in statement
    assert "ORDER BY s.delisted_at DESC" in statement
    assert "s.market = :market" in statement
    assert calls[0]["values"] == {"days": 30, "market": "stocks", "limit": 25, "offset": 10}


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


def test_symbols_page_count_remains_number_of_returned_items():
    client = TestClient(
        create_app(
            symbol_list=lambda params: {
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
                        "primary_exchange": None,
                    }
                ],
                "limit": params.limit,
                "offset": params.offset,
                "count": 1,
            },
            symbol_count=lambda params: {
                "total": 5000,
                "filters": {
                    "active": params.active,
                    "market": params.market,
                    "locale": params.locale,
                    "q": params.q,
                },
            },
        )
    )

    list_response = client.get("/symbols?limit=1&active=true")
    count_response = client.get("/symbols/count?active=true")

    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1
    assert count_response.status_code == 200
    assert count_response.json()["total"] == 5000


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


def test_symbols_count_repository_error_redacts_secret_bearing_database_url(monkeypatch):
    database_url = "postgresql+psycopg://user:super-secret@db.example.test:5432/quant"
    monkeypatch.setenv("DATABASE_URL", database_url)

    def fail_count(_params: SymbolCountParams) -> dict[str, object]:
        raise RuntimeError(f"could not connect to {database_url}")

    client = TestClient(create_app(symbol_count=fail_count))

    response = client.get("/symbols/count")

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert "super-secret" not in body["error"]
    assert database_url not in body["error"]
    assert "user:***@db.example.test:5432/quant" in body["error"]


def test_count_symbols_uses_shared_filters_for_text_query(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeResult:
        def scalar_one(self) -> int:
            return 42

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, statement, values):
            calls.append({"statement": str(statement), "values": values})
            return FakeResult()

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            calls.append({"disposed": True})

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db/quant")

    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: FakeEngine())

    response = count_symbols(
        SymbolCountParams(active=True, market="stocks", locale="us", q="A_PL%")
    )

    assert response == {
        "total": 42,
        "filters": {
            "active": True,
            "market": "stocks",
            "locale": "us",
            "q": "A_PL%",
        },
    }
    assert "SELECT count(*) AS total" in calls[0]["statement"]
    assert "FROM symbols.symbols s" in calls[0]["statement"]
    assert "s.active = :active" in calls[0]["statement"]
    assert "s.market = :market" in calls[0]["statement"]
    assert "s.locale = :locale" in calls[0]["statement"]
    assert "lower(s.canonical_ticker) LIKE :q" in calls[0]["statement"]
    assert "lower(coalesce(s.name, '')) LIKE :q" in calls[0]["statement"]
    assert "LIMIT" not in calls[0]["statement"]
    assert "OFFSET" not in calls[0]["statement"]
    assert calls[0]["values"] == {
        "active": True,
        "market": "stocks",
        "locale": "us",
        "q": "%a\\_pl\\%%",
    }
