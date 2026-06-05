"""Database repository for symbol-master upserts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from quant_symbols.symbol_master.massive_mapper import AliasCandidate, ExchangeCandidate, SymbolCandidate


@dataclass(frozen=True)
class RawPayloadLink:
    id: int


class SymbolMasterRepository:
    """SQLAlchemy-backed repository for the Day 2 symbol-master schema."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def vendor_source_id(self, code: str) -> int:
        row = self.connection.execute(
            _text("SELECT id FROM symbol_master.vendor_sources WHERE code = :code"),
            {"code": code},
        ).mappings().first()
        if row is None:
            raise RuntimeError(f"vendor source not found: {code}")
        return int(row["id"])

    def ensure_vendor_source(self, *, code: str, name: str, base_url: str | None = None) -> int:
        row = self.connection.execute(
            _text(
                """
                INSERT INTO symbol_master.vendor_sources (code, name, base_url)
                VALUES (:code, :name, :base_url)
                ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name,
                    base_url = EXCLUDED.base_url,
                    updated_at = now()
                RETURNING id
                """
            ),
            {"code": code, "name": name, "base_url": base_url},
        ).mappings().one()
        return int(row["id"])

    def start_run(self, *, vendor_source_id: int, endpoint: str, request_params: dict[str, Any]) -> int:
        row = self.connection.execute(
            _text(
                """
                INSERT INTO symbol_master.vendor_api_runs
                    (vendor_source_id, endpoint, request_params, status)
                VALUES (:vendor_source_id, :endpoint, CAST(:request_params AS jsonb), 'running')
                RETURNING id
                """
            ),
            {
                "vendor_source_id": vendor_source_id,
                "endpoint": endpoint,
                "request_params": json.dumps(request_params, sort_keys=True),
            },
        ).mappings().one()
        return int(row["id"])

    def finish_run(
        self,
        *,
        run_id: int,
        status: str,
        records_seen: int,
        records_inserted: int,
        records_failed: int,
        error_message: str | None = None,
    ) -> None:
        self.connection.execute(
            _text(
                """
                UPDATE symbol_master.vendor_api_runs
                SET status = :status,
                    finished_at = now(),
                    records_seen = :records_seen,
                    records_inserted = :records_inserted,
                    records_failed = :records_failed,
                    error_message = :error_message
                WHERE id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "status": status,
                "records_seen": records_seen,
                "records_inserted": records_inserted,
                "records_failed": records_failed,
                "error_message": error_message,
            },
        )

    def insert_raw_payload(
        self,
        *,
        vendor_source_id: int,
        run_id: int,
        provider_ticker: str,
        payload: dict[str, Any],
    ) -> RawPayloadLink:
        row = self.connection.execute(
            _text(
                """
                INSERT INTO symbol_master.raw_vendor_payloads
                    (vendor_source_id, vendor_api_run_id, provider_record_id, provider_ticker, payload)
                VALUES
                    (:vendor_source_id, :run_id, :provider_record_id, :provider_ticker, CAST(:payload AS jsonb))
                RETURNING id
                """
            ),
            {
                "vendor_source_id": vendor_source_id,
                "run_id": run_id,
                "provider_record_id": provider_ticker,
                "provider_ticker": provider_ticker,
                "payload": json.dumps(payload, sort_keys=True),
            },
        ).mappings().one()
        return RawPayloadLink(id=int(row["id"]))

    def upsert_candidate(
        self,
        *,
        vendor_source_id: int,
        run_id: int,
        raw_payload_id: int,
        candidate: SymbolCandidate,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        exchange_id = None
        if candidate.primary_exchange is not None:
            exchange_id = self._upsert_exchange(candidate.primary_exchange, counts)
        symbol_id = self._upsert_symbol(run_id, raw_payload_id, exchange_id, candidate, counts)
        self._upsert_vendor_id(vendor_source_id, run_id, raw_payload_id, symbol_id, candidate, counts)
        for alias in candidate.aliases:
            self._upsert_alias(vendor_source_id, raw_payload_id, symbol_id, alias, counts)
        return counts

    def latest_run_summary(self) -> dict[str, Any] | None:
        row = self.connection.execute(
            _text(
                """
                SELECT r.id, v.code AS vendor, r.endpoint, r.status, r.started_at, r.finished_at,
                       r.records_seen, r.records_inserted, r.records_failed, r.error_message
                FROM symbol_master.vendor_api_runs r
                JOIN symbol_master.vendor_sources v ON v.id = r.vendor_source_id
                ORDER BY r.started_at DESC, r.id DESC
                LIMIT 1
                """
            )
        ).mappings().first()
        return dict(row) if row is not None else None

    def _upsert_exchange(self, exchange: ExchangeCandidate, counts: dict[str, int]) -> int:
        row = self.connection.execute(
            _text("SELECT id, name FROM symbol_master.exchanges WHERE mic = :mic"),
            {"mic": exchange.mic},
        ).mappings().first()
        if row is None:
            inserted = self.connection.execute(
                _text(
                    """
                    INSERT INTO symbol_master.exchanges (mic, name)
                    VALUES (:mic, :name)
                    RETURNING id
                    """
                ),
                {"mic": exchange.mic, "name": exchange.name},
            ).mappings().one()
            _increment(counts, "exchanges_inserted")
            return int(inserted["id"])
        if row["name"] != exchange.name and exchange.provisional is False:
            self.connection.execute(
                _text("UPDATE symbol_master.exchanges SET name = :name, updated_at = now() WHERE id = :id"),
                {"id": row["id"], "name": exchange.name},
            )
            _increment(counts, "exchanges_updated")
        else:
            _increment(counts, "exchanges_unchanged")
        return int(row["id"])

    def _upsert_symbol(
        self,
        run_id: int,
        raw_payload_id: int,
        exchange_id: int | None,
        candidate: SymbolCandidate,
        counts: dict[str, int],
    ) -> int:
        row = self._find_symbol(candidate)
        values = {
            "canonical_ticker": candidate.canonical_ticker,
            "name": candidate.name,
            "market": candidate.market,
            "locale": candidate.locale,
            "currency": candidate.currency,
            "primary_exchange_id": exchange_id,
            "asset_class": candidate.asset_class,
            "security_type": candidate.security_type,
            "active": candidate.active,
            "cik": candidate.cik,
            "composite_figi": candidate.composite_figi,
            "share_class_figi": candidate.share_class_figi,
            "run_id": run_id,
            "payload_id": raw_payload_id,
            "delisted_at": candidate.delisted_at,
        }
        if row is None:
            inserted = self.connection.execute(
                _text(
                    """
                    INSERT INTO symbol_master.symbols
                        (canonical_ticker, name, market, locale, currency, primary_exchange_id,
                         asset_class, security_type, active, cik, composite_figi, share_class_figi,
                         first_seen_run_id, first_seen_payload_id, last_seen_run_id, last_seen_payload_id,
                         delisted_at)
                    VALUES
                        (:canonical_ticker, :name, :market, :locale, :currency, :primary_exchange_id,
                         :asset_class, :security_type, :active, :cik, :composite_figi, :share_class_figi,
                         :run_id, :payload_id, :run_id, :payload_id, :delisted_at)
                    RETURNING id
                    """
                ),
                values,
            ).mappings().one()
            _increment(counts, "symbols_inserted")
            return int(inserted["id"])

        changed = _symbol_domain_changed(row, values)
        if row["active"] is True and candidate.active is False:
            _increment(counts, "deactivated")
        if row["active"] is False and candidate.active is True:
            _increment(counts, "reactivated")
        self.connection.execute(
            _text(
                """
                UPDATE symbol_master.symbols
                SET name = :name,
                    currency = :currency,
                    primary_exchange_id = :primary_exchange_id,
                    asset_class = :asset_class,
                    security_type = :security_type,
                    active = :active,
                    cik = :cik,
                    composite_figi = :composite_figi,
                    share_class_figi = :share_class_figi,
                    last_seen_run_id = :run_id,
                    last_seen_payload_id = :payload_id,
                    delisted_at = :delisted_at,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {**values, "id": row["id"]},
        )
        _increment(counts, "symbols_updated" if changed else "symbols_unchanged")
        return int(row["id"])

    def _find_symbol(self, candidate: SymbolCandidate) -> dict[str, Any] | None:
        if candidate.composite_figi:
            row = self.connection.execute(
                _text("SELECT * FROM symbol_master.symbols WHERE composite_figi = :figi"),
                {"figi": candidate.composite_figi},
            ).mappings().first()
            if row is not None:
                return dict(row)
        row = self.connection.execute(
            _text(
                """
                SELECT * FROM symbol_master.symbols
                WHERE lower(locale) = lower(:locale)
                  AND lower(market) = lower(:market)
                  AND lower(canonical_ticker) = lower(:ticker)
                ORDER BY active DESC, id ASC
                LIMIT 1
                """
            ),
            {
                "locale": candidate.locale,
                "market": candidate.market,
                "ticker": candidate.canonical_ticker,
            },
        ).mappings().first()
        return dict(row) if row is not None else None

    def _upsert_vendor_id(
        self,
        vendor_source_id: int,
        run_id: int,
        raw_payload_id: int,
        symbol_id: int,
        candidate: SymbolCandidate,
        counts: dict[str, int],
    ) -> None:
        row = self.connection.execute(
            _text(
                """
                SELECT id, symbol_id, active FROM symbol_master.symbol_vendor_ids
                WHERE vendor_source_id = :vendor_source_id
                  AND lower(vendor_symbol) = lower(:vendor_symbol)
                ORDER BY active DESC, id ASC
                LIMIT 1
                """
            ),
            {"vendor_source_id": vendor_source_id, "vendor_symbol": candidate.source_ticker},
        ).mappings().first()
        if row is None:
            self.connection.execute(
                _text(
                    """
                    INSERT INTO symbol_master.symbol_vendor_ids
                        (symbol_id, vendor_source_id, vendor_symbol, vendor_asset_id,
                         first_seen_run_id, first_seen_payload_id, last_seen_run_id, last_seen_payload_id, active)
                    VALUES
                        (:symbol_id, :vendor_source_id, :vendor_symbol, :vendor_asset_id,
                         :run_id, :payload_id, :run_id, :payload_id, :active)
                    """
                ),
                {
                    "symbol_id": symbol_id,
                    "vendor_source_id": vendor_source_id,
                    "vendor_symbol": candidate.source_ticker,
                    "vendor_asset_id": candidate.composite_figi,
                    "run_id": run_id,
                    "payload_id": raw_payload_id,
                    "active": candidate.active,
                },
            )
            _increment(counts, "vendor_ids_inserted")
            return
        changed = row["symbol_id"] != symbol_id or row["active"] != candidate.active
        self.connection.execute(
            _text(
                """
                UPDATE symbol_master.symbol_vendor_ids
                SET symbol_id = :symbol_id,
                    vendor_asset_id = :vendor_asset_id,
                    last_seen_run_id = :run_id,
                    last_seen_payload_id = :payload_id,
                    active = :active,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "symbol_id": symbol_id,
                "vendor_asset_id": candidate.composite_figi,
                "run_id": run_id,
                "payload_id": raw_payload_id,
                "active": candidate.active,
            },
        )
        _increment(counts, "vendor_ids_updated" if changed else "vendor_ids_unchanged")

    def _upsert_alias(
        self,
        vendor_source_id: int,
        raw_payload_id: int,
        symbol_id: int,
        alias: AliasCandidate,
        counts: dict[str, int],
    ) -> None:
        row = self.connection.execute(
            _text(
                """
                SELECT id FROM symbol_master.symbol_aliases
                WHERE alias_type = :alias_type
                  AND lower(alias_value) = lower(:alias_value)
                  AND active
                """
            ),
            {"alias_type": alias.alias_type, "alias_value": alias.alias_value},
        ).mappings().first()
        if row is not None:
            _increment(counts, "aliases_unchanged")
            return
        self.connection.execute(
            _text(
                """
                INSERT INTO symbol_master.symbol_aliases
                    (symbol_id, alias_type, alias_value, source_vendor_id, source_payload_id)
                VALUES
                    (:symbol_id, :alias_type, :alias_value, :source_vendor_id, :source_payload_id)
                """
            ),
            {
                "symbol_id": symbol_id,
                "alias_type": alias.alias_type,
                "alias_value": alias.alias_value,
                "source_vendor_id": vendor_source_id,
                "source_payload_id": raw_payload_id,
            },
        )
        _increment(counts, "aliases_inserted")


def _symbol_domain_changed(row: dict[str, Any], values: dict[str, Any]) -> bool:
    keys = (
        "name",
        "currency",
        "primary_exchange_id",
        "asset_class",
        "security_type",
        "active",
        "cik",
        "composite_figi",
        "share_class_figi",
        "delisted_at",
    )
    for key in keys:
        if _normalize_compare(row.get(key)) != _normalize_compare(values.get(key)):
            return True
    return False


def _normalize_compare(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(microsecond=0)
    return value


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _text(sql: str) -> Any:
    try:
        from sqlalchemy import text
    except ModuleNotFoundError as exc:
        raise RuntimeError("SQLAlchemy is required for database-backed symbol sync") from exc
    return text(sql)
