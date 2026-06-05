# Day 3 Implementation Spec: Massive/Polygon Client Foundation

Date: 2026-06-03 JST
Source scope: `#gettowork Day 3 - Vendor client spike to production client`
Owner: Quant Engineering Manager
Target repo: `mayberryjp/quant_symbols`
Tracking issue: `#3`

## Objective

Implement the Massive/Polygon reference-data client that can fetch `/v3/reference/tickers` pages reliably, preserve vendor-owned payloads, and return typed records ready for Day 4 symbol normalization.

The client must stop at retrieval, validation, metadata capture, and raw record handoff. It must not normalize into canonical symbols and must not write to Postgres in this scope.

## Required Repository Changes

Add or complete these files once the Day 2 package layout exists:

```text
.
├── .env.example
├── pyproject.toml
├── src/
│   └── quant_symbols/
│       ├── cli.py
│       ├── config.py
│       ├── market_data_vendor/
│       │   ├── __init__.py
│       │   ├── errors.py
│       │   ├── http.py
│       │   └── massive/
│       │       ├── __init__.py
│       │       ├── client.py
│       │       ├── config.py
│       │       ├── dto.py
│       │       └── fixtures.py
│       └── symbol_master/
│           ├── __init__.py
│           └── vendor_payloads.py
└── tests/
    ├── fixtures/
    │   └── massive/
    │       ├── tickers_active_stock_page1.json
    │       ├── tickers_active_stock_page2.json
    │       ├── tickers_inactive_stock_page1.json
    │       ├── tickers_active_etf_page1.json
    │       ├── tickers_active_adr_page1.json
    │       ├── tickers_renamed_symbol_page1.json
    │       └── tickers_malformed_missing_results.json
    ├── test_massive_client.py
    ├── test_massive_config.py
    ├── test_massive_dto.py
    └── test_massive_dry_run.py
```

If Day 2 implementation uses a different package root, keep the existing root and preserve the same internal boundaries.

## Module Boundaries

### `market_data_vendor`

Owns vendor access concerns:

- HTTP request execution
- timeout handling
- retry/backoff policy
- rate-limit handling
- vendor-specific errors
- pagination iteration
- vendor DTO parsing

It must not import DB session helpers, Alembic code, or normalized symbol models.

### `market_data_vendor.massive`

Owns the Massive/Polygon API contract for `/v3/reference/tickers`.

Use `massive` as the internal source code because Day 2 seeds `vendor_sources.code = 'massive'`. Human-facing labels may say `Massive / Polygon`, and request metadata should preserve the configured base URL.

### `symbol_master.vendor_payloads`

Defines neutral handoff objects that Day 4 can persist into `symbol_master.vendor_api_runs` and `symbol_master.raw_vendor_payloads`.

This module may contain dataclasses or Pydantic models only. It must not write to Postgres during Day 3.

## Configuration Contract

Add environment-backed config for:

- `MASSIVE_API_KEY`
- `MASSIVE_BASE_URL`, default `https://api.polygon.io`
- `MASSIVE_TIMEOUT_SECONDS`, default `20`
- `MASSIVE_MAX_RETRIES`, default `3`
- `MASSIVE_BACKOFF_INITIAL_SECONDS`, default `0.5`
- `MASSIVE_BACKOFF_MAX_SECONDS`, default `8`
- `MASSIVE_RATE_LIMIT_SLEEP_SECONDS`, default `60`
- `MASSIVE_USER_AGENT`, default project-specific value such as `quant-symbols/0.1`

Rules:

- Missing `MASSIVE_API_KEY` must raise a typed config error for live mode.
- Fixture mode and dry-run fixture mode must not require an API key.
- Do not print or repr the API key.
- Put placeholders only in `.env.example`; never commit a real key.

## HTTP Client Contract

Prefer `httpx` for the HTTP implementation because it supports timeouts, test transports, and clear exception types. `requests` is acceptable only if the project already standardizes on it before Day 3 starts.

Expose a small vendor-neutral response wrapper from `market_data_vendor.http`:

```python
@dataclass(frozen=True)
class VendorHttpResponse:
    status_code: int
    url: str
    request_headers: Mapping[str, str]
    response_headers: Mapping[str, str]
    json_body: Mapping[str, Any]
    elapsed_ms: int | None
```

The low-level client must:

- set the configured timeout on every request
- add auth without leaking secrets into returned metadata
- retry only retryable failures
- apply exponential backoff with a configurable cap
- treat HTTP `429` as rate-limited and honor `Retry-After` when present
- raise typed errors for auth, rate limit exhausted, timeout, malformed JSON, and non-retryable HTTP failures

