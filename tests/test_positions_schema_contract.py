from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION = REPO_ROOT / "alembic" / "versions" / "0002_positions_orders.py"


def test_positions_order_migration_declares_trading_tables():
    migration_text = MIGRATION.read_text()

    assert 'revision = "0002_positions_orders"' in migration_text
    assert 'down_revision = "0001_symbol_master_vendor_traceability"' in migration_text
    for table in (
        "portfolios",
        "positions",
        "order_intents",
        "order_events",
        "order_fills",
        "position_ledger_entries",
        "worker_heartbeats",
    ):
        assert f"CREATE TABLE trading.{table}" in migration_text


def test_positions_order_migration_keeps_required_uniqueness_and_append_only_rules():
    migration_text = MIGRATION.read_text()

    assert "order_intents_portfolio_idempotency_unique" in migration_text
    assert "positions_portfolio_symbol_unique_idx" in migration_text
    assert "positions_portfolio_unresolved_ticker_unique_idx" in migration_text
    assert "order_fills_external_unique_idx" in migration_text
    assert "position_ledger_entries_append_only" in migration_text
    assert "position_ledger_entries is append-only" in migration_text
