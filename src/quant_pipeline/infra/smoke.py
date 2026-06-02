from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

EXPECTED_REVISION = "0001_baseline_symbol_master"
EXPECTED_TABLES = (
    "assets",
    "etf_profiles",
    "exchanges",
    "ingestion_runs",
    "vendor_symbols",
    "vendors",
)


def _database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    return database_url


def _verify_database() -> str:
    engine = create_engine(_database_url(), pool_pre_ping=True)

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT current_database() AS database_name, current_user AS user_name")
        ).one()

        alembic_revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
        if alembic_revision != EXPECTED_REVISION:
            raise RuntimeError(
                f"expected alembic revision {EXPECTED_REVISION}, found {alembic_revision!r}"
            )

        table_rows = connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'symbol_master'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
        ).scalars()
        tables = tuple(table_rows)
        if tables != EXPECTED_TABLES:
            raise RuntimeError(f"expected tables {EXPECTED_TABLES!r}, found {tables!r}")

    return (
        f"postgres=ok database={row.database_name} user={row.user_name} "
        f"alembic_head={alembic_revision} tables={len(tables)}"
    )


def main() -> int:
    try:
        print(_verify_database())
    except (RuntimeError, SQLAlchemyError) as exc:
        print(f"postgres=error detail={exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
