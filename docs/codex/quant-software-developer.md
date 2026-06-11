# Quant Software Developer Notes

## Issue 55 Read-Only Symbol Count API

The read-only API exposes `GET /symbols/count` for the aggregate row count of
normalized symbols in `symbol_master.symbols`. The endpoint accepts the same
symbol filters that apply to `GET /symbols` where they affect the symbol
universe:

- `active=true|false`
- `market=stocks`
- `locale=us`
- `q=AAPL`

The endpoint does not accept pagination parameters for its result shape.
Requests that include `limit` or `offset` return a validation response because
the endpoint is an aggregate:

```json
{
  "total": 12345,
  "filters": {
    "active": true,
    "market": "stocks",
    "locale": "us",
    "q": null
  }
}
```

`src/quant_symbols/api/symbols.py` implements `SymbolCountParams` and
`count_symbols`. The count query uses `SELECT count(*) AS total FROM
symbol_master.symbols s` and the same shared optional filter helper as
`list_symbols`, including ticker/name `q` matching through escaped SQL `LIKE`
predicates. This keeps `/symbols` and `/symbols/count` filter behavior aligned
while preserving `/symbols` page-level `count` as the number of returned items.

`src/quant_symbols/api/app.py` wires the count route through the same injected
repository pattern and secret-redacting error handler used by the existing
symbol routes. The route is defined before dynamic symbol-id routes so
`/symbols/count` is not parsed as a symbol id. It only reads from Postgres
through `DATABASE_URL`; it does not call Massive/Polygon, start sync jobs, run
normalization, or write to symbol-master tables.

## Massive/Polygon Vendor Client

The repository now includes a retrieval-only Massive/Polygon vendor module under
`src/quant_symbols/vendors/massive/`.

The module owns:

- environment-based client configuration
- one-page ticker-reference JSON requests through `MassiveClient.get_ticker_reference_page`
- HTTP timeout, retry, exponential backoff, and `Retry-After` rate-limit handling
- typed models for `/v3/reference/tickers` pages and ticker results
- raw provider payload handoff objects for later ingestion code
- a disabled-by-default manual live-check CLI

The module does not write to Postgres and does not normalize payloads into symbol
master tables. Code that only needs to prove the Massive/Polygon HTTP boundary
can call `MassiveClient.get_ticker_reference_page(ticker="AAPL", limit=1)` to
request one `/v3/reference/tickers` page and receive the decoded JSON object.
Later ingestion code should call `MassiveClient.iter_ticker_pages` or
`MassiveClient.iter_ticker_payloads` and decide how to create vendor run records
and raw payload rows.

## Configuration

Required only for intentional live Massive/Polygon access:

- `MASSIVE_API_KEY`

Optional:

- `MASSIVE_BASE_URL`, default `https://api.polygon.io`
- `MASSIVE_TIMEOUT_SECONDS`, default `30`
- `MASSIVE_RETRY_COUNT`, default `3`
- `MASSIVE_BACKOFF_SECONDS`, default `0.5`
- `MASSIVE_BACKOFF_MULTIPLIER`, default `2`

Do not commit real API keys. `.env.example` contains placeholders only.
`MassiveConfig.from_env()` can load non-live settings without an API key.
`MassiveConfig.from_env(require_api_key=True)` is the live-access path and raises
a `MassiveConfigError` when `MASSIVE_API_KEY` is missing. `MassiveConfig` repr
output redacts the API key, and config validation errors report variable names
without including secret values.

## Usage

Instantiate from environment:

```python
from quant_symbols.vendors.massive import MassiveClient

client = MassiveClient.from_env()
page = client.get_ticker_reference_page(ticker="AAPL", limit=1)

for payload in client.iter_ticker_payloads(market="stocks", locale="us", active=True, limit=1000):
    print(payload.provider_id, payload.payload)
```

Load config without requiring a secret for non-live checks:

```python
from quant_symbols.vendors.massive import MassiveConfig

config = MassiveConfig.from_env()
```

Manual live check is disabled unless explicitly enabled:

```bash
python3 -m quant_symbols.vendors.massive.cli
MASSIVE_API_KEY=... python3 -m quant_symbols.vendors.massive.cli --live --ticker AAPL --limit 1
```

Normal tests use mocked HTTP responses and do not require a live Massive/Polygon
API key.

## Positions And Order Management Foundation

Issue #59 adds the first positions/order-management software slice. The durable
schema lives in Alembic revision `0002_positions_orders` and creates a separate
`trading` schema for:

- `portfolios`
- `positions`
- `order_intents`
- `order_events`
- `order_fills`
- `position_ledger_entries`
- `worker_heartbeats`

The current implementation records API-submitted order intents only. It does not
route orders to a broker, does not place live trades, and does not enable a
broker adapter process. `order_intents` stores the submitted ticker and nullable
`symbol_id` so unresolved tickers can be preserved for later validation while
normalized symbol identity remains available when the symbol master has a match.

`position_ledger_entries` is append-only at the database level. The migration
adds a trigger that rejects updates and deletes. Current positions are stored in
`trading.positions` with uniqueness rules for resolved `(portfolio_id,
symbol_id)` positions and unresolved `(portfolio_id, submitted_ticker, market,
locale)` positions.

Order idempotency is enforced by `UNIQUE (portfolio_id, idempotency_key)` on
`trading.order_intents`. Fill idempotency is prepared by a unique partial index
on `(order_id, source, external_fill_id)` when `external_fill_id` is present.

## Positions API Slice

The Bottle app exposes the first positions/order endpoints:

```text
GET /positions/health
GET /positions/ready
GET /portfolios
POST /portfolios
GET /positions
GET /positions/{position_id}
GET /positions/by-ticker/{ticker}
POST /orders
```

`GET /positions/health` is a liveness endpoint and does not require database
access. `GET /positions/ready` reuses the existing database readiness contract.

`POST /orders` validates and persists a buy/sell order intent, then writes the
initial `submitted` order event in the same transaction. Duplicate order
submission returns the existing order by portfolio/idempotency key and does not
create another intent or event. The accepted order-intake slice supports:

- `side`: `buy`, `sell`
- `order_type`: `market`, `limit`
- `time_in_force`: `day`, `gtc`, `ioc`, `fok`
- exactly one of `quantity` or `notional`
- required `portfolio`, `idempotency_key`, `ticker`, `source`, and `reason`

Limit orders require `limit_price`; market orders reject `limit_price`.
`stop_price` is intentionally rejected in this slice even though the schema has a
nullable column for future lifecycle support.

## Positions Configuration

The positions/order slice uses the existing `DATABASE_URL` configuration. It
adds no new secrets, API keys, or environment variables.

Database validation uses:

```bash
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli db verify
```

`db verify` now expects Alembic head `0002_positions_orders`, the existing seven
`symbol_master` tables, and the seven new `trading` tables.

## Issue 29 Slice 1 Verification

