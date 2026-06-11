# Copilot Instructions

## Build & Test

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_massive_client.py

# Run a single test by name
pytest tests/test_massive_client.py::test_client_success_preserves_provider_fields_and_raw_payload

# Database smoke (requires Docker Postgres running)
docker compose up -d postgres
python -m quant_symbols.cli db upgrade
python -m quant_symbols.cli db verify
```

No linter or formatter is configured in the project.

## Architecture

This is the **symbol repository and vendor-access foundation** for a quant momentum pipeline. Two packages live under `src/`:

- **`quant_symbols`** — Symbol master domain: vendor clients, REST API, sync orchestration, CLI.
- **`quant_pipeline`** — Pipeline infrastructure (smoke tests, future orchestration).

### Vendor Client Pattern (`src/quant_symbols/vendors/massive/`)

Vendor clients follow a strict layered design:

1. **`config.py`** — Dataclass config loaded from env vars; secrets are redacted in `__repr__`.
2. **`transport.py`** — Thin HTTP abstraction (`Transport` protocol + `UrllibTransport`). Returns `TransportResponse` (status, headers, body bytes).
3. **`errors.py`** — Structured error hierarchy (`MassiveAuthError`, `MassiveRateLimitError`, `MassiveServerError`, `MassiveTimeoutError`, `MassiveMalformedPayloadError`).
4. **`models.py`** — Frozen dataclasses for typed responses. Each result preserves the full `raw` JSON dict for traceability.
5. **`client.py`** — Orchestrates pagination, retry/backoff, rate-limit handling. Returns typed pages via `iter_ticker_pages()`. **Performs no database writes.**
6. **`cli.py`** — Entry point registered as `quant-symbols-massive` console script.

Key design rules:
- Vendor clients are **retrieval-only** — no Postgres writes happen inside vendor code.
- The `Transport` dependency is injectable for testing (use `FakeTransport` in tests).
- The `sleep` function is injectable for deterministic retry tests.
- Raw vendor payloads produce `RawVendorPayload` handoff objects for later ingestion code.

### Symbol Master Domain (`src/quant_symbols/symbol_master/`)

This is the ingestion and normalization layer that sits between vendor data and the database:

- **`massive_sync.py`** — `MassiveSymbolSyncJob` orchestrates end-to-end sync (fetch → normalize → upsert). Supports fixture-based replay, dry-run mode, and page limits.
- **`repository.py`** — `SymbolMasterRepository` handles all DB writes (raw payload storage, exchange upsert, symbol/vendor-identity upsert, alias upsert). Returns frozen result dataclasses.
- **`massive_mapper.py`** — Maps raw Polygon ticker JSON into typed `SymbolCandidate`, `ExchangeCandidate`, `AliasCandidate` dataclasses.
- **`normalization.py`** / **`massive_raw_normalize.py`** — Secondary normalization for raw payloads already stored.
- **`fixtures.py`** — Loads fixture pages from disk for offline testing and replay.

### REST API (`src/quant_symbols/api/`)

Bottle app created via `create_app()` factory in `app.py`. All handler dependencies are **injectable callables** (same pattern as the vendor transport), making tests fast and DB-free.

Endpoints cover: health/readiness, symbol listing/detail/lookup-by-ticker, symbol aliases, vendor identities, raw payloads, vendor runs, and sync status.

Run locally: `python3 -m quant_symbols.api.app` (reads `API_PORT` from env, default 8000)

### Database & Migrations

- Postgres 16 via Docker Compose; schemas: `symbol_master`, `market_data`, `signals`.
- Migrations managed by Alembic (config in `alembic.ini`, scripts in `alembic/versions/`).
- CLI entrypoint: `python -m quant_symbols.cli db {upgrade|verify|downgrade-base}`.
- `raw_vendor_payloads` is append-only; inactive symbols are preserved (no survivorship bias).

### Deployment

- Docker image based on `python:3.12-slim`; runs via `supervisord` (API + scheduled sync).
- Env vars: `API_PORT` (default 8000), `SYNC_INTERVAL` (default 86400s).

### CI / Agent Workflows

GitHub Actions workflows in `.github/workflows/` dispatch work to self-hosted runners triggered by issue labels (e.g., `quant_database_engineer_delegated`). These are Codex-agent-based automation pipelines.

## Conventions

- Python 3.12+; use `from __future__ import annotations` in all modules.
- Data models are frozen dataclasses (not Pydantic).
- Tests use fixture JSON files in `tests/fixtures/` and fake transport objects — no live API calls in normal test runs.
- Config is always loaded from environment variables; never hardcode credentials.
- The vendor name "Massive" is the internal alias for the Polygon.io data provider.
- Bottle handlers use injectable callable dependencies; this allows tests to pass fake implementations directly to `create_app()`.
- Repository classes accept a SQLAlchemy engine/connection; they never create their own connections.
