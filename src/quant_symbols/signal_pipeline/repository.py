from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import os
from typing import Any

from quant_symbols.signal_pipeline.models import (
    ManualWatchlistRequest,
    SignalListParams,
    SignalSubmission,
    WatchlistListParams,
    WatchlistPatch,
)


def submit_signal_event(submission: SignalSubmission) -> dict[str, Any]:
    engine = _engine()
    try:
        with engine.begin() as connection:
            return SignalPipelineRepository(connection).submit_signal_event(submission)
    finally:
        engine.dispose()


def create_manual_watchlist_entry(request: ManualWatchlistRequest) -> dict[str, Any]:
    engine = _engine()
    try:
        with engine.begin() as connection:
            return SignalPipelineRepository(connection).create_manual_watchlist_entry(request)
    finally:
        engine.dispose()


def list_signal_events(params: SignalListParams) -> dict[str, Any]:
    engine = _engine()
    try:
        with engine.connect() as connection:
            return SignalPipelineRepository(connection).list_signal_events(params)
    finally:
        engine.dispose()


def get_signal_event(signal_event_id: int) -> dict[str, Any] | None:
    engine = _engine()
    try:
        with engine.connect() as connection:
            return SignalPipelineRepository(connection).get_signal_event(signal_event_id)
    finally:
        engine.dispose()


def list_watchlist_entries(params: WatchlistListParams) -> dict[str, Any]:
    engine = _engine()
    try:
        with engine.connect() as connection:
            return SignalPipelineRepository(connection).list_watchlist_entries(params)
    finally:
        engine.dispose()


def get_watchlist_entry(watchlist_entry_id: int) -> dict[str, Any] | None:
    engine = _engine()
    try:
        with engine.connect() as connection:
            return SignalPipelineRepository(connection).get_watchlist_entry(watchlist_entry_id)
    finally:
        engine.dispose()


def get_watchlist_by_ticker(ticker: str, *, market: str = "stocks", locale: str = "us") -> dict[str, Any] | None:
    engine = _engine()
    try:
        with engine.connect() as connection:
            return SignalPipelineRepository(connection).get_watchlist_by_ticker(
                ticker,
                market=market,
                locale=locale,
            )
    finally:
        engine.dispose()


def patch_watchlist_entry(watchlist_entry_id: int, patch: WatchlistPatch) -> dict[str, Any] | None:
    engine = _engine()
    try:
        with engine.begin() as connection:
            return SignalPipelineRepository(connection).patch_watchlist_entry(watchlist_entry_id, patch)
    finally:
        engine.dispose()


def signal_pipeline_status() -> dict[str, Any]:
    engine = _engine()
    try:
        with engine.connect() as connection:
            return SignalPipelineRepository(connection).signal_pipeline_status()
    finally:
        engine.dispose()


class SignalPipelineRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def ensure_source(self, *, name: str, source_type: str = "strategy") -> int:
        row = self.connection.execute(
            _text(
                """
                INSERT INTO signals.signal_sources (name, source_type)
                VALUES (:name, :source_type)
                ON CONFLICT (name) DO UPDATE
                SET updated_at = now()
                RETURNING id
                """
            ),
            {"name": name, "source_type": source_type},
        ).mappings().one()
        return int(row["id"])

    def submit_signal_event(self, submission: SignalSubmission) -> dict[str, Any]:
        source_id = self.ensure_source(name=submission.source, source_type="strategy")
        values = {
            "source_id": source_id,
            "external_event_id": submission.idempotency_key,
            "submitted_ticker": submission.ticker,
            "market": submission.market,
            "locale": submission.locale,
            "signal_type": submission.signal_type,
            "direction": submission.direction,
            "score": submission.score,
            "confidence": submission.confidence,
            "horizon": submission.horizon,
            "reason": submission.reason,
            "tags": _json(submission.tags),
            "metadata": _json(submission.metadata),
        }
        row = self.connection.execute(
            _text(
                """
                INSERT INTO signals.signal_events (
                    source_id, external_event_id, submitted_ticker, market, locale,
                    signal_type, direction, score, confidence, horizon, reason, tags, metadata
                )
                VALUES (
                    :source_id, :external_event_id, :submitted_ticker, :market, :locale,
                    :signal_type, :direction, :score, :confidence, :horizon, :reason,
                    CAST(:tags AS jsonb), CAST(:metadata AS jsonb)
                )
                ON CONFLICT (source_id, external_event_id) DO NOTHING
                RETURNING id, status
                """
            ),
            values,
        ).mappings().first()
        if row is not None:
            return {
                "status": "accepted",
                "signal_event_id": int(row["id"]),
                "watchlist_status": "pending_processing",
            }

        duplicate = self.connection.execute(
            _text(
                """
                SELECT id, status
                FROM signals.signal_events
                WHERE source_id = :source_id
                  AND external_event_id = :external_event_id
                """
            ),
            values,
        ).mappings().one()
        return {
            "status": "duplicate",
            "signal_event_id": int(duplicate["id"]),
            "watchlist_status": duplicate["status"],
        }

    def create_manual_watchlist_entry(self, request: ManualWatchlistRequest) -> dict[str, Any]:
        source_id = self.ensure_source(name=request.source, source_type="manual")
        symbol = self.resolve_symbol(
            ticker=request.ticker,
            market=request.market,
            locale=request.locale,
            active_preferred=True,
        )
        if symbol is not None and not symbol["active"]:
            symbol = None
        entry = self._upsert_watchlist_entry(
            source_id=source_id,
            signal_event_id=None,
            submitted_ticker=request.ticker,
            market=request.market,
            locale=request.locale,
            signal_type=request.signal_type,
            reason=request.reason,
            tags=request.tags,
            metadata=request.metadata,
            symbol=symbol,
            score=None,
            confidence=None,
            direction=None,
            horizon=None,
            created_by=request.created_by,
        )
        return {
            "status": entry["status"],
            "watchlist_entry_id": entry["id"],
            "symbol_id": entry["symbol_id"],
            "canonical_ticker": entry["canonical_ticker"],
        }

    def claim_pending_signal_events(self, *, batch_size: int) -> tuple[dict[str, Any], ...]:
        rows = self.connection.execute(
            _text(
                """
                UPDATE signals.signal_events e
                SET status = 'processing',
                    processing_started_at = now()
                WHERE e.id IN (
                    SELECT id
                    FROM signals.signal_events
                    WHERE status = 'pending'
                    ORDER BY received_at ASC, id ASC
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING e.*
                """
            ),
            {"batch_size": batch_size},
        ).mappings().all()
        return tuple(_row_to_dict(row) for row in rows)

    def process_signal_event(self, event: dict[str, Any]) -> dict[str, Any]:
        symbol = self.resolve_symbol(
            ticker=event["submitted_ticker"],
            market=event["market"],
            locale=event["locale"],
            active_preferred=True,
        )
        if symbol is None or not symbol["active"]:
            reason = "ticker could not be resolved to an active normalized symbol"
            self.connection.execute(
                _text(
                    """
                    UPDATE signals.signal_events
                    SET status = 'unresolved',
                        rejection_reason = :reason,
                        processed_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": event["id"], "reason": reason},
            )
            return {"status": "unresolved", "signal_event_id": event["id"], "rejection_reason": reason}

        entry = self._upsert_watchlist_entry(
            source_id=int(event["source_id"]),
            signal_event_id=int(event["id"]),
            submitted_ticker=event["submitted_ticker"],
            market=event["market"],
            locale=event["locale"],
            signal_type=event["signal_type"],
            reason=event["reason"],
            tags=tuple(event["tags"]),
            metadata=dict(event["metadata"]),
            symbol=symbol,
            score=event["score"],
            confidence=event["confidence"],
            direction=event["direction"],
            horizon=event["horizon"],
            created_by=None,
        )
        self.connection.execute(
            _text(
                """
                UPDATE signals.signal_events
                SET status = 'accepted',
                    symbol_id = :symbol_id,
                    canonical_ticker = :canonical_ticker,
                    processed_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": event["id"],
                "symbol_id": symbol["id"],
                "canonical_ticker": symbol["canonical_ticker"],
            },
        )
        return {
            "status": "accepted",
            "signal_event_id": event["id"],
            "watchlist_entry_id": entry["id"],
        }

    def fail_signal_event(self, event_id: int, error_message: str) -> None:
        self.connection.execute(
            _text(
                """
                UPDATE signals.signal_events
                SET status = 'failed',
                    rejection_reason = :error_message,
                    processed_at = now()
                WHERE id = :event_id
                """
            ),
            {"event_id": event_id, "error_message": error_message[:1000]},
        )

    def record_worker_heartbeat(
        self,
        *,
        worker_name: str,
        status: str,
        last_processed_signal_event_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            _text(
                """
                INSERT INTO signals.worker_heartbeats (
                    worker_name, status, last_processed_signal_event_id, metadata
                )
                VALUES (
                    :worker_name, :status, :last_processed_signal_event_id, CAST(:metadata AS jsonb)
                )
                ON CONFLICT (worker_name) DO UPDATE
                SET status = EXCLUDED.status,
                    last_seen_at = now(),
                    last_processed_signal_event_id = EXCLUDED.last_processed_signal_event_id,
                    metadata = EXCLUDED.metadata
                """
            ),
            {
                "worker_name": worker_name,
                "status": status,
                "last_processed_signal_event_id": last_processed_signal_event_id,
                "metadata": _json(metadata or {}),
            },
        )

    def resolve_symbol(
        self,
        *,
        ticker: str,
        market: str,
        locale: str,
        active_preferred: bool = True,
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            _text(
                """
                SELECT *
                FROM (
                    SELECT
                        s.id,
                        s.canonical_ticker,
                        s.name,
                        s.market,
                        s.locale,
                        s.active,
                        e.mic AS primary_exchange,
                        0 AS match_priority
                    FROM symbol_master.symbols s
                    LEFT JOIN symbol_master.exchanges e
                        ON e.id = s.primary_exchange_id
                    WHERE lower(s.canonical_ticker) = :ticker
                      AND s.market = :market
                      AND s.locale = :locale
                    UNION ALL
                    SELECT
                        s.id,
                        s.canonical_ticker,
                        s.name,
                        s.market,
                        s.locale,
                        s.active,
                        e.mic AS primary_exchange,
                        1 AS match_priority
                    FROM symbol_master.symbol_aliases a
                    JOIN symbol_master.symbols s
                        ON s.id = a.symbol_id
                    LEFT JOIN symbol_master.exchanges e
                        ON e.id = s.primary_exchange_id
                    WHERE lower(a.alias_value) = :ticker
                      AND a.active
                      AND s.market = :market
                      AND s.locale = :locale
                ) matches
                ORDER BY
                    CASE WHEN :active_preferred AND active THEN 0 ELSE 1 END,
                    match_priority ASC,
                    id DESC
                LIMIT 1
                """
            ),
            {
                "ticker": ticker.strip().lower(),
                "market": market,
                "locale": locale,
                "active_preferred": active_preferred,
            },
        ).mappings().first()
        return _row_to_dict(row) if row is not None else None

    def list_signal_events(self, params: SignalListParams) -> dict[str, Any]:
        where, values = _signal_where(params)
        rows = self.connection.execute(
            _text(
                f"""
                SELECT e.*, s.name AS source
                FROM signals.signal_events e
                JOIN signals.signal_sources s ON s.id = e.source_id
                {where}
                ORDER BY e.received_at DESC, e.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            values,
        ).mappings().all()
        return {"items": [_signal_row(row) for row in rows], "limit": params.limit, "offset": params.offset, "count": len(rows)}

    def get_signal_event(self, signal_event_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            _text(
                """
                SELECT e.*, s.name AS source
                FROM signals.signal_events e
                JOIN signals.signal_sources s ON s.id = e.source_id
                WHERE e.id = :signal_event_id
                """
            ),
            {"signal_event_id": signal_event_id},
        ).mappings().first()
        return _signal_row(row) if row is not None else None

    def list_watchlist_entries(self, params: WatchlistListParams) -> dict[str, Any]:
        where, values = _watchlist_where(params)
        rows = self.connection.execute(
            _text(
                f"""
                SELECT w.*, s.name AS source, sm.name AS company_name, sm.active AS symbol_active,
                       e.mic AS primary_exchange
                FROM signals.watchlist_entries w
                JOIN signals.signal_sources s ON s.id = w.source_id
                LEFT JOIN symbol_master.symbols sm ON sm.id = w.symbol_id
                LEFT JOIN symbol_master.exchanges e ON e.id = sm.primary_exchange_id
                {where}
                ORDER BY w.updated_at DESC, w.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            values,
        ).mappings().all()
        return {"items": [_watchlist_row(row, include_metadata=False) for row in rows], "limit": params.limit, "offset": params.offset, "count": len(rows)}

    def get_watchlist_entry(self, watchlist_entry_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            _text(
                """
                SELECT w.*, s.name AS source, sm.name AS company_name, sm.active AS symbol_active,
                       e.mic AS primary_exchange
                FROM signals.watchlist_entries w
                JOIN signals.signal_sources s ON s.id = w.source_id
                LEFT JOIN symbol_master.symbols sm ON sm.id = w.symbol_id
                LEFT JOIN symbol_master.exchanges e ON e.id = sm.primary_exchange_id
                WHERE w.id = :watchlist_entry_id
                """
            ),
            {"watchlist_entry_id": watchlist_entry_id},
        ).mappings().first()
        return _watchlist_row(row, include_metadata=True) if row is not None else None

    def get_watchlist_by_ticker(self, ticker: str, *, market: str, locale: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            _text(
                """
                SELECT w.*, s.name AS source, sm.name AS company_name, sm.active AS symbol_active,
                       e.mic AS primary_exchange
                FROM signals.watchlist_entries w
                JOIN signals.signal_sources s ON s.id = w.source_id
                LEFT JOIN symbol_master.symbols sm ON sm.id = w.symbol_id
                LEFT JOIN symbol_master.exchanges e ON e.id = sm.primary_exchange_id
                WHERE lower(w.submitted_ticker) = :ticker
                  AND w.market = :market
                  AND w.locale = :locale
                  AND w.active
                ORDER BY w.updated_at DESC, w.id DESC
                LIMIT 1
                """
            ),
            {"ticker": ticker.strip().lower(), "market": market, "locale": locale},
        ).mappings().first()
        return _watchlist_row(row, include_metadata=True) if row is not None else None

    def patch_watchlist_entry(self, watchlist_entry_id: int, patch: WatchlistPatch) -> dict[str, Any] | None:
        current = self.get_watchlist_entry(watchlist_entry_id)
        if current is None:
            return None
        values = {
            "id": watchlist_entry_id,
            "active": current["active"] if patch.active is None else patch.active,
            "status": patch.status or ("inactive" if patch.active is False else current["status"]),
            "reason": patch.reason or current["reason"],
            "tags": _json(current["tags"] if patch.tags is None else patch.tags),
            "metadata": _json(_merge_metadata(current["metadata"], patch.metadata, patch.update_reason)),
        }
        row = self.connection.execute(
            _text(
                """
                UPDATE signals.watchlist_entries
                SET active = :active,
                    status = :status,
                    reason = :reason,
                    tags = CAST(:tags AS jsonb),
                    metadata = CAST(:metadata AS jsonb),
                    deactivated_at = CASE
                        WHEN :active THEN NULL
                        ELSE COALESCE(deactivated_at, now())
                    END,
                    updated_at = now()
                WHERE id = :id
                RETURNING id
                """
            ),
            values,
        ).mappings().one()
        return self.get_watchlist_entry(int(row["id"]))

    def signal_pipeline_status(self) -> dict[str, Any]:
        counts = self.connection.execute(
            _text(
                """
                SELECT status, count(*) AS count
                FROM signals.signal_events
                GROUP BY status
                """
            )
        ).mappings().all()
        heartbeat = self.connection.execute(
            _text(
                """
                SELECT worker_name, status, last_seen_at, last_processed_signal_event_id, metadata
                FROM signals.worker_heartbeats
                ORDER BY last_seen_at DESC
                LIMIT 1
                """
            )
        ).mappings().first()
        return {
            "status": "ok",
            "signal_event_counts": {row["status"]: int(row["count"]) for row in counts},
            "latest_worker": _row_to_dict(heartbeat) if heartbeat is not None else None,
        }

    def _upsert_watchlist_entry(
        self,
        *,
        source_id: int,
        signal_event_id: int | None,
        submitted_ticker: str,
        market: str,
        locale: str,
        signal_type: str,
        reason: str,
        tags: tuple[str, ...],
        metadata: dict[str, Any],
        symbol: dict[str, Any] | None,
        score: Any,
        confidence: Any,
        direction: str | None,
        horizon: str | None,
        created_by: str | None,
    ) -> dict[str, Any]:
        values = {
            "symbol_id": symbol["id"] if symbol else None,
            "canonical_ticker": symbol["canonical_ticker"] if symbol else None,
            "submitted_ticker": submitted_ticker,
            "market": market,
            "locale": locale,
            "source_id": source_id,
            "signal_event_id": signal_event_id,
            "signal_type": signal_type,
            "reason": reason,
            "score": score,
            "confidence": confidence,
            "direction": direction,
            "horizon": horizon,
            "tags": _json(tags),
            "metadata": _json(metadata),
            "created_by": created_by,
        }
        if symbol is not None:
            conflict = "ON CONFLICT (symbol_id, source_id, signal_type) WHERE active AND symbol_id IS NOT NULL"
        else:
            conflict = "ON CONFLICT (source_id, lower(submitted_ticker), market, locale, signal_type) WHERE active AND symbol_id IS NULL"
        row = self.connection.execute(
            _text(
                f"""
                INSERT INTO signals.watchlist_entries (
                    symbol_id, canonical_ticker, submitted_ticker, market, locale,
                    source_id, signal_event_id, signal_type, reason, score, confidence,
                    direction, horizon, tags, metadata, created_by
                )
                VALUES (
                    :symbol_id, :canonical_ticker, :submitted_ticker, :market, :locale,
                    :source_id, :signal_event_id, :signal_type, :reason, :score, :confidence,
                    :direction, :horizon, CAST(:tags AS jsonb), CAST(:metadata AS jsonb), :created_by
                )
                {conflict} DO UPDATE
                SET signal_event_id = EXCLUDED.signal_event_id,
                    canonical_ticker = EXCLUDED.canonical_ticker,
                    submitted_ticker = EXCLUDED.submitted_ticker,
                    market = EXCLUDED.market,
                    locale = EXCLUDED.locale,
                    status = 'updated',
                    active = true,
                    reason = EXCLUDED.reason,
                    score = EXCLUDED.score,
                    confidence = EXCLUDED.confidence,
                    direction = EXCLUDED.direction,
                    horizon = EXCLUDED.horizon,
                    tags = EXCLUDED.tags,
                    metadata = EXCLUDED.metadata,
                    deactivated_at = NULL,
                    updated_at = now()
                RETURNING id, status, symbol_id, canonical_ticker
                """
            ),
            values,
        ).mappings().one()
        return _row_to_dict(row)


def _engine() -> Any:
    from sqlalchemy import create_engine

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_engine(database_url, pool_pre_ping=True)


def _text(sql: str) -> Any:
    from sqlalchemy import text

    return text(sql)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _row_to_dict(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key, value in tuple(result.items()):
        if isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, (datetime, date)):
            result[key] = value.isoformat()
    return result


def _signal_row(row: Any) -> dict[str, Any]:
    data = _row_to_dict(row)
    return {
        "id": data["id"],
        "source": data["source"],
        "idempotency_key": data["external_event_id"],
        "submitted_ticker": data["submitted_ticker"],
        "canonical_ticker": data["canonical_ticker"],
        "symbol_id": data["symbol_id"],
        "market": data["market"],
        "locale": data["locale"],
        "signal_type": data["signal_type"],
        "direction": data["direction"],
        "score": data["score"],
        "confidence": data["confidence"],
        "horizon": data["horizon"],
        "reason": data["reason"],
        "tags": data["tags"],
        "metadata": data["metadata"],
        "status": data["status"],
        "rejection_reason": data["rejection_reason"],
        "received_at": data["received_at"],
        "processed_at": data["processed_at"],
    }


def _watchlist_row(row: Any, *, include_metadata: bool) -> dict[str, Any]:
    data = _row_to_dict(row)
    item = {
        "id": data["id"],
        "submitted_ticker": data["submitted_ticker"],
        "canonical_ticker": data["canonical_ticker"],
        "symbol_id": data["symbol_id"],
        "company_name": data["company_name"],
        "market": data["market"],
        "locale": data["locale"],
        "active": data["active"],
        "symbol_active": data["symbol_active"],
        "primary_exchange": data["primary_exchange"],
        "source": data["source"],
        "signal_type": data["signal_type"],
        "status": data["status"],
        "reason": data["reason"],
        "score": data["score"],
        "confidence": data["confidence"],
        "direction": data["direction"],
        "horizon": data["horizon"],
        "tags": data["tags"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "latest_rejection_reason": data["latest_rejection_reason"],
    }
    if include_metadata:
        item["metadata"] = data["metadata"]
        item["signal_event_id"] = data["signal_event_id"]
    return item


def _signal_where(params: SignalListParams) -> tuple[str, dict[str, Any]]:
    predicates = []
    values: dict[str, Any] = {"limit": params.limit, "offset": params.offset}
    if params.source:
        predicates.append("s.name = :source")
        values["source"] = params.source
    if params.ticker:
        predicates.append("lower(e.submitted_ticker) = :ticker")
        values["ticker"] = params.ticker.lower()
    if params.status:
        predicates.append("e.status = :status")
        values["status"] = params.status
    if params.signal_type:
        predicates.append("e.signal_type = :signal_type")
        values["signal_type"] = params.signal_type
    return ("WHERE " + " AND ".join(predicates), values) if predicates else ("", values)


def _watchlist_where(params: WatchlistListParams) -> tuple[str, dict[str, Any]]:
    predicates = []
    values: dict[str, Any] = {"limit": params.limit, "offset": params.offset}
    if params.active is not None:
        predicates.append("w.active = :active")
        values["active"] = params.active
    if params.source:
        predicates.append("s.name = :source")
        values["source"] = params.source
    if params.ticker:
        predicates.append("lower(w.submitted_ticker) = :ticker")
        values["ticker"] = params.ticker.lower()
    if params.market:
        predicates.append("w.market = :market")
        values["market"] = params.market
    if params.locale:
        predicates.append("w.locale = :locale")
        values["locale"] = params.locale
    if params.tag:
        predicates.append("w.tags @> CAST(:tag_filter AS jsonb)")
        values["tag_filter"] = _json([params.tag])
    if params.signal_type:
        predicates.append("w.signal_type = :signal_type")
        values["signal_type"] = params.signal_type
    return ("WHERE " + " AND ".join(predicates), values) if predicates else ("", values)


def _merge_metadata(current: dict[str, Any], update: dict[str, Any] | None, update_reason: str | None) -> dict[str, Any]:
    merged = dict(current)
    if update:
        merged.update(update)
    if update_reason:
        merged["update_reason"] = update_reason
    return merged
