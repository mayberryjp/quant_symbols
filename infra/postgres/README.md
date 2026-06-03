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
