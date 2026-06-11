from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import json
import os
from typing import Any


VALID_PORTFOLIO_TYPES = frozenset(("paper", "manual", "simulated"))
VALID_ORDER_SIDES = frozenset(("buy", "sell"))
VALID_ORDER_TYPES = frozenset(("market", "limit"))
VALID_TIME_IN_FORCE = frozenset(("day", "gtc", "ioc", "fok"))


class PositionValidationError(ValueError):
    """Raised when a positions/order request violates the public contract."""


@dataclass(frozen=True)
class PortfolioCreateParams:
    name: str
    portfolio_type: str = "paper"
    currency: str = "USD"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PositionListParams:
    portfolio: str | None = None
    active: bool | None = None
    ticker: str | None = None
    market: str | None = None
    locale: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class OrderCreateParams:
    portfolio: str
    idempotency_key: str
    ticker: str
    market: str
    locale: str
    side: str
    quantity: Decimal | None
    notional: Decimal | None
    order_type: str
    limit_price: Decimal | None
    stop_price: Decimal | None
    time_in_force: str
    source: str
    reason: str
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def portfolio_params_from_payload(payload: Any) -> PortfolioCreateParams:
    if not isinstance(payload, dict):
        raise PositionValidationError("request body must be a JSON object")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise PositionValidationError("metadata must be an object")
    return PortfolioCreateParams(
        name=_required_str(payload, "name"),
        portfolio_type=_optional_str(payload, "portfolio_type", "paper"),
        currency=_optional_str(payload, "currency", "USD").upper(),
        enabled=bool(payload.get("enabled", True)),
        metadata=metadata,
    )


def order_params_from_payload(payload: Any) -> OrderCreateParams:
    if not isinstance(payload, dict):
        raise PositionValidationError("request body must be a JSON object")
    tags = payload.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
        raise PositionValidationError("tags must be a list of non-empty strings")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise PositionValidationError("metadata must be an object")

    quantity = _optional_positive_decimal(payload, "quantity")
    notional = _optional_positive_decimal(payload, "notional")
    if (quantity is None) == (notional is None):
        raise PositionValidationError("exactly one of quantity or notional is required")

    order_type = _required_str(payload, "order_type").lower()
    limit_price = _optional_positive_decimal(payload, "limit_price")
    if order_type == "limit" and limit_price is None:
        raise PositionValidationError("limit_price is required for limit orders")
    if order_type == "market" and limit_price is not None:
        raise PositionValidationError("limit_price is not allowed for market orders")

    side = _required_str(payload, "side").lower()
    time_in_force = _required_str(payload, "time_in_force").lower()
    params = OrderCreateParams(
        portfolio=_required_str(payload, "portfolio"),
        idempotency_key=_required_str(payload, "idempotency_key"),
        ticker=_required_str(payload, "ticker").upper(),
        market=_optional_str(payload, "market", "stocks"),
        locale=_optional_str(payload, "locale", "us"),
        side=side,
        quantity=quantity,
        notional=notional,
        order_type=order_type,
        limit_price=limit_price,
        stop_price=_optional_positive_decimal(payload, "stop_price"),
        time_in_force=time_in_force,
        source=_required_str(payload, "source"),
        reason=_required_str(payload, "reason"),
        tags=tuple(tag.strip() for tag in tags),
        metadata=metadata,
    )
    validate_order_params(params)
    return params


def validate_portfolio_params(params: PortfolioCreateParams) -> None:
    if not params.name.strip():
        raise PositionValidationError("name is required")
    if params.portfolio_type not in VALID_PORTFOLIO_TYPES:
        raise PositionValidationError("portfolio_type is unsupported")
    if len(params.currency) != 3 or not params.currency.isalpha():
        raise PositionValidationError("currency must be a 3-letter code")


def validate_order_params(params: OrderCreateParams) -> None:
    if params.side not in VALID_ORDER_SIDES:
        raise PositionValidationError("side must be buy or sell")
    if params.order_type not in VALID_ORDER_TYPES:
        raise PositionValidationError("order_type must be market or limit")
    if params.time_in_force not in VALID_TIME_IN_FORCE:
        raise PositionValidationError("time_in_force is unsupported")
    if params.stop_price is not None:
        raise PositionValidationError("stop_price is not supported in this slice")
    for field_name in ("portfolio", "idempotency_key", "ticker", "source", "reason"):
        if not getattr(params, field_name).strip():
            raise PositionValidationError(f"{field_name} is required")


