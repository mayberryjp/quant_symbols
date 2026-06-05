## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #11

### What changed
- Added symbol-master data-quality checks, persisted sync health metadata, latest health API routing, CLI quality reporting, fixture-backed tests, and documentation for Day 5 symbol quality/reporting.

### Software design impact
- Introduced a pure `data_quality` module with deterministic `QualityFinding`, active-state, and active/inactive diff helpers.
- Extended `SyncSummary` to produce a stable domain-shaped health payload and finding payload.
- Kept provider raw page structures out of API responses and CLI reports.

### Massive / Polygon integration impact
- Massive ticker-reference sync now checks duplicate canonical tickers, missing provider fields, unsupported classifications, unexpected U.S. universe values, and active/inactive transitions.
- Active/inactive diffs compare current sync candidates against raw payloads from the prior successful Massive ticker-reference run, not failed runs.

### Configuration impact
- Added `fastapi>=0.110` as a project dependency for the read-only backend endpoint.
- No API keys, credentials, or new environment variables were added.

### Code impact
- Added `GET /jobs/symbol-sync/latest` in `quant_symbols.api`.
- Added `python3 -m quant_symbols.cli symbols quality --latest`.
- Expanded `python3 -m quant_symbols.cli symbols sync-summary --latest` output with inserted, updated, unchanged, deactivated, reactivated, skipped, warned, and errored counts.
- Added Alembic revision `0002_symbol_quality_reporting` with `sync_summary` and `quality_findings` JSONB columns on `symbol_master.vendor_api_runs`.

### Files changed
- `alembic/versions/0002_symbol_quality_reporting.py`
- `pyproject.toml`
- `src/quant_symbols/api.py`
- `src/quant_symbols/_cli_impl.py`
- `src/quant_symbols/symbol_master/data_quality.py`
- `src/quant_symbols/symbol_master/massive_sync.py`
- `src/quant_symbols/symbol_master/repository.py`
- `src/quant_symbols/symbol_master/summary.py`
- `tests/test_schema_contract.py`
- `tests/test_symbol_data_quality.py`
- `tests/test_symbol_master_sync.py`
- `tests/test_symbol_sync_api.py`
- `README.md`
- `docs/codex/quant-software-developer.md`

### Documentation impact
- Updated `README.md` with the quality report command and latest-health endpoint path.
- Updated `docs/codex/quant-software-developer.md` with Day 5 quality checks, persistence behavior, CLI commands, and API contract.

### Testing / validation
- `python3 -m pytest -q` passed: 36 passed, 1 skipped.
- `python3 -m compileall -q src tests` passed.
- `python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --dry-run` passed with `records_seen=5`, `symbols_inserted=5`, `warnings=0`, `errors=0`.
- `python3 -m pip install -e '.[dev]'` could not run in editable mode because the runner pip requires `setup.py` for editable installs.
- `python3 -m pip install '.[dev]'` could not install dependencies because this runner reports Python 3.8.10 while the project requires Python >=3.12.

### Open questions
- Database-backed `symbols quality --latest`, `symbols sync-summary --latest`, and `GET /jobs/symbol-sync/latest` still need a Python >=3.12 environment with project dependencies installed and a migrated Postgres database for end-to-end service smoke validation.
