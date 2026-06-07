from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal


VendorRunStatus = Literal["running", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True)
class RawPayloadListParams:
    symbol_id: int
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class VendorRunListParams:
    vendor: str = "massive"
    endpoint: str | None = None
    status: VendorRunStatus | None = None
    limit: int = 20
    offset: int = 0


def list_symbol_aliases(symbol_id: int) -> dict[str, Any] | None:
    from sqlalchemy import create_engine, text

    database_url = _database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if not _symbol_exists(connection, symbol_id):
                return None
            rows = connection.execute(
                text(
                    """
                    SELECT
                        a.id,
                        a.alias_type,
                        a.alias_value,
                        a.active,
                        a.source_payload_id,
                        a.valid_from,
                        a.valid_to,
                        v.id AS vendor_id,
                        v.code AS vendor_code,
                        v.name AS vendor_name
                    FROM symbol_master.symbol_aliases a
                    LEFT JOIN symbol_master.vendor_sources v
                        ON v.id = a.source_vendor_id
                    WHERE a.symbol_id = :symbol_id
                    ORDER BY a.alias_type ASC, a.alias_value ASC, a.id ASC
                    """
                ),
                {"symbol_id": symbol_id},
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_alias_row_to_item(row) for row in rows]
    return {"symbol_id": symbol_id, "items": items, "count": len(items)}


def list_symbol_vendor_ids(symbol_id: int) -> dict[str, Any] | None:
    from sqlalchemy import create_engine, text

    database_url = _database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if not _symbol_exists(connection, symbol_id):
                return None
            rows = connection.execute(
                text(
                    """
                    SELECT
                        svi.id,
                        svi.vendor_symbol,
                        svi.vendor_asset_id,
                        svi.active,
                        svi.first_seen_run_id,
                        svi.first_seen_payload_id,
                        svi.last_seen_run_id,
                        svi.last_seen_payload_id,
                        v.id AS vendor_id,
                        v.code AS vendor_code,
                        v.name AS vendor_name
                    FROM symbol_master.symbol_vendor_ids svi
                    JOIN symbol_master.vendor_sources v
                        ON v.id = svi.vendor_source_id
                    WHERE svi.symbol_id = :symbol_id
                    ORDER BY v.code ASC, lower(svi.vendor_symbol) ASC, svi.id ASC
                    """
                ),
                {"symbol_id": symbol_id},
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_vendor_id_row_to_item(row) for row in rows]
    return {"symbol_id": symbol_id, "items": items, "count": len(items)}


def list_symbol_raw_payloads(params: RawPayloadListParams) -> dict[str, Any] | None:
    from sqlalchemy import create_engine, text

    database_url = _database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if not _symbol_exists(connection, params.symbol_id):
                return None
            rows = connection.execute(
                text(
                    """
                    WITH linked_payloads AS (
                        SELECT first_seen_payload_id AS id
                        FROM symbol_master.symbols
                        WHERE id = :symbol_id AND first_seen_payload_id IS NOT NULL
                        UNION
                        SELECT last_seen_payload_id AS id
                        FROM symbol_master.symbols
                        WHERE id = :symbol_id AND last_seen_payload_id IS NOT NULL
                        UNION
                        SELECT first_seen_payload_id AS id
                        FROM symbol_master.symbol_vendor_ids
                        WHERE symbol_id = :symbol_id AND first_seen_payload_id IS NOT NULL
                        UNION
                        SELECT last_seen_payload_id AS id
                        FROM symbol_master.symbol_vendor_ids
                        WHERE symbol_id = :symbol_id AND last_seen_payload_id IS NOT NULL
                        UNION
                        SELECT source_payload_id AS id
                        FROM symbol_master.symbol_aliases
                        WHERE symbol_id = :symbol_id AND source_payload_id IS NOT NULL
                    )
                    SELECT
                        p.id,
                        p.vendor_api_run_id,
                        p.provider_record_id,
                        p.provider_ticker,
                        p.received_at,
                        p.payload,
                        v.id AS vendor_id,
                        v.code AS vendor_code,
                        v.name AS vendor_name
                    FROM symbol_master.raw_vendor_payloads p
                    JOIN symbol_master.vendor_sources v
                        ON v.id = p.vendor_source_id
                    WHERE p.id IN (SELECT id FROM linked_payloads)
                    ORDER BY p.received_at DESC, p.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {
                    "symbol_id": params.symbol_id,
                    "limit": params.limit,
                    "offset": params.offset,
                },
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_raw_payload_row_to_item(row) for row in rows]
    return {
        "symbol_id": params.symbol_id,
        "items": items,
        "limit": params.limit,
        "offset": params.offset,
        "count": len(items),
    }


def list_vendor_runs(params: VendorRunListParams) -> dict[str, Any]:
    from sqlalchemy import create_engine, text

    database_url = _database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT
                        r.id,
                        r.endpoint,
                        r.status,
                        r.started_at,
                        r.finished_at,
                        r.records_seen,
                        r.records_inserted,
                        r.records_failed,
                        r.error_message,
                        v.id AS vendor_id,
                        v.code AS vendor_code,
                        v.name AS vendor_name
                    FROM symbol_master.vendor_api_runs r
                    JOIN symbol_master.vendor_sources v
                        ON v.id = r.vendor_source_id
                    {_vendor_run_where_clause(params)}
                    ORDER BY r.started_at DESC, r.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                _vendor_run_query_values(params),
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_vendor_run_row_to_item(row) for row in rows]
    return {
        "items": items,
        "limit": params.limit,
        "offset": params.offset,
        "count": len(items),
    }


def get_vendor_run(run_id: int) -> dict[str, Any] | None:
    from sqlalchemy import create_engine, text

    database_url = _database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT
                            r.id,
                            r.endpoint,
                            r.request_params,
                            r.status,
                            r.started_at,
                            r.finished_at,
                            r.records_seen,
                            r.records_inserted,
                            r.records_failed,
                            r.error_message,
                            v.id AS vendor_id,
                            v.code AS vendor_code,
                            v.name AS vendor_name,
                            count(p.id) AS raw_payload_count
                        FROM symbol_master.vendor_api_runs r
                        JOIN symbol_master.vendor_sources v
                            ON v.id = r.vendor_source_id
                        LEFT JOIN symbol_master.raw_vendor_payloads p
                            ON p.vendor_api_run_id = r.id
                        WHERE r.id = :run_id
                        GROUP BY
                            r.id,
                            r.endpoint,
                            r.request_params,
                            r.status,
                            r.started_at,
                            r.finished_at,
                            r.records_seen,
                            r.records_inserted,
                            r.records_failed,
                            r.error_message,
                            v.id,
                            v.code,
                            v.name
                        LIMIT 1
                        """
                    ),
                    {"run_id": run_id},
                )
                .mappings()
                .first()
            )
    finally:
        engine.dispose()

    if row is None:
        return None
    item = _vendor_run_row_to_item(row)
    item["request_params"] = row["request_params"]
    item["raw_payload_count"] = int(row["raw_payload_count"])
    return item


