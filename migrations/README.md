# Alembic Migrations

Alembic reads the database connection from `DATABASE_URL`.

The baseline migration creates the PostgreSQL schemas used by the Day 1 symbol
master foundation and mirrors `infra/postgres/schema/0001_baseline_symbol_master.sql`.
