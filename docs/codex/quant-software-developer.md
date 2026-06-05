# Quant Software Developer Notes

## Massive/Polygon Vendor Client

The repository now includes a retrieval-only Massive/Polygon vendor module under
`src/quant_symbols/vendors/massive/`.

The module owns:

- environment-based client configuration
- HTTP timeout, retry, exponential backoff, and `Retry-After` rate-limit handling
- typed models for `/v3/reference/tickers` pages and ticker results
- raw provider payload handoff objects for later ingestion code
- a disabled-by-default manual live-check CLI

The module does not write to Postgres and does not normalize payloads into symbol
master tables. Later ingestion code should call `MassiveClient.iter_ticker_pages`
or `MassiveClient.iter_ticker_payloads` and decide how to create vendor run
records and raw payload rows.

## Configuration

Required:

- `MASSIVE_API_KEY`

Optional:

- `MASSIVE_BASE_URL`, default `https://api.polygon.io`
- `MASSIVE_TIMEOUT_SECONDS`, default `30`
- `MASSIVE_RETRY_COUNT`, default `3`
- `MASSIVE_BACKOFF_SECONDS`, default `0.5`
- `MASSIVE_BACKOFF_MULTIPLIER`, default `2`

Do not commit real API keys. `.env.example` contains placeholders only.

## Usage

Instantiate from environment:

```python
from quant_symbols.vendors.massive import MassiveClient

client = MassiveClient.from_env()
for payload in client.iter_ticker_payloads(market="stocks", locale="us", active=True, limit=1000):
    print(payload.provider_id, payload.payload)
```

Manual live check is disabled unless explicitly enabled:

```bash
quant-symbols-massive
MASSIVE_API_KEY=... quant-symbols-massive --live --ticker AAPL --limit 1
```

Normal tests use mocked HTTP responses and do not require a live Massive/Polygon
API key.

## Day 4 Symbol Normalization Sync

The repository now includes a narrow symbol-master sync slice under
`src/quant_symbols/symbol_master/`.

Implemented modules:

- `massive_sync.py`: sync orchestration for fixture and live Massive ticker pages
- `massive_mapper.py`: pure mapping from `TickerReference` to normalized symbol candidates
- `repository.py`: SQLAlchemy repository for `symbol_master` run, raw payload, exchange, symbol, vendor ID, and alias writes
- `fixtures.py`: deterministic local fixture loading for smoke and tests
- `summary.py`: counters and single-line summary formatting

The sync command is available through the existing project CLI:

```bash
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --dry-run
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive
python3 -m quant_symbols.cli symbols sync-summary --latest
```

Fixture dry-run mode does not require `MASSIVE_API_KEY`, SQLAlchemy, psycopg, or
a running database. Database-backed fixture/live mode uses `DATABASE_URL` and the
Day 2 `symbol_master` schema.

Live mode constructs `MassiveClient.from_env()` and supports:

- `--max-pages N`
- `--active true|false|all`
- `--market stocks`
- `--locale us`
- `--limit N`

Mapper behavior:

- Canonical ticker lookup values are uppercased while the source ticker remains preserved.
- Missing names are allowed.
- `type=CS` maps to `asset_class=equity`, `security_type=common_stock`.
- `type=ETF` maps to `asset_class=fund`, `security_type=etf`.
- ADR, REIT, warrant, unit, missing, and unsupported types are preserved through
  source/raw fields and mapped to best-effort fallback security types.
- Active and inactive records are preserved, including `delisted_utc` where it parses.
- Unknown primary exchanges create provisional exchange candidates instead of
  dropping the symbol.
- `composite_figi` and `share_class_figi` become alias records when present.

Database-backed sync behavior:

- Creates one `symbol_master.vendor_api_runs` row per execution.
- Inserts raw vendor records append-only into `symbol_master.raw_vendor_payloads`.
- Upserts normalized `exchanges`, `symbols`, `symbol_vendor_ids`, and `symbol_aliases`.
- Reuses existing symbols by composite FIGI when available, otherwise by
  `locale + market + canonical_ticker`, including inactive rows.
- Updates last-seen run and raw payload links on repeat observations while counting
  unchanged domain records separately from changed domain records.
- Marks failed runs as `failed` with partial counts and the exception message.

The current Day 2 schema does not include a separate raw page/request diagnostics
table or request URL column. This implementation stores exact raw result payloads
unchanged, stores request parameters on `vendor_api_runs`, and records failure
messages on failed runs.

## Day 5 Symbol Quality And Reporting

The repository now includes the first symbol-master quality layer under
`src/quant_symbols/symbol_master/data_quality.py`.

Implemented checks:

- Duplicate canonical ticker inside the same `locale + market` boundary emits a
  `duplicate_canonical_ticker` error finding.
- Missing or blank provider fields emit `missing_field` warnings for name,
  exchange, currency, market, locale, security type, active flag, and vendor
  identifier.
- Unsupported or unknown provider classifications emit
  `unsupported_security_type` warnings and remain mapped instead of being
  dropped.
- Unexpected U.S. stock/ETF universe values emit
  `unexpected_us_universe_value` warnings for market, locale, or currency.
- Active/inactive diffs compare the current run against raw payloads from the
  prior successful Massive ticker-reference run. Failed runs are not used as the
  diff baseline.

Day 5 adds Alembic revision `0002_symbol_quality_reporting`, which adds
`sync_summary jsonb` and `quality_findings jsonb` to
`symbol_master.vendor_api_runs`. The sync job writes a normalized summary and
finding records when a run completes or fails.

Operator commands:

```bash
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive
python3 -m quant_symbols.cli symbols quality --latest
python3 -m quant_symbols.cli symbols sync-summary --latest
```

`symbols sync-summary --latest` reports inserted, updated, unchanged,
deactivated, reactivated, skipped, warned, and errored counts from the persisted
summary payload. `symbols quality --latest` reports total warning/error counts
and category totals for the latest run.

The read-only backend app lives in `src/quant_symbols/api.py` and exposes:

```text
GET /jobs/symbol-sync/latest
```

The response is domain-shaped and includes run id, status, started/completed
timestamps, counts, warning/error totals, active/inactive diffs, and top warning
categories. It does not expose raw Massive/Polygon page payloads.
