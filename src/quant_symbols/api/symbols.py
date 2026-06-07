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
                _query_values(params),
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


def _where_clause(params: SymbolListParams) -> str:
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


def _query_values(params: SymbolListParams) -> dict[str, Any]:
    values: dict[str, Any] = {
        "limit": params.limit,
        "offset": params.offset,
    }
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