The current #29 software slice verified in this checkout is the mocked
single-request Massive client path. `MassiveClient.get_ticker_reference_page`
builds one `/v3/reference/tickers` request through an injected transport and
returns the decoded provider JSON. The focused tests verify path/query
construction, API-key query handling, secret-safe config repr output, and the
disabled-by-default smoke command.

Verified commands:

```bash
python3 -m pytest tests/test_massive_client.py tests/test_massive_cli.py -q
python3 -m quant_symbols.vendors.massive.cli
```

Expected disabled smoke output:

```text
live check disabled; pass --live with MASSIVE_API_KEY set
```

This verification does not require Docker/Postgres or `MASSIVE_API_KEY`, and it
does not prove typed parsing, live provider access, pagination, retry handling,
raw database writes, or normalized symbol behavior for #29.

## Issue 29 Slice 2 Verification

The #29 typed response parsing slice is implemented by
`src/quant_symbols/vendors/massive/models.py`. `TickerReferencePage.from_payload`
validates that a Massive `/v3/reference/tickers` page is an object with a
`results` list, then parses each result into a `TickerReference`. The typed
record exposes the currently supported Massive fields and preserves the original
provider result dictionary on `TickerReference.raw`, including unknown extra
fields.

Focused parser tests live in `tests/test_massive_models.py`. They verify one
valid ticker response, multiple ticker results, unknown extra-field preservation,
missing optional fields, and clear failure through `MassiveMalformedPayloadError`
when the top-level response shape or ticker result shape is invalid.

Verified command for this slice:

```bash
python3 -m pytest tests/test_massive_models.py tests/test_massive_client.py -q
```

This verification does not require Docker/Postgres or `MASSIVE_API_KEY`, does
not contact the live Massive/Polygon API, and does not prove raw database writes
or normalized symbol behavior for #29.

## Issue 29 Slice 3 Verification

The #29 explicit live API smoke slice is implemented in
`src/quant_symbols/vendors/massive/cli.py`. The command remains disabled by
default and only constructs a Massive client when `--live` is passed. Live mode
loads configuration with `MassiveClient.from_env()`, which requires
`MASSIVE_API_KEY`, and requests a single ticker-reference page with
`max_pages=1`.

The live smoke command supports a tiny request shape:

```bash
MASSIVE_API_KEY=... python3 -m quant_symbols.vendors.massive.cli --live --ticker AAPL --limit 1
```

`--ticker` defaults to `AAPL`, and `--limit` defaults to `1`. `--limit` must be
greater than zero. The command prints a compact JSON summary containing provider
status, count, request id, and returned tickers. It does not print
`MASSIVE_API_KEY`.

Focused CLI tests live in `tests/test_massive_cli.py`. They verify that default
mode does not construct a client, live mode without a key fails clearly, live
mode can run through an injected fake client, ticker/limit arguments are passed
to the client request path, and output remains short and secret-safe.

Verified commands for this slice:

```bash
python3 -m pytest tests/test_massive_cli.py tests/test_massive_client.py -q
python3 -m quant_symbols.vendors.massive.cli
env -u MASSIVE_API_KEY python3 -m quant_symbols.vendors.massive.cli --live
```

Observed output:

```text
........................                                                 [100%]
24 passed in 0.11s
live check disabled; pass --live with MASSIVE_API_KEY set
massive client error: MASSIVE_API_KEY is required for live Massive/Polygon access
```

The missing-key live command exits with status 2 and writes its error to stderr.
This verification does not require Docker/Postgres or a real `MASSIVE_API_KEY`.
The optional live command above was not run in this checkout.

## Issue 29 Slice 4 Verification

The #29 raw payload database-write slice is implemented by
`src/quant_symbols/symbol_master/massive_raw_storage.py`.
`MassiveRawPayloadStorageJob.store_pages` accepts parsed Massive
`TickerReferencePage` objects, creates or reuses the `massive` vendor source,
creates one `symbol_master.vendor_api_runs` row, inserts each ticker result raw
dictionary into `symbol_master.raw_vendor_payloads`, links each payload row to
the run, and finishes the run as `succeeded` or `failed`.

The raw storage job is intentionally raw-only. It does not call the Massive live
network, does not paginate, and does not upsert normalized `symbols`,
`symbol_vendor_ids`, `symbol_aliases`, or `exchanges`. Existing broader symbol
sync code still owns normalized symbol behavior and is not the proof point for
this slice.

Request parameters are sanitized before storage, and failure messages are
redacted for secret-like values such as API keys and tokens. The schema already
supports the required run and raw payload fields, so this slice did not add a
migration.

Focused raw-storage tests live in `tests/test_massive_raw_storage.py`. They
verify one run is created, expected raw payload rows are inserted, raw provider
dictionaries are preserved unchanged, rows link back to the run, request params
and failed-run errors do not leak API-key values, and repeated runs are
append-only by design.

Verified commands for this slice:

```bash
python3 -m pytest tests/test_massive_raw_storage.py -q
python3 -m pytest -q
```

Observed output:

```text
...                                                                      [100%]
3 passed in 0.04s
.................................................................        [100%]
65 passed in 0.14s
```

This verification does not require Docker/Postgres or `MASSIVE_API_KEY`. The
tests use a fake repository/engine boundary to prove the raw-storage
orchestration without contacting the live Massive/Polygon API. Jar can run the
same commands from a clean checkout; no cleanup is required. Optional database
schema validation remains:

```bash
docker compose up -d postgres
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli db verify
```

Cleanup after optional Docker validation is `docker compose down` or
`docker compose down -v` if the local Postgres volume should be deleted.

## Issue 29 Slice 5 Verification

The #29 raw-fetch operator command is implemented on the existing Massive CLI:

```bash
python3 -m quant_symbols.vendors.massive.cli --raw-fetch --fixture tests/fixtures/massive/active_stock.json --ticker AAPL --limit 1
```

The command loads the fixture into `TickerReferencePage` objects and stores raw
provider records through `MassiveRawPayloadStorageJob`. It writes one
`vendor_api_runs` row and one `raw_vendor_payloads` row for the single-record
fixture when the database schema is available. It does not call normalized
symbol sync code and does not upsert `symbols`, `symbol_vendor_ids`,
`symbol_aliases`, or `exchanges`.

Fixture raw-fetch mode does not require `MASSIVE_API_KEY`, but it does require
SQLAlchemy and a reachable database because it performs real raw storage. Jar
verification from a dependency-installed checkout:

```bash
docker compose up -d postgres
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.vendors.massive.cli --raw-fetch --fixture tests/fixtures/massive/active_stock.json --ticker AAPL --limit 1
```

Expected output shape:

```text
massive_raw_fetch=ok run_id=<database id> mode=fixture status=ok records_seen=1 raw_payloads_inserted=1 errors=0
```

The `run_id` is database-assigned and changes between runs. Cleanup after
database verification is `docker compose down`, or `docker compose down -v` if
Jar wants to delete the local Postgres volume.

