# Quant Database Engineer Notes

## Day 1 Database Implementation

The Day 1 implementation adds Alembic wiring and a Python smoke check for the
baseline symbol master schema.

Configuration:

- `DATABASE_URL` is required by Alembic and by `python -m quant_pipeline.infra.smoke`.
- `.env.example` documents the local development value:
  `postgresql+psycopg://quant:quant_dev_password@localhost:5432/quant`.
- `migrations/env.py` and the smoke command load `.env` when present, without
  overriding already exported environment variables.

Schema:

- The baseline Alembic revision is `0001_baseline_symbol_master`.
- The migration creates `btree_gist`, schemas `symbol_master`, `market_data`,
  and `signals`, and the six baseline `symbol_master` tables:
  `vendors`, `exchanges`, `assets`, `etf_profiles`, `vendor_symbols`, and
  `ingestion_runs`.
- `vendors` is seeded with the `massive` provider row.
- `exchanges` is seeded with `XNYS`, `XNAS`, `ARCX`, `BATS`, and `OTCM`.
- `vendor_symbols` keeps provider ticker text separate from canonical asset
  identity. It supports reuse of vendor symbols over time with `active_from`
  and `active_to` date windows.
- PostgreSQL rejects overlapping effective windows for the same
  `(vendor_id, vendor_symbol)` through a GiST exclusion constraint backed by
  `btree_gist`.

Migration behavior:

- `alembic upgrade head` applies the baseline migration from scratch.
- `alembic downgrade base` drops the Day 1 tables and schemas created by the
  baseline migration. The downgrade does not drop the shared `btree_gist`
  extension because it may be used by other database objects.

Validation:

- `python -m quant_pipeline.infra.smoke` connects to Postgres, confirms the
  applied Alembic revision, and verifies the six expected `symbol_master`
  tables exist.
