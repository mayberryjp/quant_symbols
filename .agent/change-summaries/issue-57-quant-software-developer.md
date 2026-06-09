## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #57

### What changed
- Added a Postgres-backed signal intake and watchlist pipeline with schema, Python domain models, repository methods, API routes, a processing worker, tests, and documentation.

### Software design impact
- Introduced `quant_symbols.signal_pipeline` as a separate package for signal/watchlist domain validation, database access, and worker processing.
- Kept API request parsing in `quant_symbols.api.app` and database behavior behind repository functions.
- Preserved submitted ticker strings while using normalized `symbol_master.symbols.id` as the preferred watchlist identity when resolution succeeds.

### Massive / Polygon integration impact
- Signal intake does not call Massive/Polygon or any external vendor.
- The worker resolves against existing normalized symbol master tables populated by the existing Massive/Polygon symbol pipeline.

### Configuration impact
- Added optional worker tuning variables to `.env.example`: `SIGNAL_WORKER_NAME`, `SIGNAL_WORKER_BATCH_SIZE`, and `SIGNAL_WORKER_POLL_SECONDS`.
- No API keys, credentials, or secret values were added.
- `DATABASE_URL` remains the database access configuration.

### Code impact
- Added Alembic revision `0002_signal_watchlist_pipeline`.
- Added signal source, signal event, watchlist entry, and worker heartbeat repository behavior.
- Added `python3 -m quant_symbols.cli signals worker` and a `signal-watchlist-worker` supervisor program.
- Added signal pipeline and watchlist API routes.

### Files changed
- `.env.example`
- `.agent/change-summaries/issue-57-quant-software-developer.md`
- `alembic/versions/0002_signal_watchlist_pipeline.py`
- `docs/codex/quant-software-developer.md`
- `src/quant_symbols/_cli_impl.py`
- `src/quant_symbols/api/app.py`
- `src/quant_symbols/api/readiness.py`
- `src/quant_symbols/api/signal_pipeline.py`
- `src/quant_symbols/api/testing.py`
- `src/quant_symbols/signal_pipeline/__init__.py`
- `src/quant_symbols/signal_pipeline/models.py`
- `src/quant_symbols/signal_pipeline/repository.py`
- `src/quant_symbols/signal_pipeline/worker.py`
- `supervisord.conf`
- `tests/test_api_app.py`
- `tests/test_api_signal_pipeline.py`
- `tests/test_schema_contract.py`
- `tests/test_signal_pipeline_repository_worker.py`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` with the signal/watchlist schema contract, API contract, worker command, supervisor process name, identity model, operational checks, and known Kafka deferral limitation.

### Testing / validation
- Added tests for API validation and routing, schema contract text, duplicate-safe signal repository behavior, payload validation limits, and worker accepted/failed paths.
- `git diff --check` passed.
- Focused pytest command could not run because the container only has Python 3.8.10, while `pyproject.toml` requires Python >=3.12 and pytest is not installed for the available interpreter.

### Open questions
- No auth/permissions model was added because the issue explicitly left auth beyond existing project pattern out of scope.
- The implementation assumes `symbol_master.symbols` and `symbol_master.symbol_aliases` are the normalized symbol resolution sources.
