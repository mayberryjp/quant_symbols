"""symbol quality reporting

Revision ID: 0002_symbol_quality_reporting
Revises: 0001_symbol_master_vendor_traceability
Create Date: 2026-06-05
"""

from alembic import op


revision = "0002_symbol_quality_reporting"
down_revision = "0001_symbol_master_vendor_traceability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE symbol_master.vendor_api_runs
            ADD COLUMN sync_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN quality_findings jsonb NOT NULL DEFAULT '[]'::jsonb
        """
    )
    op.execute(
        """
        ALTER TABLE symbol_master.vendor_api_runs
            ADD CONSTRAINT vendor_api_runs_sync_summary_object_check
                CHECK (jsonb_typeof(sync_summary) = 'object'),
            ADD CONSTRAINT vendor_api_runs_quality_findings_array_check
                CHECK (jsonb_typeof(quality_findings) = 'array')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE symbol_master.vendor_api_runs
            DROP CONSTRAINT IF EXISTS vendor_api_runs_quality_findings_array_check,
            DROP CONSTRAINT IF EXISTS vendor_api_runs_sync_summary_object_check,
            DROP COLUMN IF EXISTS quality_findings,
            DROP COLUMN IF EXISTS sync_summary
        """
    )
