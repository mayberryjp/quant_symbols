# Quant Software Developer Notes

## Massive/Polygon Vendor Client

The repository now includes a retrieval-only Massive/Polygon vendor module under
`src/quant_symbols/vendors/massive/`.

The module owns:

- environment-based client configuration
- HTTP timeout, retry, exponential backoff, and `Retry-After` rate-limit handling
- typed models for `/v3/reference/tickers` pages and ticker results
- raw provider payload handoff objects for later ingestion code
- a disabled-by-default manual live-check CLI

The module does not write to Postgres and does not normalize payloads into symbol
master tables. Later ingestion code should call `MassiveClient.iter_ticker_pages`
or `MassiveClient.iter_ticker_payloads` and decide how to create vendor run
records and raw payload rows.

## Configuration

Required:

- `MASSIVE_API_KEY`

Optional:

- `MASSIVE_BASE_URL`, default `https://api.polygon.io`
- `MASSIVE_TIMEOUT_SECONDS`, default `30`
- `MASSIVE_RETRY_COUNT`, default `3`
- `MASSIVE_BACKOFF_SECONDS`, default `0.5`
- `MASSIVE_BACKOFF_MULTIPLIER`, default `2`

Do not commit real API keys. `.env.example` contains placeholders only.

## Usage

Instantiate from environment:

```python
from quant_symbols.vendors.massive import MassiveClient

client = MassiveClient.from_env()
for payload in client.iter_ticker_payloads(market="stocks", locale="us", active=True, limit=1000):
    print(payload.provider_id, payload.payload)
```

Manual live check is disabled unless explicitly enabled:

```bash
quant-symbols-massive
MASSIVE_API_KEY=... quant-symbols-massive --live --ticker AAPL --limit 1
```

Normal tests use mocked HTTP responses and do not require a live Massive/Polygon
API key.
