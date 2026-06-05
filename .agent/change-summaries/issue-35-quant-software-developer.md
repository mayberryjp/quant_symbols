## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #35

### What changed
- Added Slice 3 symbol and Massive vendor identifier upsert behavior for one `MassiveTickerCandidate`.
- Added focused tests for symbol insert, vendor ID insert, idempotent repeated upsert, composite FIGI matching, vendor-symbol matching, unknown type fallback, and table-scope boundaries.
- Documented the verified Slice 3 behavior and Jar validation commands.

### Software design impact
- Added `SymbolVendorIdentityUpsertResult` and `SymbolMasterRepository.upsert_symbol_vendor_identity_candidate`.
- The new repository entrypoint is intentionally one-candidate-at-a-time and scoped to symbol/vendor identity persistence.
- Matching order is composite FIGI, then Massive-scoped vendor symbol, then `locale + market + canonical_ticker` fallback.

### Massive / Polygon integration impact
- Uses the existing Slice 1 Massive ticker candidate as input.
- Stores the Massive source ticker as `symbol_vendor_ids.vendor_symbol`.
- Stores `composite_figi` as `symbol_vendor_ids.vendor_asset_id` when present.
- Does not call Massive/Polygon, fetch provider data, parse new payload shapes, or run a full symbol sync.

### Configuration impact
- No new configuration was added.
- `MASSIVE_API_KEY` is not required.
- Docker/Postgres is not required for the focused fake-backed tests added in this slice.

### Code impact
- Updated `src/quant_symbols/symbol_master/repository.py` with symbol/vendor identity upsert logic and schema-safe candidate value conversion.
- Added `tests/test_symbol_master_symbol_vendor_upsert.py`.
- Unknown Slice 1 asset types are stored with schema-safe `asset_class=other` and `security_type=unknown`.

### Files changed
- `src/quant_symbols/symbol_master/repository.py`
- `tests/test_symbol_master_symbol_vendor_upsert.py`
- `docs/codex/quant-software-developer.md`
- `.agent/change-summaries/issue-35-quant-software-developer.md`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` with the verified Slice 3 method, table scope, matching order, type fallback behavior, test commands, and optional Docker/Postgres validation commands.

### Testing / validation
- `python3 -m pytest tests/test_symbol_master_symbol_vendor_upsert.py -q` passed with 6 tests.
- `python3 -m pytest -q` passed with 89 tests.
- Docker/Postgres validation was not run; the focused tests use a fake connection and guard that this Slice 3 entrypoint only touches `symbol_master.symbols` and `symbol_master.symbol_vendor_ids`.

### Open questions
- Later slices still need alias persistence and a normalize-raw operator command.