def _database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return database_url


def _symbol_exists(connection: Any, symbol_id: int) -> bool:
    from sqlalchemy import text

    return bool(
        connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM symbol_master.symbols WHERE id = :symbol_id)"),
            {"symbol_id": symbol_id},
        ).scalar_one()
    )


def _vendor_run_where_clause(params: VendorRunListParams) -> str:
    predicates = []
    if params.vendor:
        predicates.append("v.code = :vendor")
    if params.endpoint is not None:
        predicates.append("r.endpoint = :endpoint")
    if params.status is not None:
        predicates.append("r.status = :status")
    if not predicates:
        return ""
    return "WHERE " + " AND ".join(predicates)


def _vendor_run_query_values(params: VendorRunListParams) -> dict[str, Any]:
    values: dict[str, Any] = {
        "limit": params.limit,
        "offset": params.offset,
    }
    if params.vendor:
        values["vendor"] = params.vendor
    if params.endpoint is not None:
        values["endpoint"] = params.endpoint
    if params.status is not None:
        values["status"] = params.status
    return values


def _vendor(row: Any, *, prefix: str = "vendor") -> dict[str, Any]:
    return {
        "id": int(row[f"{prefix}_id"]),
        "code": row[f"{prefix}_code"],
        "name": row[f"{prefix}_name"],
    }


def _optional_vendor(row: Any, *, prefix: str = "vendor") -> dict[str, Any] | None:
    if row[f"{prefix}_id"] is None:
        return None
    return _vendor(row, prefix=prefix)


def _alias_row_to_item(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "alias_type": row["alias_type"],
        "alias_value": row["alias_value"],
        "active": bool(row["active"]),
        "source_vendor": _optional_vendor(row),
        "source_payload_id": _optional_int(row["source_payload_id"]),
        "valid_from": _iso_or_none(row["valid_from"]),
        "valid_to": _iso_or_none(row["valid_to"]),
    }


def _vendor_id_row_to_item(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "vendor": _vendor(row),
        "vendor_symbol": row["vendor_symbol"],
        "vendor_asset_id": row["vendor_asset_id"],
        "active": bool(row["active"]),
        "first_seen_run_id": _optional_int(row["first_seen_run_id"]),
        "first_seen_payload_id": _optional_int(row["first_seen_payload_id"]),
        "last_seen_run_id": _optional_int(row["last_seen_run_id"]),
        "last_seen_payload_id": _optional_int(row["last_seen_payload_id"]),
    }


def _raw_payload_row_to_item(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "vendor": _vendor(row),
        "vendor_api_run_id": int(row["vendor_api_run_id"]),
        "provider_record_id": row["provider_record_id"],
        "provider_ticker": row["provider_ticker"],
        "received_at": _iso_or_none(row["received_at"]),
        "payload": row["payload"],
    }


def _vendor_run_row_to_item(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "vendor": _vendor(row),
        "endpoint": row["endpoint"],
        "status": row["status"],
        "started_at": _iso_or_none(row["started_at"]),
        "finished_at": _iso_or_none(row["finished_at"]),
        "records_seen": int(row["records_seen"]),
        "records_inserted": int(row["records_inserted"]),
        "records_failed": int(row["records_failed"]),
        "error_message": row["error_message"],
    }


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
