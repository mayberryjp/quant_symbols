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


@dataclass(frozen=True)
class SymbolHistoryParams:
    days: int | None = None
    market: str | None = None
    locale: str | None = None


@dataclass(frozen=True)
class SymbolRecentParams:
    days: int = 7
    market: str | None = None
    locale: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class SymbolDelistedParams:
    days: int = 7
    market: str | None = None
    locale: str | None = None
    limit: int = 100
    offset: int = 0


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


def get_symbol_count_history(params: SymbolHistoryParams) -> dict[str, Any]:
    """Return a daily time series of symbol counts.

    Each point carries three numbers for its date:
      * ``total_symbols`` — cumulative count of every symbol created on or before
        the date (the full master universe; delisted rows are retained).
      * ``new_symbols`` — symbols first created on that date.
      * ``delisted_symbols`` — symbols delisted on that date.

    ``params.days`` limits the series to the most recent N calendar days
    (inclusive of today); when omitted, the series starts at the earliest
    ``created_at`` date. ``total_symbols`` stays correct inside a window because a
    baseline count of everything created before the window start is carried in.
    """
    from sqlalchemy import create_engine, text

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    where = _history_where_clause(params)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    WITH filtered AS (
                        SELECT s.created_at, s.delisted_at
                        FROM symbol_master.symbols s
                        {where}
                    ),
                    bounds AS (
                        SELECT
                            CASE
                                WHEN :days::int IS NULL
                                    THEN (SELECT min(created_at)::date FROM filtered)
                                ELSE (current_date - ((:days::int - 1) * interval '1 day'))::date
                            END AS start_date,
                            current_date AS end_date
                    ),
                    calendar AS (
                        SELECT generate_series(b.start_date, b.end_date, interval '1 day')::date
                            AS bucket_date
                        FROM bounds b
                        WHERE b.start_date IS NOT NULL
                    ),
                    new_counts AS (
                        SELECT created_at::date AS d, count(*) AS n
                        FROM filtered
                        GROUP BY created_at::date
                    ),
                    delisted_counts AS (
                        SELECT delisted_at::date AS d, count(*) AS n
                        FROM filtered
                        WHERE delisted_at IS NOT NULL
                        GROUP BY delisted_at::date
                    ),
                    baseline AS (
                        SELECT count(*) AS base_total
                        FROM filtered
                        WHERE created_at::date < (SELECT start_date FROM bounds)
                    )
                    SELECT
                        c.bucket_date AS bucket_date,
                        COALESCE(nc.n, 0) AS new_symbols,
                        COALESCE(dc.n, 0) AS delisted_symbols,
                        (SELECT base_total FROM baseline)
                            + sum(COALESCE(nc.n, 0)) OVER (ORDER BY c.bucket_date)
                            AS total_symbols
                    FROM calendar c
                    LEFT JOIN new_counts nc ON nc.d = c.bucket_date
                    LEFT JOIN delisted_counts dc ON dc.d = c.bucket_date
                    ORDER BY c.bucket_date
                    """
                ),
                _history_query_values(params),
            ).mappings().all()
    finally:
        engine.dispose()

    points = [
        {
            "date": row["bucket_date"].isoformat(),
            "total_symbols": int(row["total_symbols"]),
            "new_symbols": int(row["new_symbols"]),
            "delisted_symbols": int(row["delisted_symbols"]),
        }
        for row in rows
    ]
    return {
        "bucket": "day",
        "filters": {
            "days": params.days,
            "market": params.market,
            "locale": params.locale,
        },
        "points": points,
    }


def list_recent_symbols(params: SymbolRecentParams) -> dict[str, Any]:
    """List symbols first created within the last ``params.days`` days."""
    from sqlalchemy import create_engine, text

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    where = _window_where_clause(params)
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
                        s.created_at,
                        e.id AS exchange_id,
                        e.mic AS exchange_mic,
                        e.name AS exchange_name
                    FROM symbol_master.symbols s
                    LEFT JOIN symbol_master.exchanges e
                        ON e.id = s.primary_exchange_id
                    WHERE s.created_at >= now() - (:days::int * interval '1 day')
                    {where}
                    ORDER BY s.created_at DESC, s.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                _window_query_values(params),
            ).mappings().all()
    finally:
        engine.dispose()

    items = []
    for row in rows:
        item = _row_to_item(row)
        item["created_at"] = row["created_at"].isoformat() if row["created_at"] else None
        items.append(item)
    return {
        "items": items,
        "days": params.days,
        "limit": params.limit,
        "offset": params.offset,
        "count": len(items),
    }


def list_delisted_symbols(params: SymbolDelistedParams) -> dict[str, Any]:
    """List symbols delisted within the last ``params.days`` days."""
    from sqlalchemy import create_engine, text

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    where = _window_where_clause(params)
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
                        s.delisted_at,
                        e.id AS exchange_id,
                        e.mic AS exchange_mic,
                        e.name AS exchange_name
                    FROM symbol_master.symbols s
                    LEFT JOIN symbol_master.exchanges e
                        ON e.id = s.primary_exchange_id
                    WHERE s.delisted_at IS NOT NULL
                      AND s.delisted_at >= now() - (:days::int * interval '1 day')
                    {where}
                    ORDER BY s.delisted_at DESC, s.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                _window_query_values(params),
            ).mappings().all()
    finally:
        engine.dispose()

    items = []
    for row in rows:
        item = _row_to_item(row)
        item["delisted_at"] = row["delisted_at"].isoformat() if row["delisted_at"] else None
        items.append(item)
    return {
        "items": items,
        "days": params.days,
        "limit": params.limit,
        "offset": params.offset,
        "count": len(items),
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


def _history_where_clause(params: SymbolHistoryParams) -> str:
    predicates = []
    if params.market is not None:
        predicates.append("s.market = :market")
    if params.locale is not None:
        predicates.append("s.locale = :locale")
    if not predicates:
        return ""
    return "WHERE " + " AND ".join(predicates)


def _history_query_values(params: SymbolHistoryParams) -> dict[str, Any]:
    values: dict[str, Any] = {"days": params.days}
    if params.market is not None:
        values["market"] = params.market
    if params.locale is not None:
        values["locale"] = params.locale
    return values


def _window_where_clause(params: SymbolRecentParams | SymbolDelistedParams) -> str:
    predicates = []
    if params.market is not None:
        predicates.append("s.market = :market")
    if params.locale is not None:
        predicates.append("s.locale = :locale")
    if not predicates:
        return ""
    return "AND " + " AND ".join(predicates)


def _window_query_values(params: SymbolRecentParams | SymbolDelistedParams) -> dict[str, Any]:
    values: dict[str, Any] = {
        "days": params.days,
        "limit": params.limit,
        "offset": params.offset,
    }
    if params.market is not None:
        values["market"] = params.market
    if params.locale is not None:
        values["locale"] = params.locale
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
