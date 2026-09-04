from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from quant_symbols.api.traceability import VendorRunStatus


DEFAULT_SYNC_VENDOR = "massive"
DEFAULT_SYNC_ENDPOINT = "/v3/reference/tickers"


@dataclass(frozen=True)
class SyncLatestParams:
    vendor: str = DEFAULT_SYNC_VENDOR
    endpoint: str = DEFAULT_SYNC_ENDPOINT


@dataclass(frozen=True)
class SyncRunListParams:
    vendor: str = DEFAULT_SYNC_VENDOR
    endpoint: str = DEFAULT_SYNC_ENDPOINT
    status: VendorRunStatus | None = None
    limit: int = 20
    offset: int = 0


def get_latest_sync_run(params: SyncLatestParams) -> dict[str, Any] | None:
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
                            r.status,
                            r.started_at,
                            r.finished_at,
                            r.records_seen,
                            r.records_inserted,
                            r.records_failed,
                            r.symbols_new,
                            r.symbols_delisted,
                            r.error_message,
                            v.id AS vendor_id,
                            v.code AS vendor_code,
                            v.name AS vendor_name,
                            count(p.id) AS raw_payload_count
                        FROM symbols.vendor_api_runs r
                        JOIN symbols.vendor_sources v
                            ON v.id = r.vendor_source_id
                        LEFT JOIN symbols.raw_vendor_payloads p
                            ON p.vendor_api_run_id = r.id
                        WHERE v.code = :vendor
                            AND r.endpoint = :endpoint
                        GROUP BY
                            r.id,
                            r.endpoint,
                            r.status,
                            r.started_at,
                            r.finished_at,
                            r.records_seen,
                            r.records_inserted,
                            r.records_failed,
                            r.symbols_new,
                            r.symbols_delisted,
                            r.error_message,
                            v.id,
                            v.code,
                            v.name
                        ORDER BY r.started_at DESC, r.id DESC
                        LIMIT 1
                        """
                    ),
                    {"vendor": params.vendor, "endpoint": params.endpoint},
                )
                .mappings()
                .first()
            )
    finally:
        engine.dispose()

    if row is None:
        return None
    return _sync_run_row_to_summary(row)


def list_sync_runs(params: SyncRunListParams) -> dict[str, Any]:
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
                        r.symbols_new,
                        r.symbols_delisted,
                        r.error_message,
                        v.id AS vendor_id,
                        v.code AS vendor_code,
                        v.name AS vendor_name,
                        count(p.id) AS raw_payload_count
                    FROM symbols.vendor_api_runs r
                    JOIN symbols.vendor_sources v
                        ON v.id = r.vendor_source_id
                    LEFT JOIN symbols.raw_vendor_payloads p
                        ON p.vendor_api_run_id = r.id
                    {_sync_run_where_clause(params)}
                    GROUP BY
                        r.id,
                        r.endpoint,
                        r.status,
                        r.started_at,
                        r.finished_at,
                        r.records_seen,
                        r.records_inserted,
                        r.records_failed,
                        r.symbols_new,
                        r.symbols_delisted,
                        r.error_message,
                        v.id,
                        v.code,
                        v.name
                    ORDER BY r.started_at DESC, r.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                _sync_run_query_values(params),
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_sync_run_row_to_summary(row) for row in rows]
    return {
        "items": items,
        "limit": params.limit,
        "offset": params.offset,
        "count": len(items),
    }


def get_sync_run(run_id: int) -> dict[str, Any] | None:
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
                            r.symbols_new,
                            r.symbols_delisted,
                            r.error_message,
                            v.id AS vendor_id,
                            v.code AS vendor_code,
                            v.name AS vendor_name,
                            count(p.id) AS raw_payload_count
                        FROM symbols.vendor_api_runs r
                        JOIN symbols.vendor_sources v
                            ON v.id = r.vendor_source_id
                        LEFT JOIN symbols.raw_vendor_payloads p
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
                            r.symbols_new,
                            r.symbols_delisted,
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
    item = _sync_run_row_to_summary(row)
    item["request_params"] = row["request_params"]
    return item


def _database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return database_url


def _sync_run_where_clause(params: SyncRunListParams) -> str:
    predicates = ["v.code = :vendor", "r.endpoint = :endpoint"]
    if params.status is not None:
        predicates.append("r.status = :status")
    return "WHERE " + " AND ".join(predicates)


def _sync_run_query_values(params: SyncRunListParams) -> dict[str, Any]:
    values: dict[str, Any] = {
        "vendor": params.vendor,
        "endpoint": params.endpoint,
        "limit": params.limit,
        "offset": params.offset,
    }
    if params.status is not None:
        values["status"] = params.status
    return values


def _sync_run_row_to_summary(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "vendor": _vendor(row),
        "endpoint": row["endpoint"],
        "run_status": row["status"],
        "started_at": _iso_or_none(row["started_at"]),
        "finished_at": _iso_or_none(row["finished_at"]),
        "records_seen": int(row["records_seen"]),
        "records_inserted": int(row["records_inserted"]),
        "records_failed": int(row["records_failed"]),
        "symbols_new": int(row["symbols_new"]),
        "symbols_delisted": int(row["symbols_delisted"]),
        "error_message": row["error_message"],
        "raw_payload_count": int(row["raw_payload_count"]),
    }


def _vendor(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["vendor_id"]),
        "code": row["vendor_code"],
        "name": row["vendor_name"],
    }


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
