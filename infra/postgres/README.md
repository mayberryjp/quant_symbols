# Postgres Infrastructure

This folder owns database infrastructure design artifacts.

Day 1 creates the symbol identity spine only. It does not create ingestion jobs, market-data tables, signal tables, or strategy tables.

## Baseline Migration Contract

The Alembic baseline migration must:

- create `btree_gist` extension
- create schemas `symbol_master`, `market_data`, and `signals`
- create the six `symbol_master` tables in `schema/0001_baseline_symbol_master.sql`
- seed the `massive` vendor row
- seed common U.S. exchange rows
- preserve the `vendor_symbols` effective-date exclusion constraint

## Local Commands

Start Postgres:

```bash
docker compose up -d postgres
```

Check health:

```bash
docker compose ps postgres
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
