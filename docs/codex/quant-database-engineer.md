# Quant Database Engineer Notes

## Day 1 PostgreSQL Implementation

The repository now contains a Python 3.12 package skeleton under `src/quant_pipeline`, Alembic migration wiring, and a database smoke command.

Database connections are configured with `DATABASE_URL`. Local development defaults are documented in `.env.example` and resolve to the `postgres` service in `docker-compose.yml`:

```text
postgresql+psycopg://quant:quant_dev_password@localhost:5432/quant
```

The baseline Alembic revision is `0001_baseline_symbol_master` in `alembic/versions/0001_baseline_symbol_master.py`. It creates:

- extension `btree_gist`
- schemas `symbol_master`, `market_data`, and `signals`
- tables `symbol_master.vendors`, `symbol_master.exchanges`, `symbol_master.assets`, `symbol_master.etf_profiles`, `symbol_master.vendor_symbols`, and `symbol_master.ingestion_runs`
- seed row for vendor code `massive`
- seed rows for common U.S. exchange MIC-style codes `XNYS`, `XNAS`, `ARCX`, `BATS`, and `OTCM`

## Symbol Identity Assumptions

Ticker text is not treated as canonical security identity. `symbol_master.assets` stores the internal asset row and optional identifiers such as CIK, composite FIGI, and share-class FIGI. `symbol_master.vendor_symbols` stores provider-specific symbols and raw provider payloads.

`vendor_symbols.active_from` and `vendor_symbols.active_to` define effective-dated vendor-symbol windows. PostgreSQL `btree_gist` supports the exclusion constraint that rejects overlapping windows for the same `(vendor_id, vendor_symbol)` pair while still allowing the same vendor symbol text to be reused across non-overlapping periods.

The baseline schema tracks active/inactive state on both assets and vendor symbols. No ingestion job, API client, market-data tables, or signal tables are implemented in Day 1.

## Migration And Smoke Commands

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

Expected smoke output:

```text
postgres=ok database=quant user=quant alembic_head=0001_baseline_symbol_master tables=6
```

Reset local state:

```bash
docker compose down -v
```

The Alembic downgrade for the baseline revision drops the six baseline tables, the three schemas, and `btree_gist`. In a shared database, review extension ownership before downgrading because other schemas could depend on `btree_gist`.
