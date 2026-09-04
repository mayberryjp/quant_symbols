from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool, text

config = context.config

VERSION_TABLE_SCHEMA = "symbols"

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://quant:quant_dev_password@localhost:5432/quant",
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=VERSION_TABLE_SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Ensure the version bookkeeping table and all project tables live under
        # the `symbols` schema, relocating any pre-existing alembic_version table.
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {VERSION_TABLE_SCHEMA}"))
        connection.execute(
            text(
                f"ALTER TABLE IF EXISTS public.alembic_version SET SCHEMA {VERSION_TABLE_SCHEMA}"
            )
        )
        # search_path is set before the commit so no transaction stays open; an
        # open auto-begun transaction here makes Alembic's begin_transaction a
        # no-op and the migration would be rolled back on connection close.
        connection.execute(text(f"SET search_path TO {VERSION_TABLE_SCHEMA}, public"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=VERSION_TABLE_SCHEMA,
        )

        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
