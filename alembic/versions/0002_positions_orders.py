"""positions and order management foundation

Revision ID: 0002_positions_orders
Revises: 0001_symbol_master_vendor_traceability
Create Date: 2026-06-09
"""

from alembic import op


revision = "0002_positions_orders"
down_revision = "0001_symbol_master_vendor_traceability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS trading")
    op.execute(
        """
        CREATE TABLE trading.portfolios (
            id bigserial PRIMARY KEY,
            name text NOT NULL,
            portfolio_type text NOT NULL DEFAULT 'paper',
            currency char(3) NOT NULL DEFAULT 'USD',
            enabled boolean NOT NULL DEFAULT true,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT portfolios_name_not_blank
                CHECK (length(trim(name)) > 0),
            CONSTRAINT portfolios_type_check
                CHECK (portfolio_type IN ('paper', 'manual', 'simulated')),
            CONSTRAINT portfolios_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT portfolios_name_unique
                UNIQUE (name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE trading.positions (
            id bigserial PRIMARY KEY,
            portfolio_id bigint NOT NULL
                REFERENCES trading.portfolios(id) ON DELETE RESTRICT,
            symbol_id bigint
                REFERENCES symbol_master.symbols(id) ON DELETE RESTRICT,
            submitted_ticker text NOT NULL,
            market text NOT NULL DEFAULT 'stocks',
            locale text NOT NULL DEFAULT 'us',
            quantity numeric(28, 8) NOT NULL DEFAULT 0,
            average_cost numeric(28, 8),
            market_value numeric(28, 8),
            realized_pnl numeric(28, 8),
            unrealized_pnl numeric(28, 8),
            status text NOT NULL DEFAULT 'open',
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            opened_at timestamptz NOT NULL DEFAULT now(),
            closed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT positions_submitted_ticker_not_blank
                CHECK (length(trim(submitted_ticker)) > 0),
            CONSTRAINT positions_market_not_blank
                CHECK (length(trim(market)) > 0),
            CONSTRAINT positions_locale_not_blank
                CHECK (length(trim(locale)) > 0),
            CONSTRAINT positions_status_check
                CHECK (status IN ('open', 'closed', 'flat', 'disabled')),
            CONSTRAINT positions_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT positions_closed_after_opened_check
                CHECK (closed_at IS NULL OR closed_at >= opened_at)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE trading.order_intents (
            id bigserial PRIMARY KEY,
            portfolio_id bigint NOT NULL
                REFERENCES trading.portfolios(id) ON DELETE RESTRICT,
            idempotency_key text NOT NULL,
            submitted_ticker text NOT NULL,
            symbol_id bigint
                REFERENCES symbol_master.symbols(id) ON DELETE RESTRICT,
            market text NOT NULL DEFAULT 'stocks',
            locale text NOT NULL DEFAULT 'us',
            side text NOT NULL,
            quantity numeric(28, 8),
            notional numeric(28, 8),
            order_type text NOT NULL,
            limit_price numeric(28, 8),
            stop_price numeric(28, 8),
            time_in_force text NOT NULL,
            source text NOT NULL,
            reason text NOT NULL,
            tags jsonb NOT NULL DEFAULT '[]'::jsonb,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            status text NOT NULL DEFAULT 'pending_validation',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT order_intents_idempotency_key_not_blank
                CHECK (length(trim(idempotency_key)) > 0),
            CONSTRAINT order_intents_submitted_ticker_not_blank
                CHECK (length(trim(submitted_ticker)) > 0),
            CONSTRAINT order_intents_side_check
                CHECK (side IN ('buy', 'sell')),
            CONSTRAINT order_intents_quantity_or_notional_check
                CHECK (
                    (quantity IS NOT NULL AND quantity > 0 AND notional IS NULL)
                    OR (notional IS NOT NULL AND notional > 0 AND quantity IS NULL)
                ),
            CONSTRAINT order_intents_order_type_check
                CHECK (order_type IN ('market', 'limit', 'stop', 'stop_limit')),
            CONSTRAINT order_intents_limit_price_check
                CHECK (limit_price IS NULL OR limit_price > 0),
            CONSTRAINT order_intents_stop_price_check
                CHECK (stop_price IS NULL OR stop_price > 0),
            CONSTRAINT order_intents_time_in_force_check
                CHECK (time_in_force IN ('day', 'gtc', 'ioc', 'fok')),
            CONSTRAINT order_intents_source_not_blank
                CHECK (length(trim(source)) > 0),
            CONSTRAINT order_intents_reason_not_blank
                CHECK (length(trim(reason)) > 0),
            CONSTRAINT order_intents_tags_array_check
                CHECK (jsonb_typeof(tags) = 'array'),
            CONSTRAINT order_intents_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT order_intents_status_check
                CHECK (
                    status IN (
                        'pending_validation', 'validated', 'rejected', 'queued',
                        'simulated', 'routed', 'partially_filled', 'filled',
                        'cancel_requested', 'cancelled', 'expired', 'failed'
                    )
                ),
            CONSTRAINT order_intents_portfolio_idempotency_unique
                UNIQUE (portfolio_id, idempotency_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE trading.order_events (
            id bigserial PRIMARY KEY,
            order_id bigint NOT NULL
                REFERENCES trading.order_intents(id) ON DELETE RESTRICT,
            event_type text NOT NULL,
            from_status text,
            to_status text,
            reason text,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT order_events_type_not_blank
                CHECK (length(trim(event_type)) > 0),
            CONSTRAINT order_events_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE trading.order_fills (
            id bigserial PRIMARY KEY,
            order_id bigint NOT NULL
                REFERENCES trading.order_intents(id) ON DELETE RESTRICT,
            position_id bigint
                REFERENCES trading.positions(id) ON DELETE RESTRICT,
            external_fill_id text,
            quantity numeric(28, 8) NOT NULL,
            price numeric(28, 8) NOT NULL,
            fees numeric(28, 8) NOT NULL DEFAULT 0,
            venue text,
            broker text,
            source text NOT NULL,
            filled_at timestamptz NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT order_fills_quantity_check
                CHECK (quantity > 0),
            CONSTRAINT order_fills_price_check
                CHECK (price > 0),
            CONSTRAINT order_fills_fees_check
                CHECK (fees >= 0),
            CONSTRAINT order_fills_source_not_blank
                CHECK (length(trim(source)) > 0),
            CONSTRAINT order_fills_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE trading.position_ledger_entries (
            id bigserial PRIMARY KEY,
            portfolio_id bigint NOT NULL
                REFERENCES trading.portfolios(id) ON DELETE RESTRICT,
            position_id bigint
                REFERENCES trading.positions(id) ON DELETE RESTRICT,
            symbol_id bigint
                REFERENCES symbol_master.symbols(id) ON DELETE RESTRICT,
            order_id bigint
                REFERENCES trading.order_intents(id) ON DELETE RESTRICT,
            fill_id bigint
                REFERENCES trading.order_fills(id) ON DELETE RESTRICT,
            entry_type text NOT NULL,
            quantity_delta numeric(28, 8) NOT NULL,
            cash_delta numeric(28, 8),
            price numeric(28, 8),
            fees numeric(28, 8) NOT NULL DEFAULT 0,
            source text NOT NULL,
            reason text,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            effective_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT position_ledger_entries_type_check
                CHECK (entry_type IN ('fill', 'adjustment', 'split', 'transfer', 'correction')),
            CONSTRAINT position_ledger_entries_source_not_blank
                CHECK (length(trim(source)) > 0),
            CONSTRAINT position_ledger_entries_fees_check
                CHECK (fees >= 0),
            CONSTRAINT position_ledger_entries_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trading.reject_position_ledger_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'position_ledger_entries is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER position_ledger_entries_append_only
        BEFORE UPDATE OR DELETE ON trading.position_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION trading.reject_position_ledger_mutation()
        """
    )
    op.execute(
        """
        CREATE TABLE trading.worker_heartbeats (
            id bigserial PRIMARY KEY,
            worker_name text NOT NULL,
            worker_type text NOT NULL,
            status text NOT NULL,
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT worker_heartbeats_name_type_unique
                UNIQUE (worker_name, worker_type),
            CONSTRAINT worker_heartbeats_status_check
                CHECK (status IN ('starting', 'running', 'idle', 'failed', 'stopped')),
            CONSTRAINT worker_heartbeats_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX positions_portfolio_symbol_unique_idx
            ON trading.positions (portfolio_id, symbol_id)
            WHERE symbol_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX positions_portfolio_unresolved_ticker_unique_idx
            ON trading.positions (portfolio_id, lower(submitted_ticker), market, locale)
            WHERE symbol_id IS NULL
        """
    )
    op.execute("CREATE INDEX positions_portfolio_status_idx ON trading.positions (portfolio_id, status)")
    op.execute("CREATE INDEX positions_ticker_lookup_idx ON trading.positions (lower(submitted_ticker), market, locale)")
    op.execute("CREATE INDEX order_intents_portfolio_status_idx ON trading.order_intents (portfolio_id, status, created_at DESC)")
    op.execute("CREATE INDEX order_intents_ticker_lookup_idx ON trading.order_intents (lower(submitted_ticker), market, locale)")
    op.execute("CREATE INDEX order_events_order_created_idx ON trading.order_events (order_id, created_at, id)")
    op.execute("CREATE INDEX order_fills_order_created_idx ON trading.order_fills (order_id, created_at)")
    op.execute(
        """
        CREATE UNIQUE INDEX order_fills_external_unique_idx
            ON trading.order_fills (order_id, source, external_fill_id)
            WHERE external_fill_id IS NOT NULL
        """
    )
    op.execute("CREATE INDEX position_ledger_portfolio_created_idx ON trading.position_ledger_entries (portfolio_id, created_at, id)")
    op.execute("CREATE INDEX position_ledger_position_created_idx ON trading.position_ledger_entries (position_id, created_at, id)")
    op.execute("CREATE INDEX worker_heartbeats_seen_idx ON trading.worker_heartbeats (worker_type, last_seen_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trading.worker_heartbeats")
    op.execute("DROP TRIGGER IF EXISTS position_ledger_entries_append_only ON trading.position_ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS trading.reject_position_ledger_mutation")
    op.execute("DROP TABLE IF EXISTS trading.position_ledger_entries")
    op.execute("DROP TABLE IF EXISTS trading.order_fills")
    op.execute("DROP TABLE IF EXISTS trading.order_events")
    op.execute("DROP TABLE IF EXISTS trading.order_intents")
    op.execute("DROP TABLE IF EXISTS trading.positions")
    op.execute("DROP TABLE IF EXISTS trading.portfolios")
    op.execute("DROP SCHEMA IF EXISTS trading")