Optional live raw fetch uses the same command with `--live` instead of
`--fixture` and requires `MASSIVE_API_KEY`:

```bash
MASSIVE_API_KEY=... python3 -m quant_symbols.vendors.massive.cli --raw-fetch --live --ticker AAPL --limit 1
```

The command stores request metadata containing mode, ticker, limit, and fixture
path when present. It does not store or print the API key. In this checkout, the
Postgres-backed raw-fetch command was not run because the Docker daemon is not
available and the local Python environment does not have SQLAlchemy installed.
The command path was still exercised by focused tests with injected client,
engine, and storage fakes.

Verified commands for this slice:

```bash
python3 -m pytest tests/test_massive_cli.py tests/test_massive_raw_storage.py -q
python3 -m pytest -q
python3 -m quant_symbols.vendors.massive.cli
env -u MASSIVE_API_KEY python3 -m quant_symbols.vendors.massive.cli --raw-fetch --live
```

Observed output:

```text
..............                                                           [100%]
14 passed in 0.04s
......................................................................   [100%]
70 passed in 0.09s
live check disabled; pass --live with MASSIVE_API_KEY set
massive client error: MASSIVE_API_KEY is required for live Massive/Polygon access
```

The focused CLI tests verify fixture mode without `MASSIVE_API_KEY`, live mode
without a key failing before storage, live raw fetch with an injected fake
client, raw storage through an injected fake job, and secret-safe summary and
request parameters.

## CLI Entry Points

The project has two separate CLI surfaces:

- Database/Alembic commands use `python3 -m quant_symbols.cli db ...`.
- Symbol-master sync commands, when the Day 4 sync code is the work being
  reviewed, use `python3 -m quant_symbols.cli symbols ...`.
- The Massive/Polygon client smoke and raw-fetch checks use
  `python3 -m quant_symbols.vendors.massive.cli`.

`python3 -m quant_symbols.cli db ...` remains supported after installation
because the CLI wrapper is present under `src/quant_symbols/cli.py`. The
top-level `quant_symbols/cli.py` wrapper preserves checkout execution from the
repository root.

Do not document `python3 -m quant_symbols.cli vendors massive ...` as a supported
Massive smoke command. That command family is not implemented. The Massive
client smoke CLI does not implement `--dry-run`, `--market`, or `--active`.
`--fixture` is supported only with the raw-fetch command path.

Do not use `python3 -m quant_symbols.cli symbols sync ...` as proof that the
Massive client smoke CLI works. That command belongs to the symbol-master sync
work, not the retrieval-only Massive client check.

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
environment when reviewing the Massive client / documentation cleanup:

```bash
python3 -m pytest -q
python3 -m quant_symbols.vendors.massive.cli --help
python3 -m quant_symbols.cli db --help
python3 -m quant_symbols.vendors.massive.cli
```

Expected signs of success:

- pytest exits zero
- `python3 -m quant_symbols.vendors.massive.cli --help` documents `--live`
- `db --help` lists `upgrade`, `verify`, and `downgrade-base`
- `python3 -m quant_symbols.vendors.massive.cli` prints `live check disabled; pass --live with MASSIVE_API_KEY set`

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

Only use the symbol-master sync command when the PR is specifically about the
Day 4 sync path:

```bash
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --dry-run
```

Expected output starts with `symbols_sync=ok`. This command is not a Massive
client smoke test.

Optional live Massive validation requires a real key and should be run only when
provider access is intended:

```bash
MASSIVE_API_KEY=... python3 -m quant_symbols.vendors.massive.cli --live
```

Expected output is JSON containing `status`, `count`, `request_id`, and
`tickers`. Do not commit or paste a real `MASSIVE_API_KEY`.

## Issue 35 Slice 1 Raw Payload Normalization

The #35 Slice 1 pure raw-payload mapper is implemented in
`src/quant_symbols/symbol_master/normalization.py`. It accepts one raw
Massive/Polygon ticker-reference dictionary and returns a frozen
`MassiveTickerCandidate` without calling HTTP services, requiring a database, or
mutating the input dictionary.

The mapper currently normalizes these fields:

- source ticker exactly as provided and canonical ticker uppercased
- name, market, locale, primary exchange code, and currency name
- provider type plus internal `asset_type` and `security_type`
- active flag
- CIK, composite FIGI, and share-class FIGI
- parsed `last_updated_utc` and `delisted_utc` timestamps when valid
- a copied raw provider dictionary on `raw_record`

Verified type mapping for this slice:

- `CS` maps to `asset_type=equity`, `security_type=common_stock`
- `ETF` maps to `asset_type=fund`, `security_type=etf`
- unknown or missing provider types map to `asset_type=unknown`,
  `security_type=unknown`, while preserving the provider type on the candidate

This slice does not write exchanges, symbols, vendor IDs, aliases, or raw
payload rows. It does not score quality, decide trade eligibility, call Massive,
or require `MASSIVE_API_KEY`.

Verified commands:

```bash
python3 -m pytest tests/test_symbol_master_normalization.py -q
python3 -m pytest tests/test_symbol_master_mapper.py -q
```

Observed output:

```text
7 passed
8 passed
```

## Issue 35 Slice 2 Exchange Candidate And Upsert

The #35 Slice 2 exchange-only path is implemented by
`map_massive_exchange_candidate` in
`src/quant_symbols/symbol_master/normalization.py` and
`SymbolMasterRepository.upsert_exchange_candidate` in
`src/quant_symbols/symbol_master/repository.py`.

`map_massive_exchange_candidate` accepts the Slice 1 `MassiveTickerCandidate`
and returns a `MassiveExchangeCandidate` for the candidate's primary exchange,
or `None` when the provider exchange code is missing or blank. Exchange codes
are uppercased into the schema's `mic` field. Known Massive/Polygon primary
exchange codes are mapped to stable names for `XNYS`, `XNAS`, `ARCX`, `BATS`,
and `OTCM`. Unknown nonblank codes are preserved predictably as provisional
exchange candidates named `Unmapped exchange <MIC>`.

`SymbolMasterRepository.upsert_exchange_candidate` writes only
`symbol_master.exchanges`. It selects by `mic`, inserts when missing, updates
the name for known non-provisional candidates when the stored name differs, and
returns inserted, updated, unchanged, or skipped counts. It does not insert or
update `symbols`, `symbol_vendor_ids`, `symbol_aliases`, raw payload rows, or
vendor run rows.

Focused tests live in `tests/test_symbol_master_exchange_upsert.py`. They use a
fake connection abstraction because this worker did not have SQLAlchemy or
Docker/Postgres available, and they fail if the exchange-only method touches
non-exchange symbol-master tables.

Verified commands:

```bash
python3 -m pytest tests/test_symbol_master_exchange_upsert.py tests/test_symbol_master_normalization.py -q
python3 -m pytest -q
```

Observed output:

```text
13 passed
83 passed
```

This slice does not require `MASSIVE_API_KEY`, does not call Massive/Polygon,
does not add migrations, and does not implement symbol rows, vendor IDs,
aliases, or normalize-raw commands. Optional Postgres verification for Jar from
a dependency-installed checkout is:

```bash
docker compose up -d postgres
python3 -m quant_symbols.cli db upgrade
python3 -m pytest tests/test_symbol_master_exchange_upsert.py -q
python3 -m pytest -q
```

Cleanup after optional Docker validation is `docker compose down`, or
`docker compose down -v` if the local Postgres volume should be deleted.

## Issue 41 Slice 5 Sync Status API

The #41 Slice 5 read-only operator sync status endpoints are implemented in
`src/quant_symbols/api/app.py` and `src/quant_symbols/api/sync_status.py`.
They expose operator-oriented views over existing `vendor_api_runs` and linked
raw payload counts. They do not execute jobs.

Endpoints:

- `GET /sync/latest?vendor=massive&endpoint=/v3/reference/tickers`
- `GET /sync/runs?vendor=massive&endpoint=/v3/reference/tickers&status=succeeded&limit=20&offset=0`
- `GET /sync/runs/{run_id}`

`/sync/latest` defaults to vendor `massive` and endpoint
`/v3/reference/tickers`. It returns the newest matching run regardless of run
status. Missing runs return:

```json
{"status":"not_found","error":"sync run not found"}
```

Latest response shape:

```json
{
  "status": "ok",
  "latest": {
    "id": 5,
    "vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
    "endpoint": "/v3/reference/tickers",
    "run_status": "succeeded",
    "started_at": "2026-06-07T09:00:00+00:00",
    "finished_at": "2026-06-07T09:00:10+00:00",
    "records_seen": 5,
    "records_inserted": 5,
    "records_failed": 0,
    "error_message": null,
    "raw_payload_count": 5
  }
}
```

`/sync/runs` supports `vendor` default `massive`, `endpoint` default
`/v3/reference/tickers`, optional `status` limited to `running`, `succeeded`,
`failed`, or `cancelled`, `limit` default `20` and maximum `100`, and `offset`
default `0`. Rows are ordered by `started_at DESC, id DESC`.

Run list response shape:

```json
{
  "items": [
    {
      "id": 5,
      "vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
      "endpoint": "/v3/reference/tickers",
      "run_status": "succeeded",
      "started_at": "2026-06-07T09:00:00+00:00",
      "finished_at": "2026-06-07T09:00:10+00:00",
      "records_seen": 5,
      "records_inserted": 5,
      "records_failed": 0,
      "error_message": null,
      "raw_payload_count": 5
    }
  ],
  "limit": 20,
  "offset": 0,
  "count": 1
}
```

`/sync/runs/{run_id}` returns one run with `request_params` and
`raw_payload_count`. Missing run ids return:

```json
{"status":"not_found","error":"sync run not found"}
```

Run detail response shape:

```json
{
  "id": 5,
  "vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
  "endpoint": "/v3/reference/tickers",
  "request_params": {"market": "stocks"},
  "run_status": "succeeded",
  "started_at": "2026-06-07T09:00:00+00:00",
  "finished_at": "2026-06-07T09:00:10+00:00",
  "records_seen": 5,
  "records_inserted": 5,
  "records_failed": 0,
  "error_message": null,
  "raw_payload_count": 5
}
```

The endpoint code is read-only. It uses SQLAlchemy bound parameters, opens the
database lazily only when an endpoint is called, does not construct a
Massive/Polygon client, does not require `MASSIVE_API_KEY`, and does not start
sync, normalize-raw, scheduler, worker, trading, momentum, or HTTP job execution
logic. Repository or database failures return compact error JSON and redact a
secret-bearing `DATABASE_URL`.

Verified commands in this checkout:

```bash
python3 -m pytest tests/test_api_sync_status.py -q
python3 -m pytest tests/test_api_app.py tests/test_api_symbols.py tests/test_api_symbol_detail.py tests/test_api_traceability.py tests/test_api_sync_status.py -q
python3 -m pytest -q
python3 - <<'PY'
from quant_symbols.api.app import app
print(app.title)
PY
```

Observed output:

```text
11 passed in 0.46s
46 passed in 1.00s
149 passed in 1.17s
quant-symbols-api
```

Local no-database smoke used this command:

```bash
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
```

Observed endpoint output without `DATABASE_URL`:

```text
$ curl -fsS 'http://127.0.0.1:8000/health'
{"status":"ok","service":"quant-symbols-api"}

$ curl -i 'http://127.0.0.1:8000/sync/latest'
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}

$ curl -i 'http://127.0.0.1:8000/sync/runs?limit=5'
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}

$ curl -i 'http://127.0.0.1:8000/sync/runs/1'
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}
```

Cleanup for the local smoke server was `Ctrl-C` in the Uvicorn terminal. No
Docker container was started for this slice.

External database verification was not run in this worker because no reachable
`DATABASE_URL` was supplied. Jar can verify against an externally supplied
migrated Postgres database with:

```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME'
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --max-pages 1
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
```

Then, from another shell:

```bash
curl -fsS 'http://127.0.0.1:8000/health'
curl -fsS 'http://127.0.0.1:8000/ready'
curl -fsS 'http://127.0.0.1:8000/sync/latest'
curl -fsS 'http://127.0.0.1:8000/sync/runs?limit=5'
curl -fsS 'http://127.0.0.1:8000/sync/runs?status=succeeded&limit=5'
curl -fsS 'http://127.0.0.1:8000/sync/runs/1'
curl -i 'http://127.0.0.1:8000/sync/runs/999999999'
```

Expected signs are `status=ok` from `/health`, `database=ok` and
`schema_version=0001_symbol_master_vendor_traceability` from `/ready`, the
latest Massive ticker-reference run from `/sync/latest`, bounded sync run
history from `/sync/runs`, and HTTP 404 for missing sync run ids.
`DATABASE_URL` is required for `/ready` and all `/sync/...` endpoints; it is not
required for `/health`.

Postgres compose was not added. `supervisord.conf`, `Dockerfile`, and
`docker-compose.yml` were not changed in this slice, so the existing persistent
`quant-symbols-api` supervisord process contract remains in place.

Known limitations: this slice does not add HTTP-triggered jobs, `POST /jobs`,
`POST /sync`, `POST /normalize-raw`, background workers, auth, frontend work,
live Massive calls, or scheduler behavior.

## Issue 41 Slice 4 Vendor Traceability API

The #41 Slice 4 read-only traceability endpoints are implemented in
`src/quant_symbols/api/app.py` and `src/quant_symbols/api/traceability.py`.
They expose aliases, vendor IDs, raw payload links, and vendor API runs without
embedding traceability data in normal symbol list/detail responses.

Endpoints:

