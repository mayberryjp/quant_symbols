## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #35

### What changed
- Added a pure Massive/Polygon raw ticker payload mapper for PR Slice 1.
- Added focused tests for common stock, ETF, unknown type, missing optional fields, canonical ticker normalization, raw payload preservation, and database-free execution.
- Documented the verified Slice 1 behavior and boundaries.

### Software design impact
- Introduced `MassiveTickerCandidate` and `map_massive_ticker_raw_record` as a narrow symbol-master normalization API for one raw provider dictionary.
- The mapper is pure and does not depend on HTTP clients, SQLAlchemy, engines, sessions, or repository code.

### Massive / Polygon integration impact
- Raw Massive/Polygon ticker dictionaries can now be converted into internal candidate fields before later persistence slices.
- `CS` maps to `equity` / `common_stock`, `ETF` maps to `fund` / `etf`, and unknown provider types are preserved on the candidate while mapped to `unknown` / `unknown`.
- No live Massive/Polygon requests are made.

### Configuration impact
- No new configuration was added.
- `MASSIVE_API_KEY` is not required for this slice.

### Code impact
- Added `src/quant_symbols/symbol_master/normalization.py`.
- Exported the pure candidate and mapper from `src/quant_symbols/symbol_master/__init__.py`.
- Added `tests/test_symbol_master_normalization.py`.

### Files changed
- `src/quant_symbols/symbol_master/normalization.py`
- `src/quant_symbols/symbol_master/__init__.py`
- `tests/test_symbol_master_normalization.py`
- `docs/codex/quant-software-developer.md`
- `.agent/change-summaries/issue-35-quant-software-developer.md`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` with the verified Slice 1 raw payload normalization behavior, type mappings, validation commands, and explicit non-database/non-live boundaries.

### Testing / validation
- `python3 -m pytest tests/test_symbol_master_normalization.py -q` passed with 7 tests.
- `python3 -m pytest tests/test_symbol_master_mapper.py -q` passed with 8 tests.
- `python3 -m pytest -q` passed with 77 tests.

### Open questions
- Later slices still need to define and verify exchange upsert, symbol/vendor ID upsert, alias persistence, and a normalize-raw operator command against the existing schema.
