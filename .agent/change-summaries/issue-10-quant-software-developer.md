## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #10

### What changed
- Added a Day 4 Massive/Polygon symbol normalization sync slice with fixture dry-run, live client consumption, mapper, repository, summary output, tests, and CLI commands.
- Moved the CLI implementation into `src/quant_symbols/_cli_impl.py` with wrappers for both installed and checkout execution paths.

### Software design impact
- Introduced `quant_symbols.symbol_master` modules that keep vendor retrieval, pure mapping, sync orchestration, database persistence, fixture loading, and summary formatting separated.
- Kept Massive client code retrieval-only; database writes live in the symbol-master repository layer.

### Massive / Polygon integration impact
- The sync job consumes Day 3 `MassiveClient.iter_ticker_pages()` in live mode and supports fixture mode without `MASSIVE_API_KEY`.
- The mapper preserves raw provider values and maps stock, ETF, ADR, inactive, missing-name, unknown-exchange, and unknown-type records without silently dropping them.

### Configuration impact
- No new secrets were added.
- Runtime dependencies now declare Alembic, SQLAlchemy, and psycopg for database-backed CLI paths.
- Existing `DATABASE_URL` and `MASSIVE_API_KEY` patterns remain in use.

### Code impact
- Added CLI commands:
  - `python3 -m quant_symbols.cli symbols sync`
  - `python3 -m quant_symbols.cli symbols sync-summary --latest`
- Added fixture dry-run support with `--fixture` and `--dry-run`.
- Added DB-backed run lifecycle writes, append-only raw payload inserts, idempotent normalized upserts, and latest run summary retrieval.

### Files changed
- `pyproject.toml`
- `quant_symbols/__init__.py`
- `quant_symbols/cli.py`
- `src/quant_symbols/_cli_impl.py`
- `src/quant_symbols/cli.py`
- `src/quant_symbols/symbol_master/__init__.py`
- `src/quant_symbols/symbol_master/fixtures.py`
- `src/quant_symbols/symbol_master/massive_mapper.py`
- `src/quant_symbols/symbol_master/massive_sync.py`
- `src/quant_symbols/symbol_master/repository.py`
- `src/quant_symbols/symbol_master/summary.py`
- `tests/test_symbol_master_mapper.py`
- `tests/test_symbol_master_sync.py`
- `README.md`
- `docs/codex/quant-software-developer.md`
- `.agent/change-summaries/issue-10-quant-software-developer.md`

### Documentation impact
- Updated `README.md` with symbol sync commands and fixture/live usage.
- Updated `docs/codex/quant-software-developer.md` with the implemented design, mapper behavior, DB behavior, and current schema diagnostics limitation.

### Testing / validation
- Passed: `python3 -m compileall quant_symbols src tests`.
- Passed: `python3 -m quant_symbols.cli symbols sync --fixture tests/fixtures/massive --dry-run`.
- Observed dry-run counts: `pages=1 records_seen=5 raw_payloads=0 symbols_inserted=5 exchanges_inserted=3 vendor_ids_inserted=5 aliases_inserted=10 skipped=0 warnings=0 errors=0`.
- Passed: `python3 -m pytest -q` with 30 tests after installing `pytest>=8,<9` directly.
- Could not run database-backed sync in this runner because the available `python3` is 3.8.10 while the project requires Python 3.12, package install was refused, and SQLAlchemy was not installed. The command failed clearly with `SQLAlchemy is required for database-backed symbol commands`.

### Open questions
- The Day 2 schema does not have a separate raw page/request diagnostics table or request URL column. This implementation stores exact raw result payloads unchanged, request parameters on run rows, and failure messages on failed runs; fuller page diagnostics would require a schema addition.