- `GET /symbols/{symbol_id}/aliases`
- `GET /symbols/{symbol_id}/vendor-ids`
- `GET /symbols/{symbol_id}/raw-payloads?limit=50&offset=0`
- `GET /vendor-runs?vendor=massive&endpoint=/v3/reference/tickers&status=succeeded&limit=20&offset=0`
- `GET /vendor-runs/{run_id}`

Symbol-scoped traceability endpoints first check that the normalized symbol id
exists. Missing symbols return:

```json
{"status":"not_found","error":"symbol not found"}
```

Existing symbols with no traceability rows return HTTP 200 with an empty
`items` list. `raw-payloads` is bounded with `limit` default `50`, minimum `1`,
maximum `100`, and `offset` default `0`, minimum `0`.

Alias response shape:

```json
{
  "symbol_id": 1,
  "items": [
    {
      "id": 10,
      "alias_type": "ticker",
      "alias_value": "AAPL",
      "active": true,
      "source_vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
      "source_payload_id": 100,
      "valid_from": null,
      "valid_to": null
    }
  ],
  "count": 1
}
```

Vendor ID response shape:

```json
{
  "symbol_id": 1,
  "items": [
    {
      "id": 20,
      "vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
      "vendor_symbol": "AAPL",
      "vendor_asset_id": "BBG000B9XRY4",
      "active": true,
      "first_seen_run_id": 5,
      "first_seen_payload_id": 100,
      "last_seen_run_id": 5,
      "last_seen_payload_id": 100
    }
  ],
  "count": 1
}
```

Raw payload response shape:

```json
{
  "symbol_id": 1,
  "items": [
    {
      "id": 100,
      "vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
      "vendor_api_run_id": 5,
      "provider_record_id": "AAPL",
      "provider_ticker": "AAPL",
      "received_at": "2026-06-07T09:00:00+00:00",
      "payload": {"ticker": "AAPL"}
    }
  ],
  "limit": 50,
  "offset": 0,
  "count": 1
}
```

Vendor run list supports `vendor` with default `massive`, optional exact
`endpoint`, optional `status` limited to `running`, `succeeded`, `failed`, or
`cancelled`, `limit` default `20` and maximum `100`, and `offset` default `0`.
Rows are ordered by `started_at DESC, id DESC`.

Vendor run list response shape:

```json
{
  "items": [
    {
      "id": 5,
      "vendor": {"id": 1, "code": "massive", "name": "Massive / Polygon"},
      "endpoint": "/v3/reference/tickers",
      "status": "succeeded",
      "started_at": "2026-06-07T09:00:00+00:00",
      "finished_at": "2026-06-07T09:00:10+00:00",
      "records_seen": 5,
      "records_inserted": 5,
      "records_failed": 0,
      "error_message": null
    }
  ],
  "limit": 20,
  "offset": 0,
  "count": 1
}
```

Vendor run detail returns one run plus `request_params` and
`raw_payload_count`. Missing run ids return:

```json
{"status":"not_found","error":"vendor run not found"}
```

The endpoint code is read-only. It uses SQLAlchemy bound parameters, opens the
database lazily only when an endpoint is called, does not construct a
Massive/Polygon client, does not require `MASSIVE_API_KEY`, and does not run
sync, normalization, ingestion, trading, momentum, scheduler, or job execution
logic. Repository or database failures return compact error JSON and redact a
secret-bearing `DATABASE_URL`.

Verified commands in this checkout:

```bash
python3 -m pytest tests/test_api_traceability.py -q
python3 -m pytest tests/test_api_app.py tests/test_api_symbols.py tests/test_api_symbol_detail.py tests/test_api_traceability.py -q
python3 -m pytest -q
python3 - <<'PY'
from quant_symbols.api.app import app
print(app.title)
PY
```

Observed output:

```text
11 passed in 0.46s
35 passed in 0.74s
138 passed in 0.94s
quant-symbols-api
```

Local no-database smoke used this command:

```bash
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
```

Observed endpoint output without `DATABASE_URL`:

```text
$ curl -fsS 'http://127.0.0.1:8000/health'
{"status":"ok","service":"quant-symbols-api"}

$ curl -i 'http://127.0.0.1:8000/symbols/1/aliases'
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}

$ curl -i 'http://127.0.0.1:8000/symbols/1/vendor-ids'
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}

$ curl -i 'http://127.0.0.1:8000/symbols/1/raw-payloads?limit=5'
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}

$ curl -i 'http://127.0.0.1:8000/vendor-runs?limit=5'
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}

$ curl -i 'http://127.0.0.1:8000/vendor-runs/1'
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}
```

Cleanup for the local smoke server was `Ctrl-C` in the Uvicorn terminal. No
Docker container was started for this slice.

External database verification was not run in this worker because no reachable
`DATABASE_URL` was supplied. Jar can verify against an externally supplied
migrated Postgres database with:

```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME'
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --max-pages 1
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
```

Then, from another shell:

```bash
curl -fsS 'http://127.0.0.1:8000/health'
curl -fsS 'http://127.0.0.1:8000/ready'
curl -fsS 'http://127.0.0.1:8000/symbols?q=AAPL&limit=1'
curl -fsS 'http://127.0.0.1:8000/symbols/by-ticker/AAPL'
curl -fsS 'http://127.0.0.1:8000/symbols/1/aliases'
curl -fsS 'http://127.0.0.1:8000/symbols/1/vendor-ids'
curl -fsS 'http://127.0.0.1:8000/symbols/1/raw-payloads?limit=5'
curl -fsS 'http://127.0.0.1:8000/vendor-runs?vendor=massive&limit=5'
curl -fsS 'http://127.0.0.1:8000/vendor-runs/1'
```

Expected signs are `status=ok` from `/health`, `database=ok` and
`schema_version=0001_symbol_master_vendor_traceability` from `/ready`,
traceability rows for fixture-normalized symbols where links exist, bounded raw
payload results, Massive vendor run metadata, and HTTP 404 for missing vendor
run ids. `DATABASE_URL` is required for `/ready`, symbol traceability endpoints,
and vendor run endpoints; it is not required for `/health`.

Postgres compose was not added. `supervisord.conf`, `Dockerfile`, and
`docker-compose.yml` were not changed in this slice, so the existing persistent
`quant-symbols-api` supervisord process contract remains in place.

Known limitations: this slice does not add HTTP-triggered jobs, `POST /jobs`,
auth, frontend work, live Massive calls, or scheduler behavior.

## Issue 41 Slice 3 Symbol Detail API

The #41 Slice 3 read-only API detail endpoints are implemented in
`src/quant_symbols/api/app.py` and `src/quant_symbols/api/symbols.py`.

Endpoints:

- `GET /symbols/{symbol_id}`
- `GET /symbols/by-ticker/{ticker}?market=stocks&locale=us&active=true`

`GET /symbols/{symbol_id}` uses an integer path parameter and looks up
`symbol_master.symbols.id` exactly. Invalid path values such as
`/symbols/not-an-int` return FastAPI validation errors before the lookup
callable is invoked.

