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

    op.execute("DROP SCHEMA IF EXISTS symbol_master")
    op.execute("DROP SCHEMA IF EXISTS market_data")
    op.execute("DROP SCHEMA IF EXISTS signals")


def downgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS symbol_master")
    op.execute("CREATE SCHEMA IF NOT EXISTS market_data")
    op.execute("CREATE SCHEMA IF NOT EXISTS signals")

    for table in _TABLES:
        op.execute(f"ALTER TABLE IF EXISTS symbols.{table} SET SCHEMA symbol_master")
