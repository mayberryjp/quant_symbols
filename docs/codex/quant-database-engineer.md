# Quant Database Engineer Notes

Issue #2 adds the first executable PostgreSQL migration path for the repository.

## Implemented Database Surface

- Alembic configuration lives in `alembic.ini` and `alembic/env.py`.
- Migration `0001_symbol_master_vendor_traceability` creates schemas
  `symbol_master`, `market_data`, and `signals`.
- The migration creates seven `symbol_master` tables:
  `vendor_sources`, `vendor_api_runs`, `raw_vendor_payloads`, `exchanges`,
  `symbols`, `symbol_vendor_ids`, and `symbol_aliases`.
- The migration seeds the `massive` vendor source and five common U.S. exchange
  rows.
- Lookup indexes support canonical ticker lookup, vendor ticker lookup, and raw
  payload lookup by vendor API run.
- Active ticker and vendor-symbol uniqueness is enforced only for active rows so
  inactive history can be retained.

## Configuration

Database commands read `DATABASE_URL` from the environment. If unset, they use
the local Docker default from `.env.example`:

```text
postgresql+psycopg://quant:quant_dev_password@localhost:5432/quant
```

## Commands

```bash
python -m quant_symbols.cli db upgrade
python -m quant_symbols.cli db verify
python -m quant_symbols.cli db downgrade-base
```

The verify command is read-only and checks connectivity, the Alembic revision,
the seven expected `symbol_master` tables, and the seed row counts.
