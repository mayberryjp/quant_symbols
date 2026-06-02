# Postgres Infrastructure

This folder owns database infrastructure design artifacts.

Day 1 creates the symbol identity spine only. It does not create ingestion jobs, market-data tables, signal tables, or strategy tables.

## Baseline Migration Contract

The Alembic baseline migration is `0001_baseline_symbol_master` in `alembic/versions/0001_baseline_symbol_master.py`. It:

- creates `btree_gist` extension
- creates schemas `symbol_master`, `market_data`, and `signals`
- creates the six `symbol_master` tables defined by `schema/0001_baseline_symbol_master.sql`
- seeds the `massive` vendor row
- seeds common U.S. exchange rows
- preserves the `vendor_symbols` effective-date exclusion constraint

## Local Commands

Install Python dependencies:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

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

Run the database smoke check:

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

The baseline downgrade drops the Day 1 tables, the `signals`, `market_data`, and `symbol_master` schemas, and the `btree_gist` extension. In a shared database, review `btree_gist` dependencies before downgrading.