`GET /symbols/by-ticker/{ticker}` performs a case-insensitive lookup against
`canonical_ticker`. The default filters are `market=stocks`, `locale=us`, and
`active=true`. Explicit query parameters override those defaults. If multiple
rows match the by-ticker filters, the database query orders by `active DESC,
id DESC` and returns one row.

Both endpoints return normalized symbol fields only:

```json
{
  "id": 1,
  "canonical_ticker": "AAPL",
  "name": "Apple Inc.",
  "market": "stocks",
  "locale": "us",
  "currency": "USD",
  "asset_class": "equity",
  "security_type": "common_stock",
  "active": true,
  "cik": "0000320193",
  "composite_figi": "BBG000B9XRY4",
  "share_class_figi": "BBG001S5N8V8",
  "delisted_at": null,
  "primary_exchange": {
    "id": 2,
    "mic": "XNAS",
    "name": "Nasdaq Stock Market"
  }
}
```

When no primary exchange is present, `primary_exchange` is `null`. Missing
records return:

```json
{"status":"not_found","error":"symbol not found"}
```

Repository or database failures return compact error JSON and redact a
secret-bearing `DATABASE_URL`. The endpoint code is read-only: it does not call
Massive/Polygon, construct a Massive client, run sync, run normalization, write
database rows, expose aliases, expose vendor IDs, expose raw payloads, or expose
vendor runs.

The API module still avoids import-time database access. SQLAlchemy imports and
engine creation happen inside repository functions when an endpoint calls them.
`create_app()` accepts injectable `symbol_detail` and `symbol_by_ticker`
callables so normal tests can run without live Postgres.

Verified commands in this checkout:

```bash
python3 -m pytest tests/test_api_symbol_detail.py -q
python3 -m pytest tests/test_api_app.py tests/test_api_symbols.py tests/test_api_symbol_detail.py -q
python3 -m pytest -q
python3 - <<'PY'
from quant_symbols.api.app import app
print(app.title)
PY
```

Observed output:

```text
11 passed in 0.42s
24 passed in 0.52s
127 passed in 0.71s
quant-symbols-api
```

Local no-database smoke used this command:

```bash
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
```

Observed endpoint output without `DATABASE_URL`:

```text
$ curl -fsS 'http://127.0.0.1:8000/health'
{"status":"ok","service":"quant-symbols-api"}

$ curl -i 'http://127.0.0.1:8000/symbols/1'
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}

$ curl -i 'http://127.0.0.1:8000/symbols/by-ticker/AAPL'
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}
```

Cleanup for the local smoke server was `Ctrl-C` in the Uvicorn terminal. No
Docker container was started for this slice.

External database verification was not run in this worker because no reachable
`DATABASE_URL` was supplied. Jar can verify against an externally supplied
migrated Postgres database with:

```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME'
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --max-pages 1
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
```

Then, from another shell:

```bash
curl -fsS 'http://127.0.0.1:8000/health'
curl -fsS 'http://127.0.0.1:8000/ready'
curl -fsS 'http://127.0.0.1:8000/symbols?q=AAPL&limit=1'
curl -fsS 'http://127.0.0.1:8000/symbols/by-ticker/AAPL'
curl -i 'http://127.0.0.1:8000/symbols/1'
curl -i 'http://127.0.0.1:8000/symbols/999999999'
```

Expected signs are `status=ok` from `/health`, `database=ok` and
`schema_version=0001_symbol_master_vendor_traceability` from `/ready`, a
normalized AAPL record from the by-ticker endpoint after fixture sync, and HTTP
404 for missing ids. `DATABASE_URL` is required for `/ready`, `/symbols`,
`/symbols/{symbol_id}`, and `/symbols/by-ticker/{ticker}` database-backed
success; it is not required for `/health`.

Postgres compose was not added. `supervisord.conf`, `Dockerfile`, and
`docker-compose.yml` were not changed in this slice, so the existing persistent
`quant-symbols-api` supervisord process contract remains in place.

Known limitations: this slice does not add aliases, vendor IDs, raw payloads,
vendor runs, operator status endpoints, auth, frontend work, HTTP-triggered
jobs, live Massive calls, or scheduler behavior.

## Issue 41 Slice 2 Read-Only Symbol List API

The #41 Slice 2 API list endpoint is implemented by
`src/quant_symbols/api/app.py` and `src/quant_symbols/api/symbols.py`.

`GET /symbols` reads normalized rows from `symbol_master.symbols` with a left
join to `symbol_master.exchanges` for the primary exchange object. The endpoint
returns only normalized symbol fields:

- `id`
- `canonical_ticker`
- `name`
- `market`
- `locale`
- `currency`
- `asset_class`
- `security_type`
- `active`
- `primary_exchange`, either an object with `id`, `mic`, and `name`, or `null`

It does not include raw vendor payloads, vendor API runs, vendor IDs, aliases,
Massive-specific response fields, or any job execution behavior.

Supported query parameters are:

- `active`, optional FastAPI boolean
- `market`, optional exact match
- `locale`, optional exact match
- `q`, optional case-insensitive search over canonical ticker and name
- `limit`, default `100`, minimum `1`, maximum `500`
- `offset`, default `0`, minimum `0`

Rows are ordered by `canonical_ticker ASC, id ASC`. The SQL query uses
SQLAlchemy bound parameters and opens a database connection only when
`GET /symbols` is called. API import and `/health` do not connect to the
database.

Example response shape from an injected test repository:

```json
{
  "items": [
    {
      "id": 1,
      "canonical_ticker": "AAPL",
      "name": "Apple Inc.",
      "market": "stocks",
      "locale": "us",
      "currency": "USD",
      "asset_class": "equity",
      "security_type": "common_stock",
      "active": true,
      "primary_exchange": {
        "id": 2,
        "mic": "XNAS",
        "name": "Nasdaq Stock Market"
      }
    }
  ],
  "limit": 100,
  "offset": 0,
  "count": 1
}
```

Empty result behavior is stable:

```json
{"items":[],"limit":5,"offset":0,"count":0}
```

With no `DATABASE_URL` configured, local Uvicorn smoke validation observed:

```bash
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
curl -fsS 'http://127.0.0.1:8000/health'
curl -i 'http://127.0.0.1:8000/symbols?limit=5'
```

Observed output:

```text
{"status":"ok","service":"quant-symbols-api"}
HTTP/1.1 500 Internal Server Error
content-type: application/json

{"status":"error","error":"DATABASE_URL is not configured"}
```

Cleanup for that smoke process was `Ctrl+C` in the Uvicorn terminal.

Verified commands:

```bash
python3 -m pytest tests/test_api_symbols.py -q
python3 -m pytest tests/test_api_app.py tests/test_api_symbols.py -q
python3 -m pytest -q
python3 - <<'PY'
from quant_symbols.api.app import app
print(app.title)
PY
```

