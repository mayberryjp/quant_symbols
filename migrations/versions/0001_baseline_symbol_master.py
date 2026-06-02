"""Create baseline symbol master schema."""

from __future__ import annotations

from alembic import op

revision = "0001_baseline_symbol_master"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS btree_gist;

        CREATE SCHEMA IF NOT EXISTS symbol_master;
        CREATE SCHEMA IF NOT EXISTS market_data;
        CREATE SCHEMA IF NOT EXISTS signals;

        CREATE TABLE symbol_master.vendors (
            id smallserial PRIMARY KEY,
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            base_url text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        INSERT INTO symbol_master.vendors (code, name, base_url)
        VALUES ('massive', 'Massive / Polygon', 'https://api.polygon.io')
        ON CONFLICT (code) DO NOTHING;

        CREATE TABLE symbol_master.exchanges (
            id bigserial PRIMARY KEY,
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            country_code char(2) NOT NULL DEFAULT 'US',
            timezone text NOT NULL DEFAULT 'America/New_York',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        INSERT INTO symbol_master.exchanges (code, name)
        VALUES
            ('XNYS', 'New York Stock Exchange'),
            ('XNAS', 'Nasdaq Stock Market'),
            ('ARCX', 'NYSE Arca'),
            ('BATS', 'Cboe BZX'),
            ('OTCM', 'OTC Markets')
        ON CONFLICT (code) DO NOTHING;

        CREATE TABLE symbol_master.assets (
            id bigserial PRIMARY KEY,
            canonical_symbol text NOT NULL UNIQUE,
            name text NOT NULL,
            asset_type text NOT NULL,
            primary_exchange_id bigint REFERENCES symbol_master.exchanges(id),
            currency char(3) NOT NULL DEFAULT 'USD',
            locale text NOT NULL DEFAULT 'us',
            cik text,
            composite_figi text,
            share_class_figi text,
            active boolean NOT NULL DEFAULT true,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            delisted_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT assets_asset_type_check
                CHECK (asset_type IN ('stock', 'etf', 'adr', 'reit', 'unit', 'warrant', 'other')),
            CONSTRAINT assets_symbol_not_blank
                CHECK (length(trim(canonical_symbol)) > 0)
        );

        CREATE INDEX assets_asset_type_idx ON symbol_master.assets (asset_type);
        CREATE INDEX assets_active_idx ON symbol_master.assets (active);
        CREATE INDEX assets_primary_exchange_id_idx ON symbol_master.assets (primary_exchange_id);
        CREATE UNIQUE INDEX assets_composite_figi_unique_idx
            ON symbol_master.assets (composite_figi)
            WHERE composite_figi IS NOT NULL;

        CREATE TABLE symbol_master.etf_profiles (
            asset_id bigint PRIMARY KEY REFERENCES symbol_master.assets(id) ON DELETE CASCADE,
            is_leveraged boolean NOT NULL DEFAULT false,
            is_inverse boolean NOT NULL DEFAULT false,
            is_index_etf boolean NOT NULL DEFAULT false,
            leverage_factor numeric(8, 3),
            benchmark_name text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT etf_profiles_leverage_factor_check
                CHECK (leverage_factor IS NULL OR leverage_factor > 0)
        );

        CREATE TABLE symbol_master.vendor_symbols (
            id bigserial PRIMARY KEY,
            vendor_id smallint NOT NULL REFERENCES symbol_master.vendors(id),
            asset_id bigint REFERENCES symbol_master.assets(id),
            vendor_symbol text NOT NULL,
            vendor_name text,
            vendor_market text,
            vendor_locale text,
            vendor_primary_exchange text,
            vendor_type text,
            vendor_currency text,
            active boolean NOT NULL DEFAULT true,
            active_from date NOT NULL DEFAULT CURRENT_DATE,
            active_to date,
            raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT vendor_symbols_symbol_not_blank
                CHECK (length(trim(vendor_symbol)) > 0),
            CONSTRAINT vendor_symbols_active_window_check
                CHECK (active_to IS NULL OR active_to >= active_from),
            CONSTRAINT vendor_symbols_vendor_symbol_window_excl
                EXCLUDE USING gist (
                    vendor_id WITH =,
                    vendor_symbol WITH =,
                    daterange(active_from, COALESCE(active_to, 'infinity'::date), '[]') WITH &&
                )
        );

        CREATE INDEX vendor_symbols_asset_id_idx ON symbol_master.vendor_symbols (asset_id);
        CREATE INDEX vendor_symbols_active_idx ON symbol_master.vendor_symbols (active);
        CREATE INDEX vendor_symbols_window_idx
            ON symbol_master.vendor_symbols (vendor_id, vendor_symbol, active_from, active_to);
        CREATE INDEX vendor_symbols_raw_payload_gin_idx
            ON symbol_master.vendor_symbols USING gin (raw_payload);

        CREATE TABLE symbol_master.ingestion_runs (
            id bigserial PRIMARY KEY,
            vendor_id smallint NOT NULL REFERENCES symbol_master.vendors(id),
            job_name text NOT NULL,
            status text NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            records_seen integer NOT NULL DEFAULT 0,
            records_inserted integer NOT NULL DEFAULT 0,
            records_updated integer NOT NULL DEFAULT 0,
            records_failed integer NOT NULL DEFAULT 0,
            error_message text,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ingestion_runs_status_check
                CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
            CONSTRAINT ingestion_runs_counts_check
                CHECK (
                    records_seen >= 0
                    AND records_inserted >= 0
                    AND records_updated >= 0
                    AND records_failed >= 0
                )
        );

        CREATE INDEX ingestion_runs_vendor_started_idx
            ON symbol_master.ingestion_runs (vendor_id, started_at DESC);
        CREATE INDEX ingestion_runs_status_idx ON symbol_master.ingestion_runs (status);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS symbol_master.ingestion_runs;
        DROP TABLE IF EXISTS symbol_master.vendor_symbols;
        DROP TABLE IF EXISTS symbol_master.etf_profiles;
        DROP TABLE IF EXISTS symbol_master.assets;
        DROP TABLE IF EXISTS symbol_master.exchanges;
        DROP TABLE IF EXISTS symbol_master.vendors;
        DROP SCHEMA IF EXISTS signals;
        DROP SCHEMA IF EXISTS market_data;
        DROP SCHEMA IF EXISTS symbol_master;
        """
    )
