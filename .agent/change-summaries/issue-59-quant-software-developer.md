## Agent Change Summary

### Agent
- Quant Software Developer

### GitHub issue
- #59

### What changed
- Added Alembic revision `0002_positions_orders` with a new `trading` schema for portfolios, positions, order intents, order events, order fills, immutable position ledger entries, and worker heartbeats.
- Added a positions/order service module with portfolio creation/listing, position reads, order-intent request validation, symbol lookup, idempotent order submission, and initial order-event persistence.
- Added Bottle routes for positions health/readiness, portfolio create/list, position list/detail/by-ticker lookup, and `POST /orders`.
- Updated database verification to expect Alembic head `0002_positions_orders` and validate both `symbol_master` and `trading` table sets.

### Software design impact
- Introduces `quant_symbols.positions.service` as the Python boundary for positions and order-management logic.
- Keeps SQLAlchemy imports lazy inside database-backed functions so importing the API app still avoids database client imports.
- Uses dependency injection in `create_app` for portfolio, position, and order handlers so API route tests can run with fake dependencies.

### Massive / Polygon integration impact
- No Massive/Polygon client behavior changed.
- Order intake resolves submitted tickers against existing normalized `symbol_master.symbols` rows when possible and preserves unresolved submitted tickers when no symbol match exists.

### Configuration impact
- No new environment variables or secrets were added.
- The new positions/order code uses the existing `DATABASE_URL` database configuration.

### Code impact
- Added migration-level uniqueness for order idempotency, resolved position identity, unresolved ticker position identity, and external fill idempotency.
- Added an append-only database trigger for `trading.position_ledger_entries`.
- Added validation for the first order-intake contract: buy/sell side, market/limit order type, required source/reason/idempotency key/ticker/portfolio, exactly one of quantity or notional, and limit-price rules.
- Did not add broker routing, live trading, order workers, reconciliation workers, or fill accounting logic in this slice.

### Files changed
- `alembic/versions/0002_positions_orders.py`
- `src/quant_symbols/_cli_impl.py`
- `src/quant_symbols/api/app.py`
- `src/quant_symbols/api/testing.py`
- `src/quant_symbols/positions/__init__.py`
- `src/quant_symbols/positions/service.py`
- `tests/test_positions_api.py`
- `tests/test_positions_schema_contract.py`
- `tests/test_schema_contract.py`
- `docs/codex/quant-software-developer.md`
- `.agent/change-summaries/issue-59-quant-software-developer.md`

### Documentation impact
- Updated `docs/codex/quant-software-developer.md` with the implemented schema, API endpoints, order-intake validation contract, idempotency rules, safety boundary, and database verification command.

### Testing / validation
- `python3 -m compileall -q src tests alembic/versions` passed.
- `python3 -m pytest -q` could not run because `pytest` is not installed in the execution environment.
- A direct API import smoke check could not run because runtime dependency `bottle` is not installed in the execution environment.
- The available interpreter is Python 3.8.10, while `pyproject.toml` declares Python 3.12+.

### Open questions
- Worker state-machine processing, fill ingestion/accounting, order read/cancel/event APIs, reconciliation checks, and supervisor process wiring remain future implementation work.
- Live broker execution remains explicitly out of scope and is not enabled by this change.