Observed output:

```text
8 passed in 0.35s
13 passed in 0.36s
116 passed in 0.49s
quant-symbols-api
```

Jar can verify against an externally supplied migrated Postgres database with:

```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME'
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --max-pages 1
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
```

Then from another shell:

```bash
curl -fsS 'http://127.0.0.1:8000/health'
curl -fsS 'http://127.0.0.1:8000/ready'
curl -fsS 'http://127.0.0.1:8000/symbols?active=true&market=stocks&locale=us&limit=10'
curl -fsS 'http://127.0.0.1:8000/symbols?q=AAPL&limit=5'
```

This worker did not run DB-backed endpoint verification because no external
Postgres `DATABASE_URL` was supplied. Docker smoke validation was not run for
this slice. `supervisord.conf` was not changed; the persistent API program
remains `quant-symbols-api`.

Known limitations for this slice: symbol detail, by-ticker lookup, aliases,
vendor IDs, raw payloads, vendor runs, and operator status endpoints remain
future slices.

## Issue 41 Slice 1 API Runtime Foundation

The #41 Slice 1 backend API foundation is implemented under
`src/quant_symbols/api/`.

Implemented modules:

- `app.py`: FastAPI app factory, module-level `app`, `GET /health`, and
  `GET /ready`
- `readiness.py`: lazy database readiness check using `DATABASE_URL`
- `__init__.py`: package exports for the API app factory and app

The API does not connect to Postgres at import time. `GET /health` is a process
liveness check and does not require `DATABASE_URL` or database access.
`GET /ready` connects only when called. It checks `SELECT 1`, the Alembic
version, and the seven expected `symbol_master` tables:

- `vendor_sources`
- `vendor_api_runs`
- `raw_vendor_payloads`
- `exchanges`
- `symbols`
- `symbol_vendor_ids`
- `symbol_aliases`

The expected schema version remains
`0001_symbol_master_vendor_traceability`.

Endpoint examples verified in this checkout:

```bash
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
curl -fsS http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
```

Observed `/health` response:

```json
{"status":"ok","service":"quant-symbols-api"}
```

Observed `/ready` response without `DATABASE_URL`:

```text
HTTP/1.1 503 Service Unavailable
```

```json
{"status":"not_ready","database":"error","error":"DATABASE_URL is not configured"}
```

When `DATABASE_URL` points to a reachable migrated database, `/ready` should
return:

```json
{"status":"ok","database":"ok","schema_version":"0001_symbol_master_vendor_traceability","tables":7}
```

Jar external database verification:

```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME'
python3 -m quant_symbols.cli db upgrade
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

`DATABASE_URL` is not required for `/health`, API import, or unit tests that
inject the readiness dependency. `DATABASE_URL` is required for a successful
real `/ready` database check. Error responses redact full secret-bearing
database URLs when they appear in readiness exceptions.

Supervisor/container contract:

- `supervisord.conf` defines `[program:quant-symbols-api]`.
- Command:
  `python3 -m uvicorn quant_symbols.api.app:app --host 0.0.0.0 --port %(ENV_API_PORT)s`
- The API program has `autostart=true`, `autorestart=true`, stdout/stderr
  logging, and `PYTHONUNBUFFERED=1`.
- `Dockerfile` sets `API_PORT=8000`.
- The existing `[program:symbols-sync]` remains defined but now has
  `autostart=false` so API-only container verification does not start a live
  Massive sync loop by default.

No Postgres service was added to `docker-compose.yml`. Database-backed API
readiness assumes an externally supplied `DATABASE_URL`.

Verified commands in this checkout:

```bash
python3 -m pytest tests/test_api_app.py -q
python3 -m pytest -q
python3 - <<'PY'
from quant_symbols.api.app import app
print(app.title)
PY
python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000
curl -fsS http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
```

Observed test output:

```text
5 passed in 0.31s
108 passed in 0.43s
quant-symbols-api
```

The host project install command `python3 -m pip install -e ".[dev]"` was not
usable in this runner because the available host interpreter reports Python
3.8.10 and the project requires Python `>=3.12`. For smoke validation only,
FastAPI, HTTPX, and Uvicorn were installed directly into the runner user site.
Docker CLI was present, but the Docker daemon was not reachable, so container
build/run smoke was not executed.

Cleanup after the local Uvicorn smoke is `Ctrl-C` in the server shell. No
database or container cleanup was needed in this checkout.

Known limitations for this slice:

- There are no `GET /symbols` list/search endpoints yet.
- There are no symbol detail endpoints yet.
- There are no vendor traceability endpoints yet.
- No endpoint triggers Massive/Polygon calls, sync jobs, normalization jobs,
  trading logic, or momentum logic.

## Issue 35 Slice 5 Normalize Raw Operator Command

The #35 Slice 5 operator command is implemented on the existing symbol-master
CLI surface:

```bash
python3 -m quant_symbols.cli symbols normalize-raw --latest
python3 -m quant_symbols.cli symbols normalize-raw --run-id <vendor_api_run_id>
```

The command is wired in `src/quant_symbols/_cli_impl.py` and calls
`MassiveRawNormalizeJob` in
`src/quant_symbols/symbol_master/massive_raw_normalize.py`. It does not
construct `MassiveClient`, call Massive/Polygon, fetch provider pages, create a
new vendor API run, or require `MASSIVE_API_KEY`.

Implemented behavior:

- `--latest` selects the latest successful `massive`
  `/v3/reference/tickers` vendor run that already has raw payload rows.
- `--run-id` normalizes raw payload rows for exactly the requested run id and
  the `massive` vendor source.
- each raw row is mapped through `map_massive_ticker_raw_record`
- exchange rows are written through `upsert_exchange_candidate`
- symbol and vendor identity rows are written through
  `upsert_symbol_vendor_identity_candidate`
- aliases are written through `upsert_aliases_for_massive_candidate`
- missing required symbol fields are counted as skipped/errors before
  normalized database writes are attempted
- an empty selected run prints an `ok` summary with `raw_records=0`

The command prints one summary line. Verified help output:

```text
usage: python3 -m quant_symbols.cli symbols normalize-raw [-h]
                                                          (--latest | --run-id RUN_ID)

optional arguments:
  -h, --help       show this help message and exit
  --latest
  --run-id RUN_ID