def list_portfolios() -> dict[str, Any]:
    from sqlalchemy import create_engine, text

    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT id, name, portfolio_type, currency, enabled, metadata, created_at, updated_at
                    FROM trading.portfolios
                    ORDER BY name ASC
                    """
                )
            ).mappings().all()
    finally:
        engine.dispose()
    items = [_portfolio_row(row) for row in rows]
    return {"items": items, "count": len(items)}


def create_portfolio(params: PortfolioCreateParams) -> dict[str, Any]:
    from sqlalchemy import create_engine, text

    validate_portfolio_params(params)
    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    INSERT INTO trading.portfolios (name, portfolio_type, currency, enabled, metadata)
                    VALUES (:name, :portfolio_type, :currency, :enabled, CAST(:metadata AS jsonb))
                    ON CONFLICT (name) DO UPDATE
                    SET portfolio_type = EXCLUDED.portfolio_type,
                        currency = EXCLUDED.currency,
                        enabled = EXCLUDED.enabled,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    RETURNING id, name, portfolio_type, currency, enabled, metadata, created_at, updated_at
                    """
                ),
                {
                    "name": params.name.strip(),
                    "portfolio_type": params.portfolio_type,
                    "currency": params.currency,
                    "enabled": params.enabled,
                    "metadata": _json(params.metadata),
                },
            ).mappings().one()
    finally:
        engine.dispose()
    return _portfolio_row(row)


def list_positions(params: PositionListParams) -> dict[str, Any]:
    from sqlalchemy import create_engine, text

    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT
                        p.id, pf.name AS portfolio, p.submitted_ticker, p.symbol_id,
                        p.market, p.locale, p.quantity, p.average_cost, p.market_value,
                        p.realized_pnl, p.unrealized_pnl, p.status, p.created_at, p.updated_at,
                        s.canonical_ticker, s.name AS symbol_name, s.active AS symbol_active,
                        e.mic AS exchange_mic
                    FROM trading.positions p
                    JOIN trading.portfolios pf ON pf.id = p.portfolio_id
                    LEFT JOIN symbol_master.symbols s ON s.id = p.symbol_id
                    LEFT JOIN symbol_master.exchanges e ON e.id = s.primary_exchange_id
                    {_positions_where_clause(params)}
                    ORDER BY pf.name ASC, p.submitted_ticker ASC, p.id ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                _positions_query_values(params),
            ).mappings().all()
    finally:
        engine.dispose()
    items = [_position_row(row) for row in rows]
    return {"items": items, "limit": params.limit, "offset": params.offset, "count": len(items)}


def get_position(position_id: int) -> dict[str, Any] | None:
    from sqlalchemy import create_engine, text

    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        p.id, pf.name AS portfolio, p.submitted_ticker, p.symbol_id,
                        p.market, p.locale, p.quantity, p.average_cost, p.market_value,
                        p.realized_pnl, p.unrealized_pnl, p.status, p.created_at, p.updated_at,
                        s.canonical_ticker, s.name AS symbol_name, s.active AS symbol_active,
                        e.mic AS exchange_mic
                    FROM trading.positions p
                    JOIN trading.portfolios pf ON pf.id = p.portfolio_id
                    LEFT JOIN symbol_master.symbols s ON s.id = p.symbol_id
                    LEFT JOIN symbol_master.exchanges e ON e.id = s.primary_exchange_id
                    WHERE p.id = :position_id
                    LIMIT 1
                    """
                ),
                {"position_id": position_id},
            ).mappings().first()
    finally:
        engine.dispose()
    return None if row is None else _position_row(row)


def get_position_by_ticker(
    *, portfolio: str, ticker: str, market: str = "stocks", locale: str = "us"
) -> dict[str, Any] | None:
    params = PositionListParams(
        portfolio=portfolio,
        ticker=ticker,
        market=market,
        locale=locale,
        limit=1,
        offset=0,
    )
    result = list_positions(params)
    return result["items"][0] if result["items"] else None


def submit_order(params: OrderCreateParams) -> dict[str, Any]:
    from sqlalchemy import create_engine, text

    validate_order_params(params)
    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            portfolio = connection.execute(
                text("SELECT id, name FROM trading.portfolios WHERE name = :name LIMIT 1"),
                {"name": params.portfolio},
            ).mappings().first()
            if portfolio is None:
                raise PositionValidationError("portfolio not found")

            existing = connection.execute(
                text(
                    """
                    SELECT id, status, symbol_id
                    FROM trading.order_intents
                    WHERE portfolio_id = :portfolio_id
                      AND idempotency_key = :idempotency_key
                    LIMIT 1
                    """
                ),
                {"portfolio_id": portfolio["id"], "idempotency_key": params.idempotency_key},
            ).mappings().first()
            if existing is not None:
                return _order_response(
                    status="duplicate",
                    order_id=int(existing["id"]),
                    params=params,
                    symbol_id=existing["symbol_id"],
                    order_state=existing["status"],
                )

            symbol = connection.execute(
                text(
                    """
                    SELECT id
                    FROM symbol_master.symbols
                    WHERE lower(canonical_ticker) = :ticker
                      AND market = :market
                      AND locale = :locale
                      AND active = true
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {
                    "ticker": params.ticker.lower(),
                    "market": params.market,
                    "locale": params.locale,
                },
            ).mappings().first()
            symbol_id = None if symbol is None else int(symbol["id"])

            order = connection.execute(
                text(
                    """
                    INSERT INTO trading.order_intents (
                        portfolio_id, idempotency_key, submitted_ticker, symbol_id, market,
                        locale, side, quantity, notional, order_type, limit_price,
                        stop_price, time_in_force, source, reason, tags, metadata, status
                    )
                    VALUES (
                        :portfolio_id, :idempotency_key, :submitted_ticker, :symbol_id, :market,
                        :locale, :side, :quantity, :notional, :order_type, :limit_price,
                        :stop_price, :time_in_force, :source, :reason, CAST(:tags AS jsonb),
                        CAST(:metadata AS jsonb), 'pending_validation'
                    )
                    RETURNING id
                    """
                ),
                {
                    "portfolio_id": portfolio["id"],
                    "idempotency_key": params.idempotency_key,
                    "submitted_ticker": params.ticker,
                    "symbol_id": symbol_id,
                    "market": params.market,
                    "locale": params.locale,
                    "side": params.side,
                    "quantity": params.quantity,
                    "notional": params.notional,
                    "order_type": params.order_type,
                    "limit_price": params.limit_price,
                    "stop_price": params.stop_price,
                    "time_in_force": params.time_in_force,
                    "source": params.source,
                    "reason": params.reason,
                    "tags": _json(list(params.tags)),
                    "metadata": _json(params.metadata),
                },
            ).mappings().one()
            order_id = int(order["id"])
            connection.execute(
                text(
                    """
                    INSERT INTO trading.order_events (order_id, event_type, to_status, reason, metadata)
                    VALUES (:order_id, 'submitted', 'pending_validation', :reason, '{}'::jsonb)
                    """
                ),
                {"order_id": order_id, "reason": params.reason},
            )
    finally:
        engine.dispose()
    return _order_response(
        status="submitted",
        order_id=order_id,
        params=params,
        symbol_id=symbol_id,
        order_state="pending_validation",
    )


