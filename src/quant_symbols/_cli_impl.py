from __future__ import annotations

import argparse
import os
from pathlib import Path


EXPECTED_SCHEMA_VERSION = "0002_symbol_quality_reporting"
EXPECTED_TABLES = (
    "vendor_sources",
    "vendor_api_runs",
    "raw_vendor_payloads",
    "exchanges",
    "symbols",
    "symbol_vendor_ids",
    "symbol_aliases",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://quant:quant_dev_password@localhost:5432/quant",
    )


def _alembic_config() -> object:
    from alembic.config import Config

    config = Config(str(_repo_root() / "alembic.ini"))
    config.set_main_option("script_location", str(_repo_root() / "alembic"))
    return config


def db_upgrade(_args: argparse.Namespace) -> None:
    from alembic import command

    command.upgrade(_alembic_config(), "head")


def db_downgrade_base(_args: argparse.Namespace) -> None:
    from alembic import command

    command.downgrade(_alembic_config(), "base")


def db_verify(_args: argparse.Namespace) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(_database_url(), pool_pre_ping=True)
    expected_table_names = tuple(sorted(EXPECTED_TABLES))

    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()
        schema_version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        tables = connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'symbol_master'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
        ).scalars().all()
        vendor_sources = connection.execute(
            text("SELECT count(*) FROM symbol_master.vendor_sources")
        ).scalar_one()
        exchanges = connection.execute(
            text("SELECT count(*) FROM symbol_master.exchanges")
        ).scalar_one()
        quality_columns = connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'symbol_master'
                  AND table_name = 'vendor_api_runs'
                  AND column_name IN ('sync_summary', 'quality_findings')
                ORDER BY column_name
                """
            )
        ).scalars().all()

    if schema_version != EXPECTED_SCHEMA_VERSION:
        raise SystemExit(
            f"schema_version={schema_version} expected={EXPECTED_SCHEMA_VERSION}"
        )
    if tuple(tables) != expected_table_names:
        raise SystemExit(f"tables={','.join(tables)} expected={','.join(expected_table_names)}")
    if tuple(quality_columns) != ("quality_findings", "sync_summary"):
        raise SystemExit("vendor_api_runs missing Day 5 quality reporting columns")

    print(
        "postgres=ok "
        f"schema_version={schema_version} "
        f"tables={len(tables)} "
        f"vendor_sources={vendor_sources} "
        f"exchanges={exchanges}"
    )


def _engine() -> object:
    try:
        from sqlalchemy import create_engine
    except ModuleNotFoundError as exc:
        raise SystemExit("SQLAlchemy is required for database-backed symbol commands") from exc

    return create_engine(_database_url(), pool_pre_ping=True)


def _parse_active(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized == "all":
        return None
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("--active must be true, false, or all")


def symbols_sync(args: argparse.Namespace) -> None:
    from quant_symbols.symbol_master.massive_sync import MassiveSymbolSyncJob, SyncOptions

    options = SyncOptions(
        fixture=Path(args.fixture) if args.fixture else None,
        dry_run=args.dry_run,
        max_pages=args.max_pages,
        active=args.active,
        market=args.market,
        locale=args.locale,
        limit=args.limit,
    )
    engine = None if args.dry_run else _engine()
    job = MassiveSymbolSyncJob(engine=engine)
    try:
        summary = job.run(options)
    except Exception as exc:
        from quant_symbols.symbol_master.summary import SyncSummary

        summary = SyncSummary(
            mode="fixture" if args.fixture else "live",
            status="failed",
            errors=1,
            error_message=str(exc),
        )
        print(summary.format_line())
        raise SystemExit(1) from exc
    print(summary.format_line())
    if summary.status == "failed":
        raise SystemExit(1)


def symbols_sync_summary(args: argparse.Namespace) -> None:
    from quant_symbols.symbol_master.massive_sync import MassiveSymbolSyncJob

    if not args.latest:
        raise SystemExit("only --latest is currently supported")
    row = MassiveSymbolSyncJob(engine=_engine()).latest_summary()
    if row is None:
        print("symbols_sync_summary=empty")
        return
    health = MassiveSymbolSyncJob(engine=_engine()).latest_health()
    counts = health["counts"] if health is not None else {}
    print(
        "symbols_sync_summary=ok "
        f"run_id={row['id']} "
        f"vendor={row['vendor']} "
        f"endpoint={row['endpoint']} "
        f"status={row['status']} "
        f"records_seen={row['records_seen']} "
        f"raw_payloads={row['records_inserted']} "
        f"inserted={counts.get('inserted', 0)} "
        f"updated={counts.get('updated', 0)} "
        f"unchanged={counts.get('unchanged', 0)} "
        f"deactivated={counts.get('deactivated', 0)} "
        f"reactivated={counts.get('reactivated', 0)} "
        f"skipped={counts.get('skipped', 0)} "
        f"warned={counts.get('warned', 0)} "
        f"errored={counts.get('errored', row['records_failed'])}"
    )


def symbols_quality(args: argparse.Namespace) -> None:
    from quant_symbols.symbol_master.massive_sync import MassiveSymbolSyncJob

    if not args.latest:
        raise SystemExit("only --latest is currently supported")
    health = MassiveSymbolSyncJob(engine=_engine()).latest_health()
    if health is None:
        print("symbols_quality=empty")
        return
    warning_categories = ",".join(
        f"{category}:{count}"
        for category, count in sorted(health["warnings"]["categories"].items())
    )
    error_categories = ",".join(
        f"{category}:{count}" for category, count in sorted(health["errors"]["categories"].items())
    )
    print(
        "symbols_quality=ok "
        f"run_id={health['run_id']} "
        f"status={health['status']} "
        f"warnings={health['warnings']['total']} "
        f"errors={health['errors']['total']} "
        f"deactivated={health['active_inactive_diffs']['deactivated_count']} "
        f"reactivated={health['active_inactive_diffs']['reactivated_count']} "
        f"warning_categories={warning_categories or 'none'} "
        f"error_categories={error_categories or 'none'}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m quant_symbols.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    db_parser = subparsers.add_parser("db")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)

    upgrade_parser = db_subparsers.add_parser("upgrade")
    upgrade_parser.set_defaults(func=db_upgrade)

    verify_parser = db_subparsers.add_parser("verify")
    verify_parser.set_defaults(func=db_verify)

    downgrade_parser = db_subparsers.add_parser("downgrade-base")
    downgrade_parser.set_defaults(func=db_downgrade_base)

    symbols_parser = subparsers.add_parser("symbols")
    symbols_subparsers = symbols_parser.add_subparsers(dest="symbols_command", required=True)

    sync_parser = symbols_subparsers.add_parser("sync")
    sync_parser.add_argument("--fixture", help="Path to Massive fixture file or directory")
    sync_parser.add_argument("--dry-run", action="store_true", help="Map records without database writes")
    sync_parser.add_argument("--max-pages", type=int)
    sync_parser.add_argument("--active", type=_parse_active, default=None, choices=(True, False, None))
    sync_parser.add_argument("--market", default="stocks")
    sync_parser.add_argument("--locale", default="us")
    sync_parser.add_argument("--limit", type=int, default=1000)
    sync_parser.set_defaults(func=symbols_sync)

    summary_parser = symbols_subparsers.add_parser("sync-summary")
    summary_parser.add_argument("--latest", action="store_true", required=True)
    summary_parser.set_defaults(func=symbols_sync_summary)

    quality_parser = symbols_subparsers.add_parser("quality")
    quality_parser.add_argument("--latest", action="store_true", required=True)
    quality_parser.set_defaults(func=symbols_quality)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0
