## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #23

### What changed
- Added explicit non-live and live Massive config loading through `MassiveConfig.from_env(require_api_key=False|True)`.
- Kept the disabled Massive smoke command unchanged.
- Added focused Massive config tests for defaults, API key handling, numeric validation, and secret redaction.

### Software design impact
- Massive settings can now be built before constructing a network client without requiring a secret for non-live checks.
- `MassiveClient.from_env()` remains the live provider path and requires `MASSIVE_API_KEY`.
- No request execution, pagination, parsing, symbol ingestion, database writes, schedulers, API endpoints, or Docker changes were added.

### Massive / Polygon integration impact
- Live Massive/Polygon access now fails early with a clear `MASSIVE_API_KEY` config error when the key is missing.
- Non-live config loading uses optional setting defaults without contacting Massive/Polygon.
- The API key is redacted from `MassiveConfig.__repr__`, and config errors do not include secret values.

### Configuration impact
- `MASSIVE_API_KEY` is required only for intentional live provider access.
- Optional config remains environment-driven with defaults for `MASSIVE_BASE_URL`, `MASSIVE_TIMEOUT_SECONDS`, `MASSIVE_RETRY_COUNT`, `MASSIVE_BACKOFF_SECONDS`, and `MASSIVE_BACKOFF_MULTIPLIER`.
- Numeric validation rejects non-numeric values, zero or negative timeout, negative retry count, negative backoff seconds, and backoff multipliers below `1`.
- No real secrets or new secret files were added.

### Code impact
- Updated `src/quant_symbols/vendors/massive/config.py` to support explicit live secret requirements and shared env parsing.
- Updated `src/quant_symbols/vendors/massive/client.py` so client construction from env requests live config.
- Updated `tests/test_massive_cli.py` for the expanded live missing-key error text.
- Added `tests/test_massive_config.py` for config-only behavior.

### Files changed
- `src/quant_symbols/vendors/massive/config.py`
- `src/quant_symbols/vendors/massive/client.py`
- `tests/test_massive_config.py`
- `tests/test_massive_cli.py`
- `docs/codex/quant-software-developer.md`
- `.agent/change-summaries/issue-23-quant-software-developer.md`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` to document that `MASSIVE_API_KEY` is required only for live access, non-live config can load without it, and secrets are redacted from repr/errors.

### Testing / validation
- `python3 -m pytest tests/test_massive_config.py tests/test_massive_cli.py -q`
- Output: `17 passed in 0.04s`
- `python3 -m pytest -q`
- Output: `47 passed in 0.10s`
- `python3 -m quant_symbols.vendors.massive.cli`
- Output: `live check disabled; pass --live with MASSIVE_API_KEY set`
- `env -u MASSIVE_API_KEY python3 -m quant_symbols.vendors.massive.cli --live`
- Exit code: `2`
- Stderr: `massive client error: MASSIVE_API_KEY is required for live Massive/Polygon access`

### Open questions
- None.
