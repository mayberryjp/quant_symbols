"""vendor api run new/delisted symbol counters

Revision ID: 0002_vendor_run_symbol_counts
Revises: 0001_symbol_master_vendor_traceability
Create Date: 2026-07-07
"""

from alembic import op


revision = "0002_vendor_run_symbol_counts"
down_revision = "0001_symbol_master_vendor_traceability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE symbol_master.vendor_api_runs
            ADD COLUMN symbols_new integer NOT NULL DEFAULT 0,
            ADD COLUMN symbols_delisted integer NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE symbol_master.vendor_api_runs
            ADD CONSTRAINT vendor_api_runs_symbols_new_nonneg
                CHECK (symbols_new >= 0),
            ADD CONSTRAINT vendor_api_runs_symbols_delisted_nonneg
                CHECK (symbols_delisted >= 0)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE symbol_master.vendor_api_runs
            DROP CONSTRAINT IF EXISTS vendor_api_runs_symbols_new_nonneg,
            DROP CONSTRAINT IF EXISTS vendor_api_runs_symbols_delisted_nonneg
        """
    )
    op.execute(
        """
        ALTER TABLE symbol_master.vendor_api_runs
            DROP COLUMN IF EXISTS symbols_new,
            DROP COLUMN IF EXISTS symbols_delisted
        """
    )
