## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #55

### What changed
- Added a read-only `GET /symbols/count` API route that returns an aggregate `total` and the applied symbol filters.
- Added `SymbolCountParams` and `count_symbols` beside the existing symbol list repository code.
- Added tests for count route defaults, supported filters, blank text query normalization, pagination-parameter rejection, list page-count preservation, repository error redaction, and count SQL filter behavior.

### Software design impact
- The count endpoint uses the existing Bottle application factory dependency-injection pattern.
- Symbol list and symbol count now share optional filter SQL/value helpers so active, market, locale, and ticker/name text-search behavior stay aligned.

### Massive / Polygon integration impact
- No Massive/Polygon client behavior changed.
- The new endpoint reads only from `symbol_master.symbols` and does not trigger vendor calls, sync jobs, normalization jobs, or write behavior.

### Configuration impact
- No new configuration was added.
- The repository function uses the existing `DATABASE_URL` environment variable pattern.

### Code impact
- `src/quant_symbols/api/symbols.py` now includes the count params model, count repository function, and shared filter query helpers.
- `src/quant_symbols/api/app.py` now accepts an injected `symbol_count` function and registers `/symbols/count` before dynamic symbol-id routes.
- `tests/test_api_symbols.py` now covers the count endpoint and repository SQL behavior.

### Files changed
- `src/quant_symbols/api/symbols.py`
- `src/quant_symbols/api/app.py`
- `tests/test_api_symbols.py`
- `docs/codex/quant-software-developer.md`
- `.agent/change-summaries/issue-55-quant-software-developer.md`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` with the endpoint shape, supported filters, repository design, route ordering note, and read-only behavior.

### Testing / validation
- `python3 -m compileall src tests` passed.
- `python3 -m pytest tests/test_api_symbols.py -q` could not run because `pytest` is not installed in the runner.
- Runtime route smoke checks could not run because `bottle`, `webtest`, and `sqlalchemy` are not installed in the runner.

### Open questions
- None.
