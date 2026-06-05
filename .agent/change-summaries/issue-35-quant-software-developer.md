## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #35

### What changed
- Added Slice 2 exchange candidate mapping from `MassiveTickerCandidate`.
- Added an exchange-only repository upsert method for `symbol_master.exchanges`.
- Added focused exchange upsert tests for insert, idempotency, intended name update, missing/unknown exchange handling, and table-scope boundaries.
- Documented verified Slice 2 behavior and validation.

### Software design impact
- Introduced `MassiveExchangeCandidate` and `map_massive_exchange_candidate` as the exchange normalization layer after the Slice 1 raw ticker mapper.
- Added `ExchangeUpsertResult` and `SymbolMasterRepository.upsert_exchange_candidate` so exchange persistence can be exercised without invoking symbol, vendor ID, alias, raw payload, or run persistence.

### Massive / Polygon integration impact
- Massive/Polygon primary exchange codes from normalized ticker candidates now map to exchange row candidates.
- Known codes `XNYS`, `XNAS`, `ARCX`, `BATS`, and `OTCM` map to stable exchange names.
- Unknown nonblank exchange codes are preserved as provisional records named `Unmapped exchange <MIC>`.
- No Massive/Polygon live API calls are made.

### Configuration impact
- No new configuration was added.
- `MASSIVE_API_KEY` is not required for this slice.
- Docker/Postgres is not required for the fake-backed focused tests added in this slice.

### Code impact
- Updated `src/quant_symbols/symbol_master/normalization.py` with exchange candidate mapping.
- Updated `src/quant_symbols/symbol_master/repository.py` with an exchange-only upsert method.
- Updated `src/quant_symbols/symbol_master/__init__.py` exports.
- Added `tests/test_symbol_master_exchange_upsert.py`.

### Files changed
- `src/quant_symbols/symbol_master/normalization.py`
- `src/quant_symbols/symbol_master/repository.py`
- `src/quant_symbols/symbol_master/__init__.py`
- `tests/test_symbol_master_exchange_upsert.py`
- `docs/codex/quant-software-developer.md`
- `.agent/change-summaries/issue-35-quant-software-developer.md`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` with the verified Slice 2 exchange candidate/upsert behavior, boundaries, test commands, and optional Jar Docker/Postgres validation commands.

### Testing / validation
- `python3 -m pytest tests/test_symbol_master_exchange_upsert.py tests/test_symbol_master_normalization.py -q` passed with 13 tests.
- `python3 -m pytest -q` passed with 83 tests.
- Docker/Postgres validation was not run in this worker; the focused tests use a fake connection abstraction and guard that only `symbol_master.exchanges` is touched.

### Open questions
- Later slices still need to implement and verify symbol/vendor ID upsert, alias persistence, and a normalize-raw operator command against the existing schema.
