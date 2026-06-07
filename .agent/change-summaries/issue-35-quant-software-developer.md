## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #35

### What changed
- Added the `symbols normalize-raw` operator command for normalizing already-stored Massive raw ticker payload rows by latest successful run or explicit run id.
- Added a narrow normalization job that maps raw rows through the existing Massive mapper and writes through the existing exchange, symbol/vendor ID, and alias repository methods.
- Added repository read helpers for latest successful Massive ticker runs with raw payloads and raw payload rows for a selected run.
- Added focused tests for CLI exposure, run selection, orchestration, idempotency, empty runs, and bad-row skip/error counting.

### Software design impact
- Keeps raw-run normalization in `symbol_master` and separate from live provider fetching.
- Reuses the already-tested mapper and upsert layers instead of adding a broader sync workflow.
- Adds a dedicated summary formatter for the normalize-raw command without changing existing `symbols sync` output.

### Massive / Polygon integration impact
- The new command does not construct `MassiveClient`, does not call Massive/Polygon, does not fetch pages, and does not require `MASSIVE_API_KEY`.
- It only reads Massive raw payload rows already stored in `symbol_master.raw_vendor_payloads`.

### Configuration impact
- No new configuration variables were added.
- Existing `DATABASE_URL` behavior is used for the database-backed CLI command.
- `MASSIVE_API_KEY` is not required for this command.

### Code impact
- `src/quant_symbols/_cli_impl.py` now exposes `python3 -m quant_symbols.cli symbols normalize-raw --latest` and `--run-id <vendor_api_run_id>`.
- `src/quant_symbols/symbol_master/massive_raw_normalize.py` implements the DB-backed orchestration job and summary counters.
- `src/quant_symbols/symbol_master/repository.py` includes read helpers for selected raw runs and raw payload rows.

### Files changed
- `src/quant_symbols/_cli_impl.py`
- `src/quant_symbols/symbol_master/massive_raw_normalize.py`
- `src/quant_symbols/symbol_master/repository.py`
- `tests/test_symbol_master_normalize_raw.py`
- `docs/codex/quant-software-developer.md`
- `.agent/change-summaries/issue-35-quant-software-developer.md`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` with the verified command path, help output, summary shape, tables read/written, tests run, and the Docker/Postgres verification blocker observed in this checkout.

### Testing / validation
- `python3 -m pytest tests/test_symbol_master_normalize_raw.py -q` passed with `8 passed in 0.04s`.
- `python3 -m pytest tests/test_symbol_master_normalization.py tests/test_symbol_master_exchange_upsert.py tests/test_symbol_master_symbol_vendor_upsert.py tests/test_symbol_master_alias_upsert.py -q` passed with `25 passed in 0.06s`.
- `python3 -m pytest -q` passed with `103 passed in 0.13s`.
- `python3 -m quant_symbols.cli symbols normalize-raw --help` printed the implemented `--latest` / `--run-id` command surface.
- `docker compose up -d postgres` could not run because the current `docker-compose.yml` has no `postgres` service and Docker Compose returned `no such service: postgres`.

### Open questions
- The requested Docker/Postgres fixture verification still needs a repository compose service named `postgres` or an externally configured Postgres database through `DATABASE_URL`.
