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

Reset local database state:

```bash
docker compose down -v
```

That reset command deletes the local Postgres volume.
