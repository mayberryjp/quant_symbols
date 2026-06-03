# Postgres Infrastructure

This folder owns database infrastructure design artifacts.

Day 1 creates the symbol identity spine only. It does not create ingestion jobs, market-data tables, signal tables, or strategy tables.

## Baseline Migration Contract

The Alembic baseline migration in `migrations/versions/0001_baseline_symbol_master.py`:

- creates `btree_gist` extension
- creates schemas `symbol_master`, `market_data`, and `signals`
- creates the six `symbol_master` tables in `schema/0001_baseline_symbol_master.sql`
- seeds the `massive` vendor row
- seeds common U.S. exchange rows
- preserves the `vendor_symbols` effective-date exclusion constraint

The exclusion constraint prevents overlapping `active_from` / `active_to`
windows for the same `(vendor_id, vendor_symbol)`. This keeps ticker text as a
provider-scoped identifier instead of treating it as canonical asset identity.

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

Apply the Day 1 reference schema directly for infrastructure validation:

```bash
docker compose exec -T postgres psql -U quant -d quant < infra/postgres/schema/0001_baseline_symbol_master.sql
```

List the expected baseline tables:

```bash
docker compose exec postgres psql -U quant -d quant -c \
  "select table_schema, table_name from information_schema.tables where table_schema = 'symbol_master' order by table_name;"
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
