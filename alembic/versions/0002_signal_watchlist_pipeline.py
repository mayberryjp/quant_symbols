"""signal watchlist pipeline schema

Revision ID: 0002_signal_watchlist_pipeline
Revises: 0001_symbol_master_vendor_traceability
Create Date: 2026-06-09
"""

from alembic import op


revision = "0002_signal_watchlist_pipeline"
down_revision = "0001_symbol_master_vendor_traceability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS signals")

    op.execute(
        """
        CREATE TABLE signals.signal_sources (
            id bigserial PRIMARY KEY,
            name text NOT NULL,
            source_type text NOT NULL DEFAULT 'strategy',
            enabled boolean NOT NULL DEFAULT true,
            owner text,
            contact text,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT signal_sources_name_not_blank
                CHECK (length(trim(name)) > 0),
            CONSTRAINT signal_sources_source_type_not_blank
                CHECK (length(trim(source_type)) > 0),
            CONSTRAINT signal_sources_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT signal_sources_name_unique
                UNIQUE (name)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE signals.signal_events (
            id bigserial PRIMARY KEY,
            source_id bigint NOT NULL
                REFERENCES signals.signal_sources(id),
            external_event_id text NOT NULL,
            submitted_ticker text NOT NULL,
            market text NOT NULL DEFAULT 'stocks',
            locale text NOT NULL DEFAULT 'us',
            symbol_id bigint
                REFERENCES symbol_master.symbols(id),
            canonical_ticker text,
            signal_type text NOT NULL,
            direction text,
            score numeric(10, 6),
            confidence numeric(10, 6),
            horizon text,
            reason text NOT NULL,
            tags jsonb NOT NULL DEFAULT '[]'::jsonb,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            status text NOT NULL DEFAULT 'pending',
            rejection_reason text,
            received_at timestamptz NOT NULL DEFAULT now(),
            processing_started_at timestamptz,
            processed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT signal_events_external_event_id_not_blank
                CHECK (length(trim(external_event_id)) > 0),
            CONSTRAINT signal_events_submitted_ticker_not_blank
                CHECK (length(trim(submitted_ticker)) > 0),
            CONSTRAINT signal_events_market_not_blank
                CHECK (length(trim(market)) > 0),
            CONSTRAINT signal_events_locale_not_blank
                CHECK (length(trim(locale)) > 0),
            CONSTRAINT signal_events_signal_type_not_blank
                CHECK (length(trim(signal_type)) > 0),
            CONSTRAINT signal_events_reason_not_blank
                CHECK (length(trim(reason)) > 0),
            CONSTRAINT signal_events_direction_check
                CHECK (direction IS NULL OR direction IN ('long', 'short', 'neutral')),
            CONSTRAINT signal_events_score_check
                CHECK (score IS NULL OR (score >= 0 AND score <= 1)),
            CONSTRAINT signal_events_confidence_check
                CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            CONSTRAINT signal_events_tags_array_check
                CHECK (jsonb_typeof(tags) = 'array'),
            CONSTRAINT signal_events_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT signal_events_status_check
                CHECK (status IN ('pending', 'processing', 'accepted', 'rejected', 'unresolved', 'duplicate', 'failed')),
            CONSTRAINT signal_events_source_external_unique
                UNIQUE (source_id, external_event_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE signals.watchlist_entries (
            id bigserial PRIMARY KEY,
            symbol_id bigint
                REFERENCES symbol_master.symbols(id),
            canonical_ticker text,
            submitted_ticker text NOT NULL,
            market text NOT NULL DEFAULT 'stocks',
            locale text NOT NULL DEFAULT 'us',
            source_id bigint NOT NULL
                REFERENCES signals.signal_sources(id),
            signal_event_id bigint
                REFERENCES signals.signal_events(id),
            signal_type text NOT NULL DEFAULT 'watchlist_candidate',
            status text NOT NULL DEFAULT 'active',
            active boolean NOT NULL DEFAULT true,
            reason text NOT NULL,
            score numeric(10, 6),
            confidence numeric(10, 6),
            direction text,
            horizon text,
            tags jsonb NOT NULL DEFAULT '[]'::jsonb,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            latest_rejection_reason text,
            created_by text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            deactivated_at timestamptz,
            CONSTRAINT watchlist_entries_submitted_ticker_not_blank
                CHECK (length(trim(submitted_ticker)) > 0),
            CONSTRAINT watchlist_entries_market_not_blank
                CHECK (length(trim(market)) > 0),
            CONSTRAINT watchlist_entries_locale_not_blank
                CHECK (length(trim(locale)) > 0),
            CONSTRAINT watchlist_entries_signal_type_not_blank
                CHECK (length(trim(signal_type)) > 0),
            CONSTRAINT watchlist_entries_reason_not_blank
                CHECK (length(trim(reason)) > 0),
            CONSTRAINT watchlist_entries_status_check
                CHECK (status IN ('active', 'updated', 'expired', 'rejected', 'superseded', 'inactive')),
            CONSTRAINT watchlist_entries_direction_check
                CHECK (direction IS NULL OR direction IN ('long', 'short', 'neutral')),
            CONSTRAINT watchlist_entries_score_check
                CHECK (score IS NULL OR (score >= 0 AND score <= 1)),
            CONSTRAINT watchlist_entries_confidence_check
                CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            CONSTRAINT watchlist_entries_tags_array_check
                CHECK (jsonb_typeof(tags) = 'array'),
            CONSTRAINT watchlist_entries_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )

    op.execute(
        """
        CREATE TABLE signals.worker_heartbeats (
            worker_name text PRIMARY KEY,
            status text NOT NULL,
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            last_processed_signal_event_id bigint
                REFERENCES signals.signal_events(id),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT worker_heartbeats_worker_name_not_blank
                CHECK (length(trim(worker_name)) > 0),
            CONSTRAINT worker_heartbeats_status_not_blank
                CHECK (length(trim(status)) > 0),
            CONSTRAINT worker_heartbeats_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX watchlist_entries_active_symbol_source_type_unique_idx
            ON signals.watchlist_entries (symbol_id, source_id, signal_type)
            WHERE active AND symbol_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX watchlist_entries_active_ticker_source_type_unique_idx
            ON signals.watchlist_entries (source_id, lower(submitted_ticker), market, locale, signal_type)
            WHERE active AND symbol_id IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX signal_events_status_received_idx
            ON signals.signal_events (status, received_at, id)
        """
    )
    op.execute(
        """
        CREATE INDEX signal_events_ticker_lookup_idx
            ON signals.signal_events (lower(submitted_ticker), market, locale)
        """
    )
    op.execute(
        """
        CREATE INDEX watchlist_entries_lookup_idx
            ON signals.watchlist_entries (active, source_id, lower(submitted_ticker), market, locale)
        """
    )
    op.execute(
        """
        CREATE INDEX watchlist_entries_tags_gin_idx
            ON signals.watchlist_entries USING gin (tags)
        """
    )
    op.execute(
        """
        CREATE INDEX watchlist_entries_metadata_gin_idx
            ON signals.watchlist_entries USING gin (metadata)
        """
    )
    op.execute(
        """
        INSERT INTO signals.signal_sources (name, source_type)
        VALUES ('operator', 'manual')
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS signals.worker_heartbeats")
    op.execute("DROP TABLE IF EXISTS signals.watchlist_entries")
    op.execute("DROP TABLE IF EXISTS signals.signal_events")
    op.execute("DROP TABLE IF EXISTS signals.signal_sources")
