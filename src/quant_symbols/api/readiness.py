from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from quant_symbols._cli_impl import (
    EXPECTED_SCHEMA_VERSION,
    EXPECTED_SIGNAL_TABLES,
    EXPECTED_TABLES,
)


class ReadinessError(RuntimeError):
    """Raised when the API process is live but not ready for database reads."""


@dataclass(frozen=True)
class ReadinessStatus:
    database: str
    schema_version: str
    tables: int
    signal_tables: int = 0

    def as_json(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "database": self.database,
            "schema_version": self.schema_version,
            "tables": self.tables,
            "signal_tables": self.signal_tables,
        }


def _database_url_from_env() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise ReadinessError("DATABASE_URL is not configured")
    return value


def _redact_database_url(database_url: str) -> str:
    try:
        parts = urlsplit(database_url)
    except ValueError:
        return "<redacted database url>"

    if not parts.netloc:
        return "<redacted database url>"

    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port is not None else ""
    username = parts.username or ""
    userinfo = f"{username}:***@" if username else ""
    return urlunsplit((parts.scheme, f"{userinfo}{host}{port}", parts.path, "", ""))


def sanitize_readiness_error(error: BaseException, database_url: str | None = None) -> str:
    message = str(error) or error.__class__.__name__
    if database_url:
        message = message.replace(database_url, _redact_database_url(database_url))
    return message


def check_database_readiness(database_url: str | None = None) -> ReadinessStatus:
    from sqlalchemy import create_engine, text

    resolved_url = database_url or _database_url_from_env()
    expected_table_names = tuple(sorted(EXPECTED_TABLES))
    engine = create_engine(resolved_url, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
            schema_version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            symbol_tables = tuple(
                connection.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'symbol_master'
                          AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                        """
                    )
                )
                .scalars()
                .all()
            )
            signal_tables = tuple(
                connection.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'signals'
                          AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                        """
                    )
                )
                .scalars()
                .all()
            )
    finally:
        engine.dispose()

    if schema_version != EXPECTED_SCHEMA_VERSION:
        raise ReadinessError(
            f"schema_version={schema_version} expected={EXPECTED_SCHEMA_VERSION}"
        )
    if symbol_tables != expected_table_names:
        raise ReadinessError(
            f"symbol_tables={','.join(symbol_tables)} expected={','.join(expected_table_names)}"
        )
    expected_signal_table_names = tuple(sorted(EXPECTED_SIGNAL_TABLES))
    if signal_tables != expected_signal_table_names:
        raise ReadinessError(
            f"signal_tables={','.join(signal_tables)} expected={','.join(expected_signal_table_names)}"
        )

    return ReadinessStatus(
        database="ok",
        schema_version=schema_version,
        tables=len(symbol_tables),
        signal_tables=len(signal_tables),
    )
