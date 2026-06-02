# quant_symbols

Symbol repository and vendor-access foundation for the quant momentum pipeline.

## Day 1 Local Infrastructure

Requirements:

- Docker with Docker Compose v2
- Python 3.12

Bootstrap:

```bash
cp .env.example .env
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
docker compose up -d postgres
docker compose ps postgres
alembic upgrade head
python -m quant_pipeline.infra.smoke
```

The Postgres service should report healthy before migrations or smoke checks run.

Expected smoke output:

```text
postgres=ok database=quant user=quant alembic_head=0001_baseline_symbol_master tables=6
```

Reset local database state:

```bash
docker compose down -v
```

That command deletes the local Postgres volume.

## Database Schema

The Day 1 baseline schema is implemented by Alembic revision `0001_baseline_symbol_master` in `alembic/versions/0001_baseline_symbol_master.py`.

The SQL file at `infra/postgres/schema/0001_baseline_symbol_master.sql` remains the infrastructure reference for the initial migration.

Required baseline tables:

- `symbol_master.vendors`
- `symbol_master.exchanges`
- `symbol_master.assets`
- `symbol_master.etf_profiles`
- `symbol_master.vendor_symbols`
- `symbol_master.ingestion_runs`

Important identity rule:

- `vendor_symbols` uses `active_from` and `active_to` date windows.
- Ticker text is not canonical identity.
- The same vendor symbol may be reused over time, but overlapping active windows for the same vendor and symbol must be rejected.

## Smoke Acceptance

Day 1 is complete when:

```bash
docker compose up -d postgres
alembic upgrade head
python -m quant_pipeline.infra.smoke
```

The smoke command should verify:

- Postgres is reachable.
- Alembic head is applied.
- The six baseline `symbol_master` tables exist.

Expected output:

```text
postgres=ok database=quant user=quant alembic_head=0001_baseline_symbol_master tables=6
```

## Current GitHub Issues

- Day 1 infrastructure/schema foundation: <https://github.com/mayberryjp/quant_symbols/issues/1>
- Day 2 Massive/Polygon client foundation: <https://github.com/mayberryjp/quant_symbols/issues/2>
