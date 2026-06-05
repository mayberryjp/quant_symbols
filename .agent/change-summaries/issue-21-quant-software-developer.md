## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #21

### What changed
- Repaired the Massive/Polygon smoke CLI so the repo-visible command remains disabled by default and exposes only the `--live` flag.
- Added focused tests for the disabled default path, missing-key live failure, and help output.
- Updated Quant Software Developer documentation to match the verified smoke command and live-check surface.

### Software design impact
- The smoke CLI remains a small module entry point under `quant_symbols.vendors.massive.cli`.
- Default execution returns before constructing `MassiveClient` or reading Massive configuration.
- No symbol ingestion, database writes, API endpoints, schedulers, or Docker behavior were added.

### Massive / Polygon integration impact
- Default mode does not make a Massive/Polygon request.
- Live mode remains available only behind `--live` and performs a single AAPL ticker page request with fixed smoke-check parameters.
- The smoke command no longer documents or accepts ad hoc `--ticker` or `--limit` CLI flags.

### Configuration impact
- No new configuration variables were added.
- Default mode does not require `MASSIVE_API_KEY`.
- Live mode fails clearly when `MASSIVE_API_KEY` is missing with `massive client error: MASSIVE_API_KEY is required`.

### Code impact
- Updated `src/quant_symbols/vendors/massive/cli.py` to keep only the `--live` command-line flag.
- Added `tests/test_massive_cli.py` for smoke-command behavior.
- Did not modify Alembic migrations, database setup, Docker files, secrets, credentials, workflows, or runner config.

### Files changed
- `src/quant_symbols/vendors/massive/cli.py`
- `tests/test_massive_cli.py`
- `docs/codex/quant-software-developer.md`
- `.agent/change-summaries/issue-21-quant-software-developer.md`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` to show `python3 -m quant_symbols.vendors.massive.cli` and `python3 -m quant_symbols.vendors.massive.cli --help` as verification commands.
- Documented that optional live validation uses `MASSIVE_API_KEY=... python3 -m quant_symbols.vendors.massive.cli --live`.
- Documented that the smoke CLI does not implement `--ticker`, `--limit`, `--fixture`, `--dry-run`, `--market`, or `--active`.

### Testing / validation
- Passed: `python3 -m quant_symbols.vendors.massive.cli`
- Output: `live check disabled; pass --live with MASSIVE_API_KEY set`
- Passed: `python3 -m quant_symbols.vendors.massive.cli --help`
- Output:
  ```text
  usage: cli.py [-h] [--live]

  Massive/Polygon reference-data utilities

  optional arguments:
    -h, --help  show this help message and exit
    --live      allow a real Massive/Polygon API request; disabled by default
  ```
- Passed: `python3 -m pytest -q`
- Output: `33 passed in 0.07s`
- Verified missing-key live mode with `env -u MASSIVE_API_KEY python3 -m quant_symbols.vendors.massive.cli --live`; it exited 2 and printed `massive client error: MASSIVE_API_KEY is required`.
- Docker/Postgres was not required for any validation command.

### Open questions
- None.
