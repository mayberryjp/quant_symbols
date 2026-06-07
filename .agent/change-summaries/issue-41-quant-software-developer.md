## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #41

### What changed
- Implemented PR Slice 1 only: a small FastAPI runtime foundation with `GET /health` and `GET /ready`.
- Added a persistent supervisord API program named `quant-symbols-api`.
- Made the existing `symbols-sync` supervisor program opt-in with `autostart=false` so API-only container startup does not begin a sync loop by default.

### Software design impact
- Added `quant_symbols.api.create_app()` for dependency-injected tests and a module-level `quant_symbols.api.app:app` for Uvicorn.
- Kept database readiness lazy; importing the API module does not connect to the database or import SQLAlchemy.
- Readiness failures return JSON with HTTP 503 instead of crashing the API process.

### Massive / Polygon integration impact
- No Massive/Polygon API calls were added.
- No endpoint starts sync, normalization, ingestion, trading, or momentum behavior.
- Existing Massive sync behavior remains a supervisor-defined process but no longer autostarts by default.

### Configuration impact
- Added `fastapi`, `uvicorn[standard]`, and dev `httpx` dependencies to `pyproject.toml`.
- Reused `DATABASE_URL` for database readiness; no new database configuration variable was introduced.
- Added `API_PORT=8000` to the Dockerfile environment for the supervised API command.
- Did not add or change secrets.
- Did not add a Postgres service to `docker-compose.yml`.

### Code impact
- Added `src/quant_symbols/api/__init__.py`.
- Added `src/quant_symbols/api/app.py`.
- Added `src/quant_symbols/api/readiness.py`.
- Added `tests/test_api_app.py`.
- Updated `supervisord.conf`.
- Updated `Dockerfile`.
- Updated `pyproject.toml`.

### Files changed
- `.agent/change-summaries/issue-41-quant-software-developer.md`
- `Dockerfile`
- `docs/codex/quant-software-developer.md`
- `pyproject.toml`
- `src/quant_symbols/api/__init__.py`
- `src/quant_symbols/api/app.py`
- `src/quant_symbols/api/readiness.py`
- `supervisord.conf`
- `tests/test_api_app.py`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` with the API contract, readiness behavior, external `DATABASE_URL` verification, supervisor command, observed endpoint responses, validation commands, Docker limitation, and out-of-scope items.

### Testing / validation
- `python3 -m pytest tests/test_api_app.py -q` passed: `5 passed in 0.31s`.
- `python3 -m pytest -q` passed: `108 passed in 0.43s`.
- API import smoke passed and printed `quant-symbols-api`.
- Local Uvicorn smoke passed for `/health`: `{"status":"ok","service":"quant-symbols-api"}`.
- Local Uvicorn smoke returned expected missing-DB readiness failure for `/ready`: HTTP 503 with `{"status":"not_ready","database":"error","error":"DATABASE_URL is not configured"}`.
- `python3 -m pip install -e ".[dev]"` could not run on the host because the available interpreter reports Python 3.8.10 while the project requires Python `>=3.12`; direct dependency installs were used only for runner smoke validation.
- Docker container smoke was not run because the Docker daemon was not reachable from this runner.

### Open questions
- Jar should verify `/ready` success against an externally supplied migrated Postgres database via `DATABASE_URL`.
- Future PR slices still need symbol list/search, symbol detail, vendor traceability, and optional read-only operator status endpoints.