Retryable responses:

- HTTP `408`
- HTTP `409`
- HTTP `425`
- HTTP `429`
- HTTP `500`
- HTTP `502`
- HTTP `503`
- HTTP `504`

Non-retryable responses:

- HTTP `400`
- HTTP `401`
- HTTP `403`
- HTTP `404`
- other `4xx` responses unless explicitly configured later

## Massive Tickers API Contract

Implement a client method equivalent to:

```python
class MassiveReferenceClient:
    def iter_tickers(
        self,
        *,
        market: str = "stocks",
        active: bool | None = True,
        ticker_type: str | None = None,
        locale: str | None = "us",
        limit: int = 1000,
        sort: str | None = "ticker",
        order: str | None = "asc",
        extra_params: Mapping[str, str | int | bool] | None = None,
    ) -> Iterator[VendorTickerPage]:
        ...
```

Parameter rules:

- `active=True` discovers active listings.
- `active=False` discovers inactive or delisted listings.
- `active=None` omits the active parameter if the provider supports an all-status query.
- `ticker_type="CS"` should be usable for common stocks.
- `ticker_type="ETF"` should be usable for ETFs.
- Preserve custom `extra_params` for future provider filters, but reject collisions with explicitly supported method parameters.

Pagination rules:

- Follow the provider `next_url` until absent.
- Track page number starting at `1`.
- Use `next_url` as returned by the vendor, while still applying auth safely if the next URL omits the key.
- Stop only after yielding the final page.
- Detect repeated `next_url` values and raise a pagination error to avoid infinite loops.

## DTO Layer

Use Pydantic models if it is already in the Day 2 dependency set; otherwise use frozen dataclasses plus explicit validation. The DTO layer must isolate provider shape from normalized DB shape.

Required page DTO:

```python
@dataclass(frozen=True)
class VendorTickerPage:
    vendor_source_code: Literal["massive"]
    endpoint: Literal["/v3/reference/tickers"]
    request_url: str
    request_params: Mapping[str, Any]
    page_number: int
    status_code: int
    next_url: str | None
    count: int | None
    results: Sequence[VendorTickerRecord]
    raw_page: Mapping[str, Any]
    response_headers: Mapping[str, str]
    elapsed_ms: int | None
```

Required record DTO:

```python
@dataclass(frozen=True)
class VendorTickerRecord:
    vendor_source_code: Literal["massive"]
    endpoint: Literal["/v3/reference/tickers"]
    vendor_record_key: str
    page_number: int
    payload: Mapping[str, Any]
```

`vendor_record_key` should be the vendor ticker value for `/v3/reference/tickers`.

Record payload rules:

- Preserve the exact vendor result object in `payload`.
- Do not rename vendor fields inside the DTO payload.
- Do not derive canonical symbol fields in this layer.
- Validate that each result is an object and has a non-empty `ticker`.
- Allow inactive, ETF, ADR, renamed, delisted, and OTC-like records to pass through.

## Raw Payload Handoff Contract

Add a Day 4-ready neutral model:

```python
@dataclass(frozen=True)
class RawVendorPayloadCandidate:
    vendor_source_code: str
    endpoint: str
    vendor_record_key: str | None
    page_number: int | None
    payload: Mapping[str, Any]
    payload_hash: str
    observed_at: datetime
    request_metadata: Mapping[str, Any]
```

Hashing rules:

- `payload_hash` must be deterministic across key order changes.
- Use canonical JSON serialization with sorted keys and compact separators.
- Hash with SHA-256 and store hex digest.
- Hash the per-record vendor payload, not the whole page.

Request metadata should include:

- endpoint
- sanitized request params
- page number
- status code
- response headers useful for rate diagnostics
- elapsed milliseconds if available
- next URL presence as boolean
- vendor source code

Metadata must not include the API key.

## Fixture Capture

Add representative static fixtures under `tests/fixtures/massive/`.

Fixtures must be sanitized and small. They should preserve real provider field names, but may use synthetic tickers if necessary to avoid licensing or account leakage.

Required fixture scenarios:

- active U.S. common stock page with `next_url`
- active U.S. common stock final page without `next_url`
- inactive or delisted stock page
- active ETF page
- active ADR page
- renamed or changed-symbol style record if available from captured provider shape
- malformed page missing `results`

Each valid fixture should include at least:

- `ticker`
- `name`
- `market`
- `locale`
- `primary_exchange`
- `type`
- `active`
- `currency_name` when present
- `cik`, `composite_figi`, or `share_class_figi` when present

Do not require live fixture capture in normal test runs. If live capture tooling is added, it must be opt-in and must sanitize secrets before writing files.

## CLI Smoke Ergonomics

Implemented command source of truth:

```bash
quant-symbols-massive
MASSIVE_API_KEY=... quant-symbols-massive --live --ticker AAPL --limit 1
```

The first command is intentionally disabled and exits without a network request:

```text
live check disabled; pass --live with MASSIVE_API_KEY set
```

The live smoke command requires both `--live` and `MASSIVE_API_KEY`. It performs
one retrieval-only `/v3/reference/tickers` check through
`src/quant_symbols/vendors/massive/cli.py` and prints JSON containing the
provider status, count, request id, and ticker list. It does not write to
Postgres.

The Massive client smoke CLI does not expose `vendors massive tickers`,
`--fixture`, `--dry-run`, `--market`, or `--active`. Fixture dry-run belongs to
the Day 4 symbol normalization command:

```bash
python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --dry-run
```

The database/Alembic CLI remains a separate command family:

```bash
python3 -m quant_symbols.cli db upgrade
python3 -m quant_symbols.cli db verify
python3 -m quant_symbols.cli db downgrade-base
```

## Minimal Tests

Add tests for:

- config loads defaults from env and hides the API key in repr/error output
- live config fails when `MASSIVE_API_KEY` is missing
- fixture mode works without `MASSIVE_API_KEY`
- successful single-page parsing
- successful multi-page pagination using mocked HTTP
- `active=True`, `active=False`, and `active=None` request parameter behavior
- ETF ticker-type request parameter behavior
- retryable `500` succeeds after retry
- retryable `429` honors mocked `Retry-After`
- non-retryable `401` raises auth error
- request timeout raises typed timeout error
- repeated `next_url` raises pagination error
- malformed JSON raises typed response error
- missing `results` raises typed DTO error
- record with inactive status still yields a raw payload candidate
- payload hash is deterministic regardless of JSON key order
- retrieval-only smoke command exits zero without `--live` and does not make a network request

Use mocked HTTP transports. No default test may call the live Massive/Polygon API.

## Acceptance Criteria

- Client can iterate all ticker pages without exposing vendor payload shape to normalized symbol-master models.
- Client supports active and inactive/delisted discovery parameters.
- Client supports ETF discovery parameters without excluding leveraged, inverse, or index ETFs.
- Retry, backoff, timeout, and rate-limit settings are configurable.
- Typed DTOs preserve provider fields and isolate them from normalized DB models.
- Raw payload candidates contain enough metadata for future `vendor_api_runs` and `raw_vendor_payloads` inserts.
- Fixtures cover active stock, inactive stock, ETF, ADR, renamed-symbol style, pagination, and malformed payload cases.
- Unit tests cover pagination, retryable failure, auth/config missing, fixture parsing, DTO validation, hash determinism, and disabled smoke CLI behavior.
- Local Massive smoke command runs without a live API key and reports that live
  checks are disabled. Day 4 fixture dry-run uses `python3 -m quant_symbols.cli
  symbols sync --fixture tests/fixtures/massive --dry-run`.

## Out Of Scope

- Postgres writes.
- `vendor_api_runs` insert/update implementation.
- `raw_vendor_payloads` insert implementation.
- Normalization into `symbols` or `symbol_vendor_ids`.
- Tradability filters.
- ETF leverage/inverse/index classification.
- Daily bars, trades, quotes, aggregates, momentum algorithms, signals, frontend, or API endpoints.

## Sequencing Notes

1. Wait for Day 2 schema/package structure to be merged or reconcile with its final package names.
2. Add config and typed error classes first.
3. Add HTTP abstraction with mocked tests.
4. Add Massive `/v3/reference/tickers` DTOs and fixture parsing.
5. Add pagination and raw payload candidate generation.
6. Add a disabled-by-default Massive smoke CLI.
7. Add optional live command behavior only behind an explicit `--live` flag.

## Codex Handoff Notes

Keep the vendor client boring and explicit. The important boundary is that it returns durable raw payload records and request metadata; Day 4 will decide how to persist and normalize them.

When posting validation evidence back to the issue or channel, include:

- exact pytest command
- disabled Massive smoke command and output
- confirmation that no tests required a live API key
- confirmation that CLI output redacts or omits secrets
- any live API check only if explicitly run with `--live`