```

Summary output shape:

```text
symbols_normalize_raw=ok vendor=massive run_id=<id-or-none> raw_records=<n> symbols_inserted=<n> symbols_updated=<n> symbols_unchanged=<n> exchanges_inserted=<n> exchanges_updated=<n> exchanges_unchanged=<n> exchanges_skipped=<n> vendor_ids_inserted=<n> vendor_ids_updated=<n> vendor_ids_unchanged=<n> aliases_inserted=<n> aliases_unchanged=<n> skipped=<n> errors=<n>
```

Tables read:

- `symbol_master.vendor_sources`
- `symbol_master.vendor_api_runs`
- `symbol_master.raw_vendor_payloads`

Tables written through existing repository methods:

- `symbol_master.exchanges`
- `symbol_master.symbols`
- `symbol_master.symbol_vendor_ids`
- `symbol_master.symbol_aliases`

Focused tests live in `tests/test_symbol_master_normalize_raw.py`. They verify
CLI parser exposure, no-API-key command invocation through a fake job,
`--latest` selection, exact `--run-id` selection, orchestration through
exchange/symbol/vendor-id/alias layers, idempotent repeated normalization,
empty selected runs, and bad-row skip/error counting.

Verified commands in this checkout:

```bash
python3 -m pytest tests/test_symbol_master_normalize_raw.py -q
python3 -m pytest tests/test_symbol_master_normalization.py tests/test_symbol_master_exchange_upsert.py tests/test_symbol_master_symbol_vendor_upsert.py tests/test_symbol_master_alias_upsert.py -q
python3 -m pytest -q
python3 -m quant_symbols.cli symbols normalize-raw --help
docker compose up -d postgres
```

Observed output:

```text
8 passed in 0.04s
25 passed in 0.06s
103 passed in 0.13s
```

The `docker compose up -d postgres` command did not run in this checkout
because the current `docker-compose.yml` defines only the `quant_symbols`
service and Docker Compose returned:

```text
no such service: postgres
```

As a result, the fixture sync plus Postgres-backed `normalize-raw` verification
was not executed here. Jar verification needs either a compose file with a
`postgres` service or an externally reachable Postgres database through
`DATABASE_URL` before these DB-backed commands can be run:

```bash
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli db verify
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --max-pages 1
python3 -m quant_symbols.cli symbols normalize-raw --latest
python3 -m quant_symbols.cli symbols normalize-raw --latest
```

Cleanup after a successful Docker-backed verification is `docker compose down`,
or `docker compose down -v` if the local Postgres volume should be deleted.

## Issue 35 Slice 3 Symbol And Vendor ID Upsert

The #35 Slice 3 symbol/vendor-identity path is implemented by
`SymbolMasterRepository.upsert_symbol_vendor_identity_candidate` in
`src/quant_symbols/symbol_master/repository.py`. It accepts the Slice 1
`MassiveTickerCandidate`, the existing vendor source id, run id, raw payload id,
and an optional `primary_exchange_id` from the Slice 2 exchange upsert.

This entrypoint writes only:

- `symbol_master.symbols`
- `symbol_master.symbol_vendor_ids`

It does not call Massive/Polygon, parse new payload shapes, upsert exchanges,
insert aliases, read raw payload batches, or run a full symbol sync.

Matching behavior for this slice:

- first match an existing symbol by `composite_figi` when present
- then match through a Massive-scoped `symbol_vendor_ids.vendor_symbol`
- finally fall back to `locale + market + canonical_ticker`

The symbol row stores the normalized ticker fields from the Slice 1 candidate.
`CS` candidates store `asset_class=equity` and `security_type=common_stock`.
`ETF` candidates store `asset_class=fund` and `security_type=etf`. Slice 1
unknown asset types are stored with schema-safe `asset_class=other` while
preserving `security_type=unknown`.

The vendor identity row stores the Massive source ticker in `vendor_symbol` and
uses the candidate `composite_figi`, when present, as `vendor_asset_id`.
Repeated calls update last-seen run and payload references without creating
duplicate symbols or vendor identities.

Focused tests live in `tests/test_symbol_master_symbol_vendor_upsert.py`. They
use a fake connection abstraction because this worker validated the narrow SQL
contract without Docker/Postgres. The fake fails if this Slice 3 entrypoint
touches exchanges, aliases, raw payload rows, or vendor API runs.

Verified commands:

```bash
python3 -m pytest tests/test_symbol_master_symbol_vendor_upsert.py -q
python3 -m pytest -q
```

Observed output:

```text
6 passed
89 passed
```

This slice does not require Docker/Postgres or `MASSIVE_API_KEY`. Optional
Postgres verification for Jar from a dependency-installed checkout is:

```bash
docker compose up -d postgres
python3 -m quant_symbols.cli db upgrade
python3 -m pytest tests/test_symbol_master_symbol_vendor_upsert.py -q
python3 -m pytest -q
```

Cleanup after optional Docker validation is `docker compose down`, or
`docker compose down -v` if the local Postgres volume should be deleted.

## Issue 35 Slice 4 Alias Persistence

The #35 Slice 4 alias path is implemented by
`map_massive_alias_candidates` in
`src/quant_symbols/symbol_master/normalization.py` and
`SymbolMasterRepository.upsert_aliases_for_massive_candidate` in
`src/quant_symbols/symbol_master/repository.py`.

`map_massive_alias_candidates` accepts the Slice 1 `MassiveTickerCandidate` and
derives lookup aliases from fields already present on that candidate. The stable
alias types currently written are:

- `ticker` from the Massive source ticker
- `cik` from the candidate CIK
- `composite_figi` from the candidate composite FIGI
- `share_class_figi` from the candidate share-class FIGI

Blank or missing alias values are skipped. The mapper is pure and does not call
Massive/Polygon, touch the database, mutate the raw provider dictionary, score
quality, or decide tradability.

`SymbolMasterRepository.upsert_aliases_for_massive_candidate` writes only
`symbol_master.symbol_aliases` for an already-upserted symbol id. It selects by
active `alias_type + lower(alias_value)` and inserts the alias with
`source_vendor_id` and `source_payload_id` when missing. Repeated calls are
idempotent and count existing aliases as unchanged; they do not create duplicate
alias rows or update symbol, vendor ID, exchange, raw payload, or vendor run
tables.

Focused tests live in `tests/test_symbol_master_alias_upsert.py`. They use a
fake connection abstraction and fail if the Slice 4 entrypoint touches
non-alias symbol-master tables.

Verified commands:

```bash
python3 -m pytest tests/test_symbol_master_alias_upsert.py -q
python3 -m pytest tests/test_symbol_master_normalization.py tests/test_symbol_master_symbol_vendor_upsert.py tests/test_symbol_master_exchange_upsert.py -q
python3 -m pytest -q
```

Observed output:

```text
6 passed
19 passed
95 passed
```

This slice does not require Docker/Postgres or `MASSIVE_API_KEY`. It does not
call Massive/Polygon, run a full symbol sync, add migrations, persist symbol
rows, persist vendor IDs, or add a normalize-raw operator command. Optional
Postgres verification for Jar from a dependency-installed checkout is:

```bash
docker compose up -d postgres
python3 -m quant_symbols.cli db upgrade
python3 -m pytest tests/test_symbol_master_alias_upsert.py -q
python3 -m pytest -q
```

Cleanup after optional Docker validation is `docker compose down`, or
`docker compose down -v` if the local Postgres volume should be deleted.
