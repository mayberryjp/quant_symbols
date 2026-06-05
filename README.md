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
python3 -m pip install --upgrade pip
python3 -m pip install -e .
docker compose up -d postgres
docker compose ps
alembic upgrade head
python3 -m quant_pipeline.infra.smoke
```

The Postgres service should report healthy before migrations or smoke checks run.

Stop local services without deleting data:

```bash
docker compose stop postgres
```

Reset local database state:

```bash
docker compose down -v
```

The `docker compose down -v` command deletes the local Postgres volume.

## Database Schema

Database schema and migration files are owned by the database engineer. Keep executable migration artifacts in the database engineer's migration path, not under `infra/postgres`.

The executable Day 2 schema is Alembic revision `0001_symbol_master_vendor_traceability`.

Apply it locally with:

```bash
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli db verify
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
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli db verify
python3 -m quant_symbols.cli db downgrade-base
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli db verify
```

Expected output shape:

```text
postgres=ok schema_version=0001_symbol_master_vendor_traceability tables=7 vendor_sources=1 exchanges=5
```

## Current GitHub Issues

- Day 1 infrastructure/schema foundation: <https://github.com/mayberryjp/quant_symbols/issues/1>
- Day 2 Massive/Polygon client foundation: <https://github.com/mayberryjp/quant_symbols/issues/2>

## Massive/Polygon Vendor Client

The retrieval-only Massive/Polygon client lives in `src/quant_symbols/vendors/massive/`.
It targets `/v3/reference/tickers`, handles pagination, timeout, retry/backoff,
rate-limit, and structured error behavior, and returns typed provider pages plus
raw payload handoff objects for later ingestion work.

Required configuration:

- `MASSIVE_API_KEY`

Optional configuration:

- `MASSIVE_BASE_URL`
- `MASSIVE_TIMEOUT_SECONDS`
- `MASSIVE_RETRY_COUNT`
- `MASSIVE_BACKOFF_SECONDS`
- `MASSIVE_BACKOFF_MULTIPLIER`

The client performs no Postgres writes and does not normalize vendor payloads
into symbol-master tables. Normal tests use mocked HTTP responses and do not
require a Massive/Polygon API key.

Manual live check:

```bash
quant-symbols-massive
MASSIVE_API_KEY=... quant-symbols-massive --live --ticker AAPL --limit 1
```

The first command is intentionally disabled and exits without making a network
request. Pass `--live` only for a manual provider check.

## Symbol Normalization Sync

The Day 4 symbol sync entrypoint consumes Massive/Polygon ticker reference pages,
maps them into symbol-master candidates, and can write raw payload and normalized
records to the Day 2 `symbol_master` schema.

Fixture dry-run does not require an API key or database:

```bash
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --dry-run
```

Database-backed fixture smoke flow:

```bash
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive
python3 -m quant_symbols.cli symbols sync-summary --latest
```

Live sync uses `MASSIVE_API_KEY` through `MassiveClient.from_env()` and supports
`--max-pages`, `--active true|false|all`, `--market`, `--locale`, and `--limit`.
