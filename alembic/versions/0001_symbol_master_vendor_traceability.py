"""symbol master and vendor traceability schema v1

Revision ID: 0001_symbol_master_vendor_traceability
Revises:
Create Date: 2026-06-03
"""

from alembic import op


revision = "0001_symbol_master_vendor_traceability"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(128)")

    op.execute("CREATE SCHEMA IF NOT EXISTS symbol_master")
    op.execute("CREATE SCHEMA IF NOT EXISTS market_data")
    op.execute("CREATE SCHEMA IF NOT EXISTS signals")

    op.execute(
        """
        CREATE TABLE symbol_master.vendor_sources (
            id smallserial PRIMARY KEY,
            code text NOT NULL,
            name text NOT NULL,
            base_url text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT vendor_sources_code_not_blank
                CHECK (length(trim(code)) > 0),
            CONSTRAINT vendor_sources_name_not_blank
                CHECK (length(trim(name)) > 0),
            CONSTRAINT vendor_sources_code_unique
                UNIQUE (code)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE symbol_master.vendor_api_runs (
            id bigserial PRIMARY KEY,
            vendor_source_id smallint NOT NULL
                REFERENCES symbol_master.vendor_sources(id),
            endpoint text NOT NULL,
            request_params jsonb NOT NULL DEFAULT '{}'::jsonb,
            status text NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            records_seen integer NOT NULL DEFAULT 0,
            records_inserted integer NOT NULL DEFAULT 0,
            records_failed integer NOT NULL DEFAULT 0,
            error_message text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT vendor_api_runs_endpoint_not_blank
                CHECK (length(trim(endpoint)) > 0),
            CONSTRAINT vendor_api_runs_status_check
                CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
            CONSTRAINT vendor_api_runs_counts_check
                CHECK (
                    records_seen >= 0
                    AND records_inserted >= 0
                    AND records_failed >= 0
                ),
            CONSTRAINT vendor_api_runs_finished_after_started_check
                CHECK (finished_at IS NULL OR finished_at >= started_at),
            CONSTRAINT vendor_api_runs_id_source_unique
                UNIQUE (id, vendor_source_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE symbol_master.raw_vendor_payloads (
            id bigserial PRIMARY KEY,
            vendor_source_id smallint NOT NULL
                REFERENCES symbol_master.vendor_sources(id),
            vendor_api_run_id bigint NOT NULL
                REFERENCES symbol_master.vendor_api_runs(id) ON DELETE RESTRICT,
            provider_record_id text,
            provider_ticker text,
            payload jsonb NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT raw_vendor_payloads_payload_object_check
                CHECK (jsonb_typeof(payload) = 'object'),
            CONSTRAINT raw_vendor_payloads_provider_ticker_not_blank
                CHECK (provider_ticker IS NULL OR length(trim(provider_ticker)) > 0),
            CONSTRAINT raw_vendor_payloads_run_source_fk
                FOREIGN KEY (vendor_api_run_id, vendor_source_id)
                REFERENCES symbol_master.vendor_api_runs(id, vendor_source_id)
                ON DELETE RESTRICT
        )
        """
    )

    op.execute(
        """
        CREATE TABLE symbol_master.exchanges (
            id bigserial PRIMARY KEY,
            mic text NOT NULL,
            name text NOT NULL,
            country_code char(2) NOT NULL DEFAULT 'US',
            timezone text NOT NULL DEFAULT 'America/New_York',
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT exchanges_mic_not_blank
                CHECK (length(trim(mic)) > 0),
            CONSTRAINT exchanges_name_not_blank
                CHECK (length(trim(name)) > 0),
            CONSTRAINT exchanges_mic_unique
                UNIQUE (mic)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE symbol_master.symbols (
            id bigserial PRIMARY KEY,
            canonical_ticker text NOT NULL,
            name text,
            market text NOT NULL,
            locale text NOT NULL,
            currency char(3) NOT NULL DEFAULT 'USD',
            primary_exchange_id bigint
                REFERENCES symbol_master.exchanges(id),
            asset_class text NOT NULL,
            security_type text NOT NULL DEFAULT 'unknown',
            active boolean NOT NULL DEFAULT true,
            cik text,
            composite_figi text,
            share_class_figi text,
            first_seen_run_id bigint
                REFERENCES symbol_master.vendor_api_runs(id),
            first_seen_payload_id bigint
                REFERENCES symbol_master.raw_vendor_payloads(id),
            last_seen_run_id bigint
                REFERENCES symbol_master.vendor_api_runs(id),
            last_seen_payload_id bigint
                REFERENCES symbol_master.raw_vendor_payloads(id),
            delisted_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT symbols_canonical_ticker_not_blank
                CHECK (length(trim(canonical_ticker)) > 0),
            CONSTRAINT symbols_market_not_blank
                CHECK (length(trim(market)) > 0),
            CONSTRAINT symbols_locale_not_blank
                CHECK (length(trim(locale)) > 0),
            CONSTRAINT symbols_asset_class_check
                CHECK (asset_class IN ('equity', 'fund', 'crypto', 'forex', 'index', 'other')),
            CONSTRAINT symbols_security_type_not_blank
                CHECK (length(trim(security_type)) > 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE symbol_master.symbol_vendor_ids (
            id bigserial PRIMARY KEY,
            symbol_id bigint NOT NULL
                REFERENCES symbol_master.symbols(id) ON DELETE CASCADE,
            vendor_source_id smallint NOT NULL
                REFERENCES symbol_master.vendor_sources(id),
            vendor_symbol text NOT NULL,
            vendor_asset_id text,
            first_seen_run_id bigint
                REFERENCES symbol_master.vendor_api_runs(id),
            first_seen_payload_id bigint
                REFERENCES symbol_master.raw_vendor_payloads(id),
            last_seen_run_id bigint
                REFERENCES symbol_master.vendor_api_runs(id),
            last_seen_payload_id bigint
                REFERENCES symbol_master.raw_vendor_payloads(id),
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT symbol_vendor_ids_vendor_symbol_not_blank
                CHECK (length(trim(vendor_symbol)) > 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE symbol_master.symbol_aliases (
            id bigserial PRIMARY KEY,
            symbol_id bigint NOT NULL
                REFERENCES symbol_master.symbols(id) ON DELETE CASCADE,
            alias_type text NOT NULL,
            alias_value text NOT NULL,
            source_vendor_id smallint
                REFERENCES symbol_master.vendor_sources(id),
            source_payload_id bigint
                REFERENCES symbol_master.raw_vendor_payloads(id),
            active boolean NOT NULL DEFAULT true,
            valid_from date,
            valid_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT symbol_aliases_alias_type_not_blank
                CHECK (length(trim(alias_type)) > 0),
            CONSTRAINT symbol_aliases_alias_value_not_blank
                CHECK (length(trim(alias_value)) > 0),
            CONSTRAINT symbol_aliases_valid_window_check
                CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
        )
        """
    )

    op.execute(
        """
        INSERT INTO symbol_master.vendor_sources (code, name, base_url)
        VALUES ('massive', 'Massive / Polygon', 'https://api.polygon.io')
        ON CONFLICT (code) DO UPDATE
            SET name = EXCLUDED.name,
                base_url = EXCLUDED.base_url,
                updated_at = now()
        """
    )

    op.execute(
        """
        INSERT INTO symbol_master.exchanges (mic, name)
        VALUES
            ('XNYS', 'New York Stock Exchange'),
            ('XNAS', 'Nasdaq Stock Market'),
            ('ARCX', 'NYSE Arca'),
            ('BATS', 'Cboe BZX Exchange'),
            ('OTCM', 'OTC Markets')
        ON CONFLICT (mic) DO UPDATE
            SET name = EXCLUDED.name,
                updated_at = now()
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX symbols_active_canonical_ticker_unique_idx
            ON symbol_master.symbols (locale, market, canonical_ticker)
            WHERE active
        """
    )
    op.execute(
        """
        CREATE INDEX symbols_canonical_ticker_lookup_idx
            ON symbol_master.symbols (locale, market, lower(canonical_ticker))
        """
    )
    op.execute(
        """
        CREATE INDEX symbols_active_lookup_idx
            ON symbol_master.symbols (active, locale, market)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX symbols_composite_figi_unique_idx
            ON symbol_master.symbols (composite_figi)
            WHERE composite_figi IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX symbols_primary_exchange_idx
            ON symbol_master.symbols (primary_exchange_id)
        """
    )

    op.execute(
        """
        CREATE INDEX vendor_api_runs_vendor_started_idx
            ON symbol_master.vendor_api_runs (vendor_source_id, started_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX vendor_api_runs_status_idx
            ON symbol_master.vendor_api_runs (status)
        """
    )

    op.execute(
        """
        CREATE INDEX raw_vendor_payloads_run_linkage_idx
            ON symbol_master.raw_vendor_payloads (vendor_api_run_id, id)
        """
    )
    op.execute(
        """
        CREATE INDEX raw_vendor_payloads_vendor_ticker_lookup_idx
            ON symbol_master.raw_vendor_payloads (vendor_source_id, lower(provider_ticker))
            WHERE provider_ticker IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX raw_vendor_payloads_payload_gin_idx
            ON symbol_master.raw_vendor_payloads USING gin (payload)
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX symbol_vendor_ids_active_vendor_symbol_unique_idx
            ON symbol_master.symbol_vendor_ids (vendor_source_id, lower(vendor_symbol))
            WHERE active
        """
    )
    op.execute(
        """
        CREATE INDEX symbol_vendor_ids_vendor_symbol_lookup_idx
            ON symbol_master.symbol_vendor_ids (vendor_source_id, lower(vendor_symbol))
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX symbol_vendor_ids_vendor_asset_unique_idx
            ON symbol_master.symbol_vendor_ids (vendor_source_id, vendor_asset_id)
            WHERE vendor_asset_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX symbol_vendor_ids_symbol_idx
            ON symbol_master.symbol_vendor_ids (symbol_id)
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX symbol_aliases_value_unique_idx
            ON symbol_master.symbol_aliases (alias_type, lower(alias_value))
            WHERE active
        """
    )
    op.execute(
        """
        CREATE INDEX symbol_aliases_symbol_idx
            ON symbol_master.symbol_aliases (symbol_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS symbol_master.symbol_aliases")
    op.execute("DROP TABLE IF EXISTS symbol_master.symbol_vendor_ids")
    op.execute("DROP TABLE IF EXISTS symbol_master.symbols")
    op.execute("DROP TABLE IF EXISTS symbol_master.exchanges")
    op.execute("DROP TABLE IF EXISTS symbol_master.raw_vendor_payloads")
    op.execute("DROP TABLE IF EXISTS symbol_master.vendor_api_runs")
    op.execute("DROP TABLE IF EXISTS symbol_master.vendor_sources")
    op.execute("DROP SCHEMA IF EXISTS signals")
    op.execute("DROP SCHEMA IF EXISTS market_data")
    op.execute("DROP SCHEMA IF EXISTS symbol_master")
