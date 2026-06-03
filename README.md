# quant_symbols

Symbol repository and vendor-access foundation for the quant momentum pipeline.

## Local Infrastructure

Requirements:

- Docker with Docker Compose v2
- Python 3.12

Bootstrap:

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
docker compose up -d postgres
docker compose ps
alembic upgrade head
python -m quant_pipeline.infra.smoke
```

The Postgres service should report healthy before migrations or smoke checks run.

Stop local services without deleting data:

```bash
docker compose stop postgres
```

Reset local database state:

```bash
docker compose down -v
docker compose up -d postgres
alembic upgrade head
python -m quant_pipeline.infra.smoke
```

The `docker compose down -v` command deletes the local Postgres volume.

## Database Schema

The executable Day 2 schema is Alembic revision
`0001_symbol_master_vendor_traceability`.

Apply it locally with:

```bash
python -m quant_symbols.cli db upgrade
python -m quant_symbols.cli db verify
```

The migration creates schemas:

- `symbol_master`
- `market_data`
- `signals`

Required `symbol_master` tables:

- `symbol_master.vendor_sources`
- `symbol_master.vendor_api_runs`
- `symbol_master.raw_vendor_payloads`
- `symbol_master.exchanges`
- `symbol_master.symbols`
- `symbol_master.symbol_vendor_ids`
- `symbol_master.symbol_aliases`

Important traceability rules:

- Complete vendor records are stored in `symbol_master.raw_vendor_payloads.payload`.
- Raw vendor payload rows are append-only application data.
- Normalized symbol and vendor-id rows can link back to vendor API runs and raw payloads.
- Active and inactive symbols are preserved to avoid survivorship bias.

## Smoke Acceptance

Day 2 database smoke flow:

```bash
docker compose up -d postgres
python -m quant_symbols.cli db upgrade
python -m quant_symbols.cli db verify
python -m quant_symbols.cli db downgrade-base
python -m quant_symbols.cli db upgrade
python -m quant_symbols.cli db verify
```

Expected output shape:

```text
postgres=ok schema_version=0001_symbol_master_vendor_traceability tables=7 vendor_sources=1 exchanges=5
```

## Current GitHub Issues

- Day 2 database schema v1: <https://github.com/mayberryjp/quant_symbols/issues/2>
