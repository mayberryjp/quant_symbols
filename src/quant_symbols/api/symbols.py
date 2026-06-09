from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SymbolListParams:
    active: bool | None = None
    market: str | None = None
    locale: str | None = None
    q: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class SymbolCountParams:
    active: bool | None = None
    market: str | None = None
    locale: str | None = None
    q: str | None = None


@dataclass(frozen=True)
class SymbolTickerLookupParams:
    ticker: str
    market: str = "stocks"
    locale: str = "us"
    active: bool = True


def list_symbols(params: SymbolListParams) -> dict[str, Any]:
    from sqlalchemy import create_engine, text

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT
                        s.id,
                        s.canonical_ticker,
                        s.name,
                        s.market,
                        s.locale,
                        s.currency,
                        s.asset_class,
                        s.security_type,
                        s.active,
                        e.id AS exchange_id,
                        e.mic AS exchange_mic,
                        e.name AS exchange_name
                    FROM symbol_master.symbols s
                    LEFT JOIN symbol_master.exchanges e
                        ON e.id = s.primary_exchange_id
                    {_where_clause(params)}
                    ORDER BY s.canonical_ticker ASC, s.id ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                _list_query_values(params),
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_row_to_item(row) for row in rows]
    return {
        "items": items,
        "limit": params.limit,
        "offset": params.offset,
        "count": len(items),
    }


def count_symbols(params: SymbolCountParams) -> dict[str, Any]:
    from sqlalchemy import create_engine, text

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            total = connection.execute(
                text(
                    f"""
                    SELECT count(*) AS total
                    FROM symbol_master.symbols s
                    {_where_clause(params)}
                    """
                ),
                _filter_query_values(params),
            ).scalar_one()
    finally:
        engine.dispose()

    return {
        "total": int(total),
        "filters": {
            "active": params.active,
            "market": params.market,
            "locale": params.locale,
            "q": params.q,
        },
    }


def get_symbol_by_id(symbol_id: int) -> dict[str, Any] | None:
    from sqlalchemy import create_engine, text

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT
                            s.id,
                            s.canonical_ticker,
                            s.name,
                            s.market,
                            s.locale,
                            s.currency,
                            s.asset_class,
                            s.security_type,
                            s.active,
                            s.cik,
                            s.composite_figi,
                            s.share_class_figi,
                            s.delisted_at,
                            e.id AS exchange_id,
                            e.mic AS exchange_mic,
                            e.name AS exchange_name
                        FROM symbol_master.symbols s
                        LEFT JOIN symbol_master.exchanges e
                            ON e.id = s.primary_exchange_id
                        WHERE s.id = :symbol_id
                        LIMIT 1
                        """
                    ),
                    {"symbol_id": symbol_id},
                )
                .mappings()
                .first()
            )
    finally:
        engine.dispose()

    if row is None:
        return None
    return _row_to_detail(row)


def get_symbol_by_ticker(params: SymbolTickerLookupParams) -> dict[str, Any] | None:
    from sqlalchemy import create_engine, text

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT
                            s.id,
                            s.canonical_ticker,
                            s.name,
                            s.market,
                            s.locale,
                            s.currency,
                            s.asset_class,
                            s.security_type,
                            s.active,
                            s.cik,
                            s.composite_figi,
                            s.share_class_figi,
                            s.delisted_at,
                            e.id AS exchange_id,
                            e.mic AS exchange_mic,
                            e.name AS exchange_name
                        FROM symbol_master.symbols s
                        LEFT JOIN symbol_master.exchanges e
                            ON e.id = s.primary_exchange_id
                        WHERE lower(s.canonical_ticker) = :ticker
                            AND s.market = :market
                            AND s.locale = :locale
                            AND s.active = :active
                        ORDER BY s.active DESC, s.id DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "ticker": params.ticker.strip().lower(),
                        "market": params.market,
                        "locale": params.locale,
                        "active": params.active,
                    },
                )
                .mappings()
                .first()
            )
    finally:
        engine.dispose()

    if row is None:
        return None
    return _row_to_detail(row)


def _where_clause(params: SymbolListParams | SymbolCountParams) -> str:
    predicates = []
    if params.active is not None:
        predicates.append("s.active = :active")
    if params.market is not None:
        predicates.append("s.market = :market")
    if params.locale is not None:
        predicates.append("s.locale = :locale")
    if params.q:
        predicates.append(
            """
            (
                lower(s.canonical_ticker) LIKE :q ESCAPE '\\'
                OR lower(coalesce(s.name, '')) LIKE :q ESCAPE '\\'
            )
            """
        )
    if not predicates:
        return ""
    return "WHERE " + " AND ".join(predicates)


def _list_query_values(params: SymbolListParams) -> dict[str, Any]:
    values = _filter_query_values(params)
    values.update(
        {
            "limit": params.limit,
            "offset": params.offset,
        }
    )
    return values


def _filter_query_values(params: SymbolListParams | SymbolCountParams) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if params.active is not None:
        values["active"] = params.active
    if params.market is not None:
        values["market"] = params.market
    if params.locale is not None:
        values["locale"] = params.locale
    if params.q:
        values["q"] = f"%{_escape_like(params.q.strip().lower())}%"
    return values


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_to_item(row: Any) -> dict[str, Any]:
    exchange_id = row["exchange_id"]
    primary_exchange = None
    if exchange_id is not None:
        primary_exchange = {
            "id": int(exchange_id),
            "mic": row["exchange_mic"],
            "name": row["exchange_name"],
        }

    return {
        "id": int(row["id"]),
        "canonical_ticker": row["canonical_ticker"],
        "name": row["name"],
        "market": row["market"],
        "locale": row["locale"],
        "currency": row["currency"],
        "asset_class": row["asset_class"],
        "security_type": row["security_type"],
        "active": bool(row["active"]),
        "primary_exchange": primary_exchange,
    }


def _row_to_detail(row: Any) -> dict[str, Any]:
    item = _row_to_item(row)
    item.update(
        {
            "cik": row["cik"],
            "composite_figi": row["composite_figi"],
            "share_class_figi": row["share_class_figi"],
            "delisted_at": row["delisted_at"].isoformat() if row["delisted_at"] else None,
        }
    )
    return item
