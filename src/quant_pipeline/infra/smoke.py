from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text

EXPECTED_ALEMBIC_HEAD = "0001_baseline_symbol_master"
EXPECTED_TABLES = {
    "assets",
    "etf_profiles",
    "exchanges",
    "ingestion_runs",
    "vendor_symbols",
    "vendors",
}


def _load_dotenv() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _database_url() -> str:
    _load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for smoke validation")
    return database_url


def main() -> None:
    engine = create_engine(_database_url())

    with engine.connect() as connection:
        database_name = connection.execute(text("SELECT current_database()")).scalar_one()
        user_name = connection.execute(text("SELECT current_user")).scalar_one()
        alembic_head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        table_names = set(
            connection.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'symbol_master'
                      AND table_type = 'BASE TABLE'
                    """
                )
            ).scalars()
        )

    missing_tables = EXPECTED_TABLES - table_names
    if alembic_head != EXPECTED_ALEMBIC_HEAD:
        raise RuntimeError(f"expected alembic head {EXPECTED_ALEMBIC_HEAD}, found {alembic_head}")
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise RuntimeError(f"missing symbol_master tables: {missing}")

    print(
        "postgres=ok "
        f"database={database_name} "
        f"user={user_name} "
        f"alembic_head={alembic_head} "
        f"tables={len(EXPECTED_TABLES)}"
    )


if __name__ == "__main__":
    main()
