from pathlib import Path

from quant_symbols.cli import EXPECTED_SCHEMA_VERSION, EXPECTED_TABLES, build_parser


REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION = REPO_ROOT / "alembic" / "versions" / "0001_symbol_master_vendor_traceability.py"


def test_cli_exposes_required_db_commands():
    parser = build_parser()

    assert parser.parse_args(["db", "upgrade"]).func.__name__ == "db_upgrade"
    assert parser.parse_args(["db", "verify"]).func.__name__ == "db_verify"
    assert (
        parser.parse_args(["db", "downgrade-base"]).func.__name__
        == "db_downgrade_base"
    )


def test_migration_declares_expected_revision_and_tables():
    migration_text = MIGRATION.read_text()

    assert f'revision = "{EXPECTED_SCHEMA_VERSION}"' in migration_text
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE symbol_master.{table}" in migration_text


def test_migration_keeps_vendor_payloads_jsonb_and_trace_links():
    migration_text = MIGRATION.read_text()

    assert "payload jsonb NOT NULL" in migration_text
    assert "vendor_api_run_id bigint NOT NULL" in migration_text
    assert "first_seen_payload_id bigint" in migration_text
    assert "last_seen_payload_id bigint" in migration_text
    assert "raw_vendor_payloads_run_linkage_idx" in migration_text