def _database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return database_url


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PositionValidationError(f"{key} is required")
    return value.strip()


def _optional_str(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise PositionValidationError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_positive_decimal(payload: dict[str, Any], key: str) -> Decimal | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise PositionValidationError(f"{key} must be a positive number")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PositionValidationError(f"{key} must be a positive number")
    if decimal <= 0:
        raise PositionValidationError(f"{key} must be a positive number")
    return decimal


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _decimal_string(value: Any) -> str | None:
    if value is None:
        return None
    return format(Decimal(str(value)).normalize(), "f")


def _timestamp(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _portfolio_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "portfolio_type": row["portfolio_type"],
        "currency": row["currency"],
        "enabled": bool(row["enabled"]),
        "metadata": dict(row["metadata"]),
        "created_at": _timestamp(row["created_at"]),
        "updated_at": _timestamp(row["updated_at"]),
    }


def _position_row(row: Any) -> dict[str, Any]:
    symbol = None
    if row["symbol_id"] is not None:
        symbol = {
            "id": int(row["symbol_id"]),
            "canonical_ticker": row["canonical_ticker"],
            "name": row["symbol_name"],
            "market": row["market"],
            "locale": row["locale"],
            "active": bool(row["symbol_active"]),
            "exchange": row["exchange_mic"],
        }
    return {
        "id": int(row["id"]),
        "portfolio": row["portfolio"],
        "submitted_ticker": row["submitted_ticker"],
        "symbol_id": int(row["symbol_id"]) if row["symbol_id"] is not None else None,
        "symbol": symbol,
        "market": row["market"],
        "locale": row["locale"],
        "quantity": _decimal_string(row["quantity"]),
        "average_cost": _decimal_string(row["average_cost"]),
        "market_value": _decimal_string(row["market_value"]),
        "realized_pnl": _decimal_string(row["realized_pnl"]),
        "unrealized_pnl": _decimal_string(row["unrealized_pnl"]),
        "status": row["status"],
        "created_at": _timestamp(row["created_at"]),
        "updated_at": _timestamp(row["updated_at"]),
    }


def _positions_where_clause(params: PositionListParams) -> str:
    predicates: list[str] = []
    if params.portfolio:
        predicates.append("pf.name = :portfolio")
    if params.active is True:
        predicates.append("p.status = 'open'")
    elif params.active is False:
        predicates.append("p.status <> 'open'")
    if params.ticker:
        predicates.append("lower(p.submitted_ticker) = :ticker")
    if params.market:
        predicates.append("p.market = :market")
    if params.locale:
        predicates.append("p.locale = :locale")
    return "" if not predicates else "WHERE " + " AND ".join(predicates)


def _positions_query_values(params: PositionListParams) -> dict[str, Any]:
    values: dict[str, Any] = {"limit": params.limit, "offset": params.offset}
    if params.portfolio:
        values["portfolio"] = params.portfolio
    if params.ticker:
        values["ticker"] = params.ticker.lower()
    if params.market:
        values["market"] = params.market
    if params.locale:
        values["locale"] = params.locale
    return values


def _order_response(
    *,
    status: str,
    order_id: int,
    params: OrderCreateParams,
    symbol_id: Any,
    order_state: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "order_id": order_id,
        "portfolio": params.portfolio,
        "side": params.side,
        "submitted_ticker": params.ticker,
        "symbol_id": int(symbol_id) if symbol_id is not None else None,
        "order_state": order_state,
    }
