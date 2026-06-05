# Quant Software Developer Notes

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
