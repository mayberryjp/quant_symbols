from __future__ import annotations

from decimal import Decimal

from quant_symbols.api.app import create_app
from quant_symbols.api.readiness import ReadinessStatus
from quant_symbols.api.testing import TestClient
from quant_symbols.positions.service import OrderCreateParams, PositionListParams, PortfolioCreateParams


def test_positions_health_does_not_call_database_readiness():
    def fail_if_called() -> ReadinessStatus:
        raise AssertionError("readiness should not be called")

    client = TestClient(create_app(readiness_check=fail_if_called))

    response = client.get("/positions/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "quant-positions-api"}


def test_positions_ready_uses_existing_readiness_contract():
    client = TestClient(
        create_app(
            readiness_check=lambda: ReadinessStatus(
                database="ok",
                schema_version="0002_positions_orders",
                tables=14,
            )
        )
    )

    response = client.get("/positions/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["schema_version"] == "0002_positions_orders"


def test_portfolios_routes_use_injected_handlers():
    seen: list[PortfolioCreateParams] = []

    def fake_create(params: PortfolioCreateParams) -> dict[str, object]:
        seen.append(params)
        return {
            "id": 1,
            "name": params.name,
            "portfolio_type": params.portfolio_type,
            "currency": params.currency,
            "enabled": params.enabled,
            "metadata": params.metadata,
        }

    client = TestClient(
        create_app(
            portfolio_list=lambda: {"items": [], "count": 0},
            portfolio_create=fake_create,
        )
    )

    list_response = client.get("/portfolios")
    create_response = client.post(
        "/portfolios",
        json={"name": "paper-main", "portfolio_type": "paper", "metadata": {"owner": "ops"}},
    )

    assert list_response.status_code == 200
    assert list_response.json() == {"items": [], "count": 0}
    assert create_response.status_code == 201
    assert create_response.json()["name"] == "paper-main"
    assert seen == [
        PortfolioCreateParams(
            name="paper-main",
            portfolio_type="paper",
            currency="USD",
            enabled=True,
            metadata={"owner": "ops"},
        )
    ]


def test_positions_list_parses_filters_and_pagination():
    seen: list[PositionListParams] = []

    def fake_list(params: PositionListParams) -> dict[str, object]:
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(position_list=fake_list))

    response = client.get(
        "/positions?portfolio=paper-main&active=true&ticker=AAPL&market=stocks&locale=us&limit=25&offset=50"
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 25, "offset": 50, "count": 0}
    assert seen == [
        PositionListParams(
            portfolio="paper-main",
            active=True,
            ticker="AAPL",
            market="stocks",
            locale="us",
            limit=25,
            offset=50,
        )
    ]


def test_position_by_ticker_requires_portfolio():
    client = TestClient(create_app())

    response = client.get("/positions/by-ticker/AAPL")

    assert response.status_code == 422
    assert response.json() == {"detail": "portfolio is required"}


def test_post_orders_valid_buy_uses_injected_submitter():
    seen: list[OrderCreateParams] = []

    def fake_submit(params: OrderCreateParams) -> dict[str, object]:
        seen.append(params)
        return {
            "status": "submitted",
            "order_id": 123,
            "portfolio": params.portfolio,
            "side": params.side,
            "submitted_ticker": params.ticker,
            "symbol_id": 1,
            "order_state": "pending_validation",
        }

    client = TestClient(create_app(order_submit=fake_submit))

    response = client.post(
        "/orders",
        json={
            "portfolio": "paper-main",
            "idempotency_key": "paper-main:2026-06-09:AAPL:buy:001",
            "ticker": "AAPL",
            "market": "stocks",
            "locale": "us",
            "side": "buy",
            "quantity": 10,
            "order_type": "limit",
            "limit_price": 185.50,
            "time_in_force": "day",
            "source": "watchlist-review",
            "reason": "Approved after manual review",
            "tags": ["manual", "watchlist"],
            "metadata": {"watchlist_entry_id": 456},
        },
    )

    assert response.status_code == 201
    assert response.json()["order_state"] == "pending_validation"
    assert seen == [
        OrderCreateParams(
            portfolio="paper-main",
            idempotency_key="paper-main:2026-06-09:AAPL:buy:001",
            ticker="AAPL",
            market="stocks",
            locale="us",
            side="buy",
            quantity=Decimal("10"),
            notional=None,
            order_type="limit",
            limit_price=Decimal("185.5"),
            stop_price=None,
            time_in_force="day",
            source="watchlist-review",
            reason="Approved after manual review",
            tags=("manual", "watchlist"),
            metadata={"watchlist_entry_id": 456},
        )
    ]


def test_post_orders_rejects_invalid_quantity_before_submitter():
    def fail_if_called(_params: OrderCreateParams) -> dict[str, object]:
        raise AssertionError("invalid order should not be submitted")

    client = TestClient(create_app(order_submit=fail_if_called))

    response = client.post(
        "/orders",
        json={
            "portfolio": "paper-main",
            "idempotency_key": "bad",
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 0,
            "order_type": "market",
            "time_in_force": "day",
            "source": "operator",
            "reason": "test",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "quantity must be a positive number"}


def test_post_orders_duplicate_response_keeps_200_status():
    client = TestClient(
        create_app(
            order_submit=lambda params: {
                "status": "duplicate",
                "order_id": 123,
                "portfolio": params.portfolio,
                "side": params.side,
                "submitted_ticker": params.ticker,
                "symbol_id": 1,
                "order_state": "pending_validation",
            }
        )
    )

    response = client.post(
        "/orders",
        json={
            "portfolio": "paper-main",
            "idempotency_key": "dup",
            "ticker": "AAPL",
            "side": "sell",
            "quantity": 5,
            "order_type": "market",
            "time_in_force": "day",
            "source": "operator",
            "reason": "Reduce exposure",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"
