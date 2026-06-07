## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #41

### What changed
- Implemented PR Slice 3 only: read-only symbol detail endpoints.
- Added `GET /symbols/{symbol_id}` for lookup by normalized symbol id.
- Added `GET /symbols/by-ticker/{ticker}` with `market`, `locale`, and `active` filters.
- Preserved the existing Slice 1 health/readiness runtime and Slice 2 symbol list endpoint.

### Software design impact
- Extended `create_app()` with injectable `symbol_detail` and `symbol_by_ticker` callables for DB-free endpoint tests.
- Added `SymbolTickerLookupParams` and lazy SQLAlchemy-backed repository helpers in `src/quant_symbols/api/symbols.py`.
- Reused the existing normalized symbol response shape and added detail fields from `symbol_master.symbols`: `cik`, `composite_figi`, `share_class_figi`, and `delisted_at`.
- Kept database access lazy; importing the API module and calling `/health` do not connect to the database.
- Repository failures return compact JSON without exposing a secret-bearing `DATABASE_URL`.

### Massive / Polygon integration impact
- No Massive/Polygon API calls were added.
- The new endpoints read normalized `symbol_master.symbols` rows only, with an optional left join to `symbol_master.exchanges`.
- No endpoint starts sync, normalization, ingestion, trading, or momentum behavior.
- Aliases, vendor IDs, raw payloads, and vendor runs remain out of scope for future traceability slices.

### Configuration impact
- Reused `DATABASE_URL` for database-backed symbol detail reads.
- No new environment variables or dependencies were added.
- Did not add or change secrets.
- Did not add a Postgres service to `docker-compose.yml`.
- Did not change `supervisord.conf`; the API remains the persistent `quant-symbols-api` process.

### Code impact
- Added parameterized SQLAlchemy text queries for symbol lookup by id and by case-insensitive ticker.
- `GET /symbols/{symbol_id}` returns HTTP 404 with `{"status":"not_found","error":"symbol not found"}` when missing.
- `GET /symbols/by-ticker/{ticker}` defaults to `market=stocks`, `locale=us`, and `active=true`.
- Invalid symbol id path values return FastAPI validation errors before the injected lookup callable is invoked.
- Added DB-free tests for found records, missing records, invalid id routing, by-ticker defaults and explicit filters, lowercase ticker requests, nullable primary exchange, import safety, and secret-safe repository errors.

### Files changed
- `.agent/change-summaries/issue-41-quant-software-developer.md`
- `docs/codex/quant-software-developer.md`
- `src/quant_symbols/api/app.py`
- `src/quant_symbols/api/symbols.py`
- `tests/test_api_symbol_detail.py`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` with the Slice 3 endpoint contract, supported query parameters, response examples, observed no-DB local smoke output, validation commands, external DB verification commands, and known limitations.

### Testing / validation
- `python3 -m pytest tests/test_api_symbol_detail.py -q` passed: `11 passed in 0.42s`.
- `python3 -m pytest tests/test_api_app.py tests/test_api_symbols.py tests/test_api_symbol_detail.py -q` passed: `24 passed in 0.52s`.
- `python3 -m pytest -q` passed: `127 passed in 0.71s`.
- API import smoke passed and printed `quant-symbols-api`.
- Local Uvicorn smoke command: `python3 -m uvicorn quant_symbols.api.app:app --host 127.0.0.1 --port 8000`.
- Local Uvicorn smoke passed for `/health`: `{"status":"ok","service":"quant-symbols-api"}`.
- Local Uvicorn smoke for `/symbols/1` without `DATABASE_URL` returned HTTP 500 with `{"status":"error","error":"DATABASE_URL is not configured"}`.
- Local Uvicorn smoke for `/symbols/by-ticker/AAPL` without `DATABASE_URL` returned HTTP 500 with `{"status":"error","error":"DATABASE_URL is not configured"}`.
- External DB-backed detail endpoint verification was not run because no reachable `DATABASE_URL` was supplied.
- Docker container smoke was not run for this slice.
- Cleanup for the local Uvicorn smoke was `Ctrl-C` in the Uvicorn terminal.

### Open questions
- Jar should verify the detail endpoints against an externally supplied migrated Postgres database via `DATABASE_URL` after fixture sync.
- Future PR slices still need aliases, vendor IDs, raw payloads, vendor runs, and optional read-only operator status endpoints.
