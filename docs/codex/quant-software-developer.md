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

## CLI Entry Points

The project has two separate CLI surfaces:

- Database/Alembic and symbol normalization commands use `python3 -m quant_symbols.cli`.
- The retrieval-only Massive/Polygon smoke check uses the `quant-symbols-massive` console script.

`python3 -m quant_symbols.cli db ...` remains supported after installation
because the CLI wrapper is present under `src/quant_symbols/cli.py`. The
top-level `quant_symbols/cli.py` wrapper preserves checkout execution from the
repository root.

Do not document `python3 -m quant_symbols.cli vendors massive ...` as a supported
Massive smoke command. That command family is not implemented. The Massive
client smoke CLI also does not implement `--fixture`, `--dry-run`, `--market`,
or `--active`; fixture dry-run behavior belongs to `symbols sync`.

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

## Issue Workflow And Delegated Labels

Daily scope/source issues and engineering-manager design comments are not
delegated implementation assignments by default. The expected workflow is:

- the architect opens the daily issue
- the engineering manager posts implementation/spec handoff as a comment on the same issue
- role-specific sections live in that comment
- separate specialist issues are created only when Jar explicitly asks for them
- delegated labels are reserved for actual implementation assignments

For Day 5 cleanup, issues `#12`, `#13`, and `#14` are superseded by `#11` and
are already closed. Delegated labels should be removed from daily scope,
engineering-manager, and cleanup issues when those issues are not actual
implementation assignments. As of the cleanup pass on 2026-06-05, closed issues
`#1`, `#2`, `#3`, `#10`, `#11`, `#12`, `#13`, `#14`, and `#17` have no delegated
labels attached.

## Jar Verification Handoff

Run these from the host after installing the package in the active Python 3.12
environment:

```bash
python3 -m pytest -q
python3 -m quant_symbols.cli db --help
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --dry-run
quant-symbols-massive
```

Expected signs of success:

- pytest exits zero
- `db --help` lists `upgrade`, `verify`, and `downgrade-base`
- fixture dry-run prints a `symbols_sync=ok` summary and does not require a database or `MASSIVE_API_KEY`
- `quant-symbols-massive` prints `live check disabled; pass --live with MASSIVE_API_KEY set`

Database verification requires a running local Postgres service with the Day 2
schema:

```bash
docker compose up -d postgres
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli db verify
```

`python3 -m quant_symbols.cli db verify` should print a `postgres=ok` summary.
Stop the service without deleting data with `docker compose stop postgres`, or
delete the local Postgres volume with `docker compose down -v`.

Optional live Massive validation requires a real key and should be run only when
provider access is intended:

```bash
MASSIVE_API_KEY=... quant-symbols-massive --live --ticker AAPL --limit 1
```

Expected output is JSON containing `status`, `count`, `request_id`, and
`tickers`. Do not commit or paste a real `MASSIVE_API_KEY`.
