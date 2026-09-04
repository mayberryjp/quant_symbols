from pathlib import Path

from quant_symbols.cli import EXPECTED_SCHEMA_VERSION, EXPECTED_TABLES, build_parser


REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_MIGRATION = REPO_ROOT / "alembic" / "versions" / "0001_symbol_master_vendor_traceability.py"
COUNTERS_MIGRATION = REPO_ROOT / "alembic" / "versions" / "0002_vendor_run_symbol_counts.py"
HEAD_MIGRATION = REPO_ROOT / "alembic" / "versions" / "0003_consolidate_symbols_schema.py"


def test_cli_exposes_required_db_commands():
    parser = build_parser()

    assert parser.parse_args(["db", "upgrade"]).func.__name__ == "db_upgrade"
    assert parser.parse_args(["db", "verify"]).func.__name__ == "db_verify"
    assert (
        parser.parse_args(["db", "downgrade-base"]).func.__name__
        == "db_downgrade_base"
    )


def test_migration_declares_expected_revision_and_tables():
    baseline_text = BASELINE_MIGRATION.read_text()
    head_text = HEAD_MIGRATION.read_text()

    assert f'revision = "{EXPECTED_SCHEMA_VERSION}"' in head_text
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE symbol_master.{table}" in baseline_text


def test_head_migration_consolidates_into_symbols_schema():
    head_text = HEAD_MIGRATION.read_text()

    assert 'down_revision = "0002_vendor_run_symbol_counts"' in head_text
    assert "CREATE SCHEMA IF NOT EXISTS symbols" in head_text
    assert "symbol_master.{table} SET SCHEMA symbols" in head_text
    assert "DROP SCHEMA IF EXISTS symbol_master" in head_text


def test_counters_migration_adds_run_symbol_counters():
    counters_text = COUNTERS_MIGRATION.read_text()

    assert 'down_revision = "0001_symbol_master_vendor_traceability"' in counters_text
    assert "ADD COLUMN symbols_new integer NOT NULL DEFAULT 0" in counters_text
    assert "ADD COLUMN symbols_delisted integer NOT NULL DEFAULT 0" in counters_text


def test_migration_keeps_vendor_payloads_jsonb_and_trace_links():
    migration_text = BASELINE_MIGRATION.read_text()

    assert "payload jsonb NOT NULL" in migration_text
    assert "vendor_api_run_id bigint NOT NULL" in migration_text
    assert "first_seen_payload_id bigint" in migration_text
    assert "last_seen_payload_id bigint" in migration_text
    assert "raw_vendor_payloads_run_linkage_idx" in migration_text
