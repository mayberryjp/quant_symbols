"""Database repository for symbol-master upserts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from quant_symbols.symbol_master.massive_mapper import AliasCandidate, ExchangeCandidate, SymbolCandidate
from quant_symbols.symbol_master.normalization import (
    MassiveAliasCandidate,
    MassiveExchangeCandidate,
    MassiveTickerCandidate,
    map_massive_alias_candidates,
)


@dataclass(frozen=True)
class RawPayloadLink:
    id: int


@dataclass(frozen=True)
class RawPayloadRow:
    id: int
    payload: dict[str, Any]
    provider_ticker: str | None = None


@dataclass(frozen=True)
class ExchangeUpsertResult:
    exchange_id: int | None
    counts: dict[str, int]


@dataclass(frozen=True)
class SymbolVendorIdentityUpsertResult:
    symbol_id: int
    counts: dict[str, int]


@dataclass(frozen=True)
class AliasUpsertResult:
    counts: dict[str, int]


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
                    (vendor_source_id, endpoint, request_params, status, started_at)
                VALUES (:vendor_source_id, :endpoint, CAST(:request_params AS jsonb), 'running', clock_timestamp())
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
        symbols_new: int = 0,
        symbols_delisted: int = 0,
        error_message: str | None = None,
    ) -> None:
        self.connection.execute(
            _text(
                """
                UPDATE symbol_master.vendor_api_runs
                SET status = :status,
                    finished_at = clock_timestamp(),
                    records_seen = :records_seen,
                    records_inserted = :records_inserted,
                    records_failed = :records_failed,
                    symbols_new = :symbols_new,
                    symbols_delisted = :symbols_delisted,
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
                "symbols_new": symbols_new,
                "symbols_delisted": symbols_delisted,
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

    def latest_successful_massive_ticker_run_with_payloads(self) -> dict[str, Any] | None:
        row = self.connection.execute(
            _text(
                """
                SELECT r.id, v.code AS vendor, r.endpoint, r.status, r.started_at, r.finished_at,
                       r.records_seen, r.records_inserted, r.records_failed
                FROM symbol_master.vendor_api_runs r
                JOIN symbol_master.vendor_sources v ON v.id = r.vendor_source_id
                WHERE v.code = 'massive'
                  AND r.endpoint = '/v3/reference/tickers'
                  AND r.status = 'succeeded'
                  AND EXISTS (
                      SELECT 1
                      FROM symbol_master.raw_vendor_payloads p
                      WHERE p.vendor_api_run_id = r.id
                        AND p.vendor_source_id = r.vendor_source_id
                  )
                ORDER BY r.finished_at DESC NULLS LAST, r.started_at DESC, r.id DESC
                LIMIT 1
                """
            )
        ).mappings().first()
        return dict(row) if row is not None else None

    def raw_payload_rows_for_run(
        self,
        *,
        vendor_source_id: int,
        run_id: int,
    ) -> tuple[RawPayloadRow, ...]:
        rows = self.connection.execute(
            _text(
                """
                SELECT id, provider_ticker, payload
                FROM symbol_master.raw_vendor_payloads
                WHERE vendor_source_id = :vendor_source_id
                  AND vendor_api_run_id = :run_id
                ORDER BY id
                """
            ),
            {"vendor_source_id": vendor_source_id, "run_id": run_id},
        ).mappings().all()
        return tuple(
            RawPayloadRow(
                id=int(row["id"]),
                provider_ticker=row["provider_ticker"],
                payload=dict(row["payload"]),
            )
            for row in rows
        )

    def upsert_exchange_candidate(self, exchange: MassiveExchangeCandidate | None) -> ExchangeUpsertResult:
        counts: dict[str, int] = {}
        if exchange is None:
            _increment(counts, "exchanges_skipped")
            return ExchangeUpsertResult(exchange_id=None, counts=counts)
        exchange_id = self._upsert_exchange(exchange, counts)
        return ExchangeUpsertResult(exchange_id=exchange_id, counts=counts)

    def upsert_symbol_vendor_identity_candidate(
        self,
        *,
        vendor_source_id: int,
        run_id: int,
        raw_payload_id: int,
        candidate: MassiveTickerCandidate,
        primary_exchange_id: int | None = None,
    ) -> SymbolVendorIdentityUpsertResult:
        """Upsert one normalized symbol and its Massive vendor identity.

        This Slice 3 entrypoint deliberately does not create exchanges or aliases.
        Callers that need an exchange link should run the Slice 2 exchange upsert
        first and pass the returned exchange id here.
        """

        values = _massive_symbol_values(candidate, run_id, raw_payload_id, primary_exchange_id)
        counts: dict[str, int] = {}
        row = self._find_massive_symbol(vendor_source_id, candidate)
        symbol_id = self._upsert_massive_symbol_row(row, values, counts)
        self._upsert_massive_vendor_id(
            vendor_source_id=vendor_source_id,
            run_id=run_id,
            raw_payload_id=raw_payload_id,
            symbol_id=symbol_id,
            candidate=candidate,
            counts=counts,
        )
        return SymbolVendorIdentityUpsertResult(symbol_id=symbol_id, counts=counts)

    def upsert_aliases_for_massive_candidate(
        self,
        *,
        vendor_source_id: int,
        raw_payload_id: int,
        symbol_id: int,
        candidate: MassiveTickerCandidate,
    ) -> AliasUpsertResult:
        """Upsert aliases for an already-upserted Massive symbol candidate.

        This Slice 4 entrypoint deliberately writes only symbol aliases. Callers
        must create or locate the symbol row first and pass its id here.
        """

        counts: dict[str, int] = {}
        for alias in map_massive_alias_candidates(candidate):
            self._upsert_alias(vendor_source_id, raw_payload_id, symbol_id, alias, counts)
        return AliasUpsertResult(counts=counts)

    def _upsert_exchange(self, exchange: ExchangeCandidate | MassiveExchangeCandidate, counts: dict[str, int]) -> int:
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

    def _find_massive_symbol(self, vendor_source_id: int, candidate: MassiveTickerCandidate) -> dict[str, Any] | None:
        if candidate.composite_figi:
            row = self.connection.execute(
                _text("SELECT * FROM symbol_master.symbols WHERE composite_figi = :figi"),
                {"figi": candidate.composite_figi},
            ).mappings().first()
            if row is not None:
                return dict(row)
        if candidate.source_ticker:
            row = self.connection.execute(
                _text(
                    """
                    SELECT s.*
                    FROM symbol_master.symbol_vendor_ids v
                    JOIN symbol_master.symbols s ON s.id = v.symbol_id
                    WHERE v.vendor_source_id = :vendor_source_id
                      AND lower(v.vendor_symbol) = lower(:vendor_symbol)
                    ORDER BY v.active DESC, s.active DESC, s.id ASC
                    LIMIT 1
                    """
                ),
                {"vendor_source_id": vendor_source_id, "vendor_symbol": candidate.source_ticker},
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
                "locale": _required_text(candidate.locale, "locale"),
                "market": _required_text(candidate.market, "market"),
                "ticker": _required_text(candidate.canonical_ticker, "canonical_ticker"),
            },
        ).mappings().first()
        return dict(row) if row is not None else None

    def _upsert_massive_symbol_row(
        self,
        row: dict[str, Any] | None,
        values: dict[str, Any],
        counts: dict[str, int],
    ) -> int:
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

        changed = _massive_symbol_domain_changed(row, values)
        self.connection.execute(
            _text(
                """
                UPDATE symbol_master.symbols
                SET canonical_ticker = :canonical_ticker,
                    name = :name,
                    market = :market,
                    locale = :locale,
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

    def _upsert_massive_vendor_id(
        self,
        *,
        vendor_source_id: int,
        run_id: int,
        raw_payload_id: int,
        symbol_id: int,
        candidate: MassiveTickerCandidate,
        counts: dict[str, int],
    ) -> None:
        row = None
        if candidate.composite_figi:
            row = self.connection.execute(
                _text(
                    """
                    SELECT id, symbol_id, vendor_symbol, vendor_asset_id, active
                    FROM symbol_master.symbol_vendor_ids
                    WHERE vendor_source_id = :vendor_source_id
                      AND vendor_asset_id = :vendor_asset_id
                    ORDER BY active DESC, id ASC
                    LIMIT 1
                    """
                ),
                {"vendor_source_id": vendor_source_id, "vendor_asset_id": candidate.composite_figi},
            ).mappings().first()
        if row is None:
            row = self.connection.execute(
                _text(
                    """
                    SELECT id, symbol_id, vendor_symbol, vendor_asset_id, active
                    FROM symbol_master.symbol_vendor_ids
                    WHERE vendor_source_id = :vendor_source_id
                      AND lower(vendor_symbol) = lower(:vendor_symbol)
                    ORDER BY active DESC, id ASC
                    LIMIT 1
                    """
                ),
                {
                    "vendor_source_id": vendor_source_id,
                    "vendor_symbol": _required_text(candidate.source_ticker, "source_ticker"),
                },
            ).mappings().first()

        values = {
            "symbol_id": symbol_id,
            "vendor_source_id": vendor_source_id,
            "vendor_symbol": _required_text(candidate.source_ticker, "source_ticker"),
            "vendor_asset_id": candidate.composite_figi,
            "run_id": run_id,
            "payload_id": raw_payload_id,
            "active": candidate.active if candidate.active is not None else True,
        }
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
                values,
            )
            _increment(counts, "vendor_ids_inserted")
            return

        changed = (
            row["symbol_id"] != symbol_id
            or row["vendor_symbol"] != values["vendor_symbol"]
            or row["vendor_asset_id"] != values["vendor_asset_id"]
            or row["active"] != values["active"]
        )
        self.connection.execute(
            _text(
                """
                UPDATE symbol_master.symbol_vendor_ids
                SET symbol_id = :symbol_id,
                    vendor_symbol = :vendor_symbol,
                    vendor_asset_id = :vendor_asset_id,
                    last_seen_run_id = :run_id,
                    last_seen_payload_id = :payload_id,
                    active = :active,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {**values, "id": row["id"]},
        )
        _increment(counts, "vendor_ids_updated" if changed else "vendor_ids_unchanged")

    def _upsert_vendor_id(
        self,
        vendor_source_id: int,
        run_id: int,
        raw_payload_id: int,
        symbol_id: int,
        candidate: SymbolCandidate,
        counts: dict[str, int],
    ) -> None:
        row = None
        if candidate.composite_figi:
            row = self.connection.execute(
                _text(
                    """
                    SELECT id, symbol_id, vendor_symbol, active FROM symbol_master.symbol_vendor_ids
                    WHERE vendor_source_id = :vendor_source_id
                      AND vendor_asset_id = :vendor_asset_id
                    ORDER BY active DESC, id ASC
                    LIMIT 1
                    """
                ),
                {"vendor_source_id": vendor_source_id, "vendor_asset_id": candidate.composite_figi},
            ).mappings().first()
        if row is None:
            row = self.connection.execute(
                _text(
                    """
                    SELECT id, symbol_id, vendor_symbol, active FROM symbol_master.symbol_vendor_ids
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
        changed = (
            row["symbol_id"] != symbol_id
            or row["vendor_symbol"] != candidate.source_ticker
            or row["active"] != candidate.active
        )
        self.connection.execute(
            _text(
                """
                UPDATE symbol_master.symbol_vendor_ids
                SET symbol_id = :symbol_id,
                    vendor_symbol = :vendor_symbol,
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
                "vendor_symbol": candidate.source_ticker,
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
        alias: AliasCandidate | MassiveAliasCandidate,
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


def _massive_symbol_values(
    candidate: MassiveTickerCandidate,
    run_id: int,
    raw_payload_id: int,
    primary_exchange_id: int | None,
) -> dict[str, Any]:
    return {
        "canonical_ticker": _required_text(candidate.canonical_ticker, "canonical_ticker"),
        "name": candidate.name,
        "market": _required_text(candidate.market, "market"),
        "locale": _required_text(candidate.locale, "locale"),
        "currency": _currency_code(candidate.currency_name),
        "primary_exchange_id": primary_exchange_id,
        "asset_class": _asset_class_for_schema(candidate.asset_type),
        "security_type": candidate.security_type or "unknown",
        "active": candidate.active if candidate.active is not None else True,
        "cik": candidate.cik,
        "composite_figi": candidate.composite_figi,
        "share_class_figi": candidate.share_class_figi,
        "run_id": run_id,
        "payload_id": raw_payload_id,
        "delisted_at": candidate.delisted_utc,
    }


def _massive_symbol_domain_changed(row: dict[str, Any], values: dict[str, Any]) -> bool:
    keys = (
        "canonical_ticker",
        "name",
        "market",
        "locale",
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


def _asset_class_for_schema(asset_type: str) -> str:
    if asset_type in {"equity", "fund", "crypto", "forex", "index"}:
        return asset_type
    return "other"


def _currency_code(value: str | None) -> str:
    if isinstance(value, str) and len(value.strip()) == 3:
        return value.strip().upper()
    return "USD"


def _required_text(value: str | None, field_name: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError(f"Massive ticker candidate is missing required field: {field_name}")


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
