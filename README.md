# quant_symbols

Symbol repository and vendor-access foundation for the quant momentum pipeline.

## Day 1 Local Infrastructure

Requirements:

- Docker with Docker Compose v2
- Python 3.12 for later application work

Bootstrap:

```bash
cp .env.example .env
docker compose up -d postgres
docker compose ps
```

The Postgres service should report healthy before migrations or smoke checks run.

Reset local database state:

```bash
docker compose down -v
```

That command deletes the local Postgres volume.

## Database Schema

The Day 1 baseline schema is documented in `infra/postgres/schema/0001_baseline_symbol_master.sql`.

The application migration tool should be Alembic. The SQL file is the infrastructure reference for the initial migration; engineers should translate it into the Alembic baseline migration and preserve the constraints.

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

Expected output shape:

```text
postgres=ok database=quant user=quant alembic_head=0001_baseline_symbol_master tables=6
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
