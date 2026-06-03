"""Massive/Polygon reference-data client."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from quant_symbols.vendors.massive.config import MassiveConfig
from quant_symbols.vendors.massive.errors import (
    MassiveAuthError,
    MassiveHTTPError,
    MassiveRateLimitError,
    MassiveServerError,
)
from quant_symbols.vendors.massive.models import RawVendorPayload, TickerReferencePage
from quant_symbols.vendors.massive.transport import Transport, UrllibTransport, decode_json_body


SleepFunc = Callable[[float], None]


class MassiveClient:
    """Retrieval-only Massive/Polygon client.

    This class performs no database writes. It isolates HTTP concerns and returns
    typed provider pages or raw payload handoff objects for later ingestion code.
    """

    def __init__(
        self,
        config: MassiveConfig,
        *,
        transport: Transport | None = None,
        sleep: SleepFunc | None = None,
    ) -> None:
        self.config = config
        self._transport = transport or UrllibTransport()
        self._sleep = sleep or time.sleep

    @classmethod
    def from_env(cls, *, transport: Transport | None = None, sleep: SleepFunc | None = None) -> "MassiveClient":
        return cls(MassiveConfig.from_env(), transport=transport, sleep=sleep)

    def iter_ticker_pages(
        self,
        *,
        ticker: str | None = None,
        market: str | None = None,
        locale: str | None = None,
        active: bool | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
    ) -> Iterator[TickerReferencePage]:
        """Yield paginated `/v3/reference/tickers` pages."""

        params: dict[str, Any] = {}
        if ticker is not None:
            params["ticker"] = ticker
        if market is not None:
            params["market"] = market
        if locale is not None:
            params["locale"] = locale
        if active is not None:
            params["active"] = str(active).lower()
        if limit is not None:
            params["limit"] = limit

        next_url: str | None = self._build_url("/v3/reference/tickers", params)
        pages_seen = 0
        while next_url:
            if max_pages is not None and pages_seen >= max_pages:
                return
            request_url = self._with_api_key(next_url)
            payload = self._request_json(request_url)
            fetched_at = datetime.now(timezone.utc)
            page = TickerReferencePage.from_payload(
                payload,
                request_url=self._redact_api_key(request_url),
                fetched_at=fetched_at,
            )
            yield page
            pages_seen += 1
            next_url = page.next_url

    def iter_ticker_payloads(self, **kwargs: Any) -> Iterator[RawVendorPayload]:
        """Yield raw ticker result payloads suitable for later persistence."""

        for page in self.iter_ticker_pages(**kwargs):
            yield from page.raw_vendor_payloads()

    def _request_json(self, url: str) -> dict[str, object]:
        max_attempts = self.config.retry_count + 1
        for attempt in range(max_attempts):
            response = self._transport.request(
                "GET",
                url,
                headers={"Accept": "application/json", "User-Agent": "quant-symbols/0.1"},
                timeout=self.config.timeout_seconds,
            )
            if 200 <= response.status_code < 300:
                return decode_json_body(response)

            body: object | None
            try:
                body = decode_json_body(response)
            except Exception:
                body = response.body.decode("utf-8", errors="replace")

            if response.status_code in (401, 403):
                raise MassiveAuthError(
                    "Massive/Polygon authentication failed",
                    status_code=response.status_code,
                    body=body,
                )

            retry_after = _retry_after_seconds(response.headers)
            if response.status_code == 429:
                if attempt < max_attempts - 1:
                    self._sleep(retry_after if retry_after is not None else self._backoff_for(attempt))
                    continue
                raise MassiveRateLimitError(
                    "Massive/Polygon rate limit exceeded",
                    status_code=response.status_code,
                    body=body,
                    retry_after_seconds=retry_after,
                )

            if 500 <= response.status_code < 600:
                if attempt < max_attempts - 1:
                    self._sleep(self._backoff_for(attempt))
                    continue
                raise MassiveServerError(
                    "Massive/Polygon server error after retries",
                    status_code=response.status_code,
                    body=body,
                )

            raise MassiveHTTPError(
                "Massive/Polygon HTTP request failed",
                status_code=response.status_code,
                body=body,
                retry_after_seconds=retry_after,
            )

        raise AssertionError("unreachable retry loop exit")

    def _build_url(self, path: str, params: Mapping[str, Any]) -> str:
        base = self.config.base_url.rstrip("/") + "/"
        url = urljoin(base, path.lstrip("/"))
        if params:
            return f"{url}?{urlencode(params)}"
        return url

    def _with_api_key(self, url: str) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["apiKey"] = self.config.api_key
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _redact_api_key(self, url: str) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if "apiKey" in query:
            query["apiKey"] = "<redacted>"
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _backoff_for(self, attempt: int) -> float:
        return self.config.backoff_seconds * (self.config.backoff_multiplier**attempt)


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    retry_after = None
    for key, value in headers.items():
        if key.lower() == "retry-after":
            retry_after = value
            break
    if retry_after is None:
        return None
    try:
        seconds = float(retry_after)
    except ValueError:
        return None
    return max(seconds, 0.0)
