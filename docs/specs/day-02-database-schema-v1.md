# Day 2 Database Schema v1

This repository implements Day 2 as one executable Alembic revision:
`0001_symbol_master_vendor_traceability`.

## Schemas

The migration creates three PostgreSQL schemas:

- `symbol_master`
- `market_data`
- `signals`

Only `symbol_master` receives tables in this revision. The other schemas are
created so later market-data and signal migrations have stable namespaces.

## Symbol Master Tables

The migration creates seven `symbol_master` tables:

- `vendor_sources`
- `vendor_api_runs`
- `raw_vendor_payloads`
- `exchanges`
- `symbols`
- `symbol_vendor_ids`
- `symbol_aliases`

`vendor_sources` is seeded with the `massive` source for Massive / Polygon.
`exchanges` is seeded with `XNYS`, `XNAS`, `ARCX`, `BATS`, and `OTCM`.

## Design Notes

Massive / Polygon records are treated as vendor-owned payloads. Complete raw
records are stored in `symbol_master.raw_vendor_payloads.payload` as `jsonb`.
Normalized symbol fields live in `symbol_master.symbols` and
`symbol_master.symbol_vendor_ids`.

Raw payload rows are append-only application data by contract. The database
schema links each raw payload to `vendor_api_runs`; loaders should insert a new
row when vendor content changes instead of updating old payload JSON.

`symbols` preserves active and inactive records with `active` and optional
`delisted_at`. The v1 uniqueness assumption is one active canonical ticker per
`locale`, `market`, and `canonical_ticker`; inactive historical rows can remain
for replay and survivorship-bias checks. Vendor-specific lookup is handled
separately by `symbol_vendor_ids`, which enforces one active vendor symbol per
vendor source while retaining inactive rows.

Traceability columns on `symbols` and `symbol_vendor_ids` can link derived rows
back to the first and latest vendor API runs and raw payloads used to produce
them.

## Local Commands

Start local Postgres:

```bash
docker compose up -d postgres
```

Apply migrations:

```bash
python3 -m quant_symbols.cli db upgrade
```

Verify the schema:

```bash
python3 -m quant_symbols.cli db verify
```

Expected output:

```text
postgres=ok schema_version=0001_symbol_master_vendor_traceability tables=7 vendor_sources=1 exchanges=5
```

Downgrade to base:

```bash
python3 -m quant_symbols.cli db downgrade-base
```

Downgrade drops the Day 2 tables and schemas created by this migration. Local
rebuilds should use `db downgrade-base` followed by `db upgrade`, or
`docker compose down -v` when a full database reset is acceptable.
