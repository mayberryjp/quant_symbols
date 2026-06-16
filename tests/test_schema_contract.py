from pathlib import Path

from quant_symbols.cli import (
    EXPECTED_SCHEMA_VERSION,
    EXPECTED_SIGNAL_TABLES,
    EXPECTED_TABLES,
    build_parser,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_MIGRATION = REPO_ROOT / "alembic" / "versions" / "0001_symbol_master_vendor_traceability.py"
SIGNAL_MIGRATION = REPO_ROOT / "alembic" / "versions" / "0002_signal_watchlist_pipeline.py"


def test_cli_exposes_required_db_commands():
    parser = build_parser()

    assert parser.parse_args(["db", "upgrade"]).func.__name__ == "db_upgrade"
    assert parser.parse_args(["db", "verify"]).func.__name__ == "db_verify"
    assert (
        parser.parse_args(["db", "downgrade-base"]).func.__name__
        == "db_downgrade_base"
    )
    assert parser.parse_args(["signals", "worker", "--once"]).func.__name__ == "signal_worker"


def test_migration_declares_expected_revision_and_tables():
    base_migration_text = BASE_MIGRATION.read_text()
    signal_migration_text = SIGNAL_MIGRATION.read_text()

    assert f'revision = "{EXPECTED_SCHEMA_VERSION}"' in signal_migration_text
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE symbol_master.{table}" in base_migration_text
    for table in EXPECTED_SIGNAL_TABLES:
        assert f"CREATE TABLE signals.{table}" in signal_migration_text


def test_migration_keeps_vendor_payloads_jsonb_and_trace_links():
    migration_text = BASE_MIGRATION.read_text()

    assert "payload jsonb NOT NULL" in migration_text
    assert "vendor_api_run_id bigint NOT NULL" in migration_text
    assert "first_seen_payload_id bigint" in migration_text
    assert "last_seen_payload_id bigint" in migration_text
    assert "raw_vendor_payloads_run_linkage_idx" in migration_text


def test_signal_migration_keeps_idempotency_and_normalized_identity_central():
    migration_text = SIGNAL_MIGRATION.read_text()

    assert "UNIQUE (source_id, external_event_id)" in migration_text
    assert "symbol_id bigint" in migration_text
    assert "submitted_ticker text NOT NULL" in migration_text
    assert "watchlist_entries_active_symbol_source_type_unique_idx" in migration_text
    assert "worker_heartbeats" in migration_text
