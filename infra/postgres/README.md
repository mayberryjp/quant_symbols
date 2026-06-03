# Postgres Infrastructure

This folder owns database infrastructure design artifacts.

The executable schema is owned by Alembic at the repository root. The current
database revision is `0001_symbol_master_vendor_traceability`.

## Migration Contract

The Day 2 Alembic migration:

- create schemas `symbol_master`, `market_data`, and `signals`
- create seven `symbol_master` tables for vendor traceability and normalized symbols
- store complete raw vendor records in `symbol_master.raw_vendor_payloads.payload`
- link raw payloads to `symbol_master.vendor_api_runs`
- seed the `massive` vendor source
- seed common U.S. exchange rows
- add lookup indexes for canonical tickers, vendor tickers, and raw payload run linkage

## Local Commands

Start Postgres:

```bash
docker compose up -d postgres
```

Check health:

```bash
docker compose ps postgres
```

Apply migrations:

```bash
alembic upgrade head
```

Run the Python smoke check:

```bash
python -m quant_pipeline.infra.smoke
```

Open `psql` inside the container:

```bash
docker compose exec postgres psql -U quant -d quant
```

Apply and verify migrations:

```bash
python -m quant_symbols.cli db upgrade
python -m quant_symbols.cli db verify
```

Downgrade the local database to Alembic base:

```bash
python -m quant_symbols.cli db downgrade-base
```

Reset local database state:

```bash
docker compose down -v
```

That reset command deletes the local Postgres volume.

## Issue #1 Infrastructure Validation

Static validation completed on 2026-06-02:

- `docker compose --env-file .env.example config` rendered successfully.
- `.env.example` defines `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `DATABASE_URL`.
- The rendered Postgres service uses image `postgres:16-alpine`, publishes host port `5432`, mounts named volume `quant_symbols_postgres_data`, and includes the `pg_isready` healthcheck.
- `infra/postgres/schema/0001_baseline_symbol_master.sql` contains the six expected `symbol_master` tables and the `vendor_symbols` exclusion constraint for effective-date overlap prevention.

Live Docker validation is pending in this runtime because the Docker daemon was unavailable:

```text
docker compose up -d postgres
unable to get image 'postgres:16-alpine': Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?
```

When the Docker daemon is available, run these commands before closing the Day 1 infrastructure validation:

```bash
docker compose up -d postgres
docker compose ps postgres
docker compose exec -T postgres psql -U quant -d quant < infra/postgres/schema/0001_baseline_symbol_master.sql
docker compose exec postgres psql -U quant -d quant -c \
  "select table_schema, table_name from information_schema.tables where table_schema = 'symbol_master' order by table_name;"
docker compose down -v
```
