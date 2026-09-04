"""consolidate all project tables under the symbols schema

Revision ID: 0003_consolidate_symbols_schema
Revises: 0002_vendor_run_symbol_counts
Create Date: 2026-09-04
"""

from alembic import op


revision = "0003_consolidate_symbols_schema"
down_revision = "0002_vendor_run_symbol_counts"
branch_labels = None
depends_on = None


_TABLES = (
    "vendor_sources",
    "vendor_api_runs",
    "raw_vendor_payloads",
    "exchanges",
    "symbols",
    "symbol_vendor_ids",
    "symbol_aliases",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS symbols")

    for table in _TABLES:
        op.execute(f"ALTER TABLE IF EXISTS symbol_master.{table} SET SCHEMA symbols")

    # Sweep any relation left behind by earlier schema iterations so symbol_master
    # ends empty and drops without CASCADE. Serial-owned sequences and indexes
    # follow their table automatically on SET SCHEMA.
    op.execute(
        """
        DO $$
        DECLARE
            obj record;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'symbol_master'
            ) THEN
                FOR obj IN
                    SELECT c.relname, c.relkind
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'symbol_master'
                      AND c.relkind IN ('r', 'p', 'v', 'm')
                      AND NOT EXISTS (
                          SELECT 1
                          FROM pg_class existing
                          JOIN pg_namespace en ON en.oid = existing.relnamespace
                          WHERE en.nspname = 'symbols'
                            AND existing.relname = c.relname
                      )
                LOOP
                    IF obj.relkind = 'v' THEN
                        EXECUTE format('ALTER VIEW symbol_master.%I SET SCHEMA symbols', obj.relname);
                    ELSIF obj.relkind = 'm' THEN
                        EXECUTE format('ALTER MATERIALIZED VIEW symbol_master.%I SET SCHEMA symbols', obj.relname);
                    ELSE
                        EXECUTE format('ALTER TABLE symbol_master.%I SET SCHEMA symbols', obj.relname);
                    END IF;
                END LOOP;
            END IF;
        END $$;
        """
    )

    # Only symbol_master is retired here. market_data and signals are sibling
    # schemas with their own tables and migration lineage, so this migration must
    # never drop them.
    op.execute("DROP SCHEMA IF EXISTS symbol_master")


def downgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS symbol_master")

    for table in _TABLES:
        op.execute(f"ALTER TABLE IF EXISTS symbols.{table} SET SCHEMA symbol_master")
