from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from quant_symbols.vendors.massive import MassiveClient, MassiveConfig
from quant_symbols.vendors.massive.errors import (
    MassiveAuthError,
    MassiveHTTPError,
    MassiveMalformedPayloadError,
    MassiveRateLimitError,
    MassiveServerError,
    MassiveTimeoutError,
)
from quant_symbols.vendors.massive.models import TickerReferencePage
from quant_symbols.vendors.massive.transport import TransportResponse


FIXTURES = Path(__file__).parent / "fixtures" / "massive"


class FakeTransport:
    def __init__(self, responses: list[TransportResponse] | None = None, *, raise_timeout: bool = False) -> None:
        self.responses = list(responses or [])
        self.raise_timeout = raise_timeout
        self.requests: list[dict[str, object]] = []
        self.urls: list[str] = []

    def request(self, method: str, url: str, *, headers: dict[str, str], timeout: float) -> TransportResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        self.urls.append(url)
        if self.raise_timeout:
            raise MassiveTimeoutError("timeout")
        if not self.responses:
            raise AssertionError("no fake response queued")
        return self.responses.pop(0)


def response(status_code: int, payload: object, headers: dict[str, str] | None = None) -> TransportResponse:
    return TransportResponse(
        status_code=status_code,
        headers=headers or {},
        body=json.dumps(payload).encode("utf-8"),
    )


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def config(**kwargs: object) -> MassiveConfig:
    values = {
        "api_key": "test-key",
        "base_url": "https://api.polygon.io",
        "timeout_seconds": 1.0,
        "retry_count": 2,
        "backoff_seconds": 0.1,
        "backoff_multiplier": 2.0,
    }
    values.update(kwargs)
    return MassiveConfig(**values)


def test_get_ticker_reference_page_sends_one_expected_request(capsys: pytest.CaptureFixture[str]) -> None:
    payload = {"status": "OK", "request_id": "abc", "count": 0, "results": []}
    transport = FakeTransport([response(200, payload)])
    client = MassiveClient(config(), transport=transport, sleep=lambda _: None)

    returned = client.get_ticker_reference_page(ticker="AAPL", limit=1)

    assert returned == payload
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request["method"] == "GET"
    assert request["headers"] == {"Accept": "application/json", "User-Agent": "quant-symbols/0.1"}
    assert request["timeout"] == 1.0

    parsed = urlparse(str(request["url"]))
    query = parse_qs(parsed.query)
    assert parsed.path == "/v3/reference/tickers"
    assert query["apiKey"] == ["test-key"]
    assert query["ticker"] == ["AAPL"]
    assert query["limit"] == ["1"]
    assert "test-key" not in str(request["headers"])
    assert "test-key" not in repr(client.config)
    captured = capsys.readouterr()
    assert "test-key" not in captured.out
    assert "test-key" not in captured.err


def test_get_ticker_reference_page_can_send_market_and_locale() -> None:
    payload = {"status": "OK", "results": []}
    transport = FakeTransport([response(200, payload)])
    client = MassiveClient(config(), transport=transport, sleep=lambda _: None)

    returned = client.get_ticker_reference_page(market="stocks", locale="us", limit=5)

    parsed = urlparse(transport.urls[0])
    query = parse_qs(parsed.query)
    assert returned == payload
    assert len(transport.requests) == 1
    assert query["market"] == ["stocks"]
    assert query["locale"] == ["us"]
    assert query["limit"] == ["5"]


def test_get_ticker_reference_page_raises_existing_http_error_for_failure() -> None:
    transport = FakeTransport([response(400, {"status": "ERROR", "error": "bad request"})])
    client = MassiveClient(config(), transport=transport, sleep=lambda _: None)

    with pytest.raises(MassiveHTTPError) as exc_info:
        client.get_ticker_reference_page(ticker="AAPL", limit=1)

    assert exc_info.value.status_code == 400
    assert len(transport.requests) == 1


def test_client_success_preserves_provider_fields_and_raw_payload() -> None:
    payload = {
        "status": "OK",
        "request_id": "abc",
        "count": 1,
        "results": [fixture("active_stock.json")],
    }
    transport = FakeTransport([response(200, payload)])
    client = MassiveClient(config(), transport=transport, sleep=lambda _: None)

    page = next(client.iter_ticker_pages(ticker="AAPL", limit=1))

    assert page.status == "OK"
    assert page.request_id == "abc"
    assert page.results[0].ticker == "AAPL"
    assert page.results[0].composite_figi == "BBG000B9XRY4"
    assert page.results[0].raw["primary_exchange"] == "XNAS"
    assert page.raw_vendor_payloads()[0].vendor == "massive"
    assert page.raw_vendor_payloads()[0].payload["ticker"] == "AAPL"
    assert "test-key" not in page.request_url
    assert parse_qs(urlparse(transport.urls[0]).query)["apiKey"] == ["test-key"]


@pytest.mark.parametrize(
    "fixture_name,expected_ticker,expected_type",
    [
        ("active_stock.json", "AAPL", "CS"),
        ("inactive_stock.json", "SBNY", "CS"),
        ("etf.json", "SPY", "ETF"),
        ("adr.json", "BABA", "ADRC"),
        ("renamed_symbol.json", "META", "CS"),
    ],
)
def test_representative_ticker_fixtures(fixture_name: str, expected_ticker: str, expected_type: str) -> None:
    transport = FakeTransport([response(200, {"results": [fixture(fixture_name)]})])
    client = MassiveClient(config(), transport=transport, sleep=lambda _: None)

    page = next(client.iter_ticker_pages(limit=1))

    assert page.results[0].ticker == expected_ticker
    assert page.results[0].type == expected_type
    assert page.results[0].raw == fixture(fixture_name)


def test_auth_failure_raises_structured_error_without_retry() -> None:
    transport = FakeTransport([response(401, {"status": "ERROR", "error": "invalid api key"})])
    client = MassiveClient(config(), transport=transport, sleep=lambda _: None)

    with pytest.raises(MassiveAuthError) as exc_info:
        list(client.iter_ticker_pages(limit=1))

    assert exc_info.value.status_code == 401
    assert len(transport.urls) == 1


def test_rate_limit_retries_then_raises_with_retry_after() -> None:
    sleeps: list[float] = []
    transport = FakeTransport(
        [
            response(429, {"status": "ERROR"}, {"Retry-After": "3"}),
            response(429, {"status": "ERROR"}, {"Retry-After": "3"}),
            response(429, {"status": "ERROR"}, {"Retry-After": "3"}),
        ]
    )
    client = MassiveClient(config(retry_count=2), transport=transport, sleep=sleeps.append)

    with pytest.raises(MassiveRateLimitError) as exc_info:
        list(client.iter_ticker_pages(limit=1))

    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 3
    assert sleeps == [3, 3]


def test_retryable_server_error_retries_and_succeeds() -> None:
    sleeps: list[float] = []
    transport = FakeTransport(
        [
            response(500, {"status": "ERROR"}),
            response(502, {"status": "ERROR"}),
            response(200, {"results": [fixture("etf.json")]}),
        ]
    )
    client = MassiveClient(config(retry_count=2), transport=transport, sleep=sleeps.append)

    page = next(client.iter_ticker_pages(limit=1))

    assert page.results[0].ticker == "SPY"
    assert sleeps == [0.1, 0.2]


def test_retryable_server_error_raises_after_retries() -> None:
    transport = FakeTransport(
        [
            response(500, {"status": "ERROR"}),
            response(500, {"status": "ERROR"}),
            response(500, {"status": "ERROR"}),
        ]
    )
    client = MassiveClient(config(retry_count=2), transport=transport, sleep=lambda _: None)

    with pytest.raises(MassiveServerError):
        list(client.iter_ticker_pages(limit=1))


def test_timeout_error_is_propagated() -> None:
    client = MassiveClient(config(), transport=FakeTransport(raise_timeout=True), sleep=lambda _: None)

    with pytest.raises(MassiveTimeoutError):
        list(client.iter_ticker_pages(limit=1))


def test_pagination_follows_next_url_and_adds_api_key() -> None:
    first_page = {
        "results": [fixture("active_stock.json")],
        "next_url": "https://api.polygon.io/v3/reference/tickers?cursor=next",
    }
    second_page = {"results": [fixture("inactive_stock.json")]}
    transport = FakeTransport([response(200, first_page), response(200, second_page)])
    client = MassiveClient(config(), transport=transport, sleep=lambda _: None)

    pages = list(client.iter_ticker_pages(limit=1))

    assert [page.results[0].ticker for page in pages] == ["AAPL", "SBNY"]
    assert parse_qs(urlparse(transport.urls[1]).query)["apiKey"] == ["test-key"]
    assert parse_qs(urlparse(transport.urls[1]).query)["cursor"] == ["next"]


def test_malformed_payload_missing_results_raises() -> None:
    transport = FakeTransport([response(200, {"status": "OK"})])
    client = MassiveClient(config(), transport=transport, sleep=lambda _: None)

    with pytest.raises(MassiveMalformedPayloadError):
        list(client.iter_ticker_pages(limit=1))


def test_config_from_env_redacts_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASSIVE_API_KEY", "secret")
    monkeypatch.setenv("MASSIVE_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("MASSIVE_RETRY_COUNT", "4")
    monkeypatch.setenv("MASSIVE_BACKOFF_SECONDS", "0.25")
    monkeypatch.setenv("MASSIVE_BACKOFF_MULTIPLIER", "3")

    loaded = MassiveConfig.from_env()

    assert loaded.api_key == "secret"
    assert loaded.timeout_seconds == 2.5
    assert loaded.retry_count == 4
    assert "secret" not in repr(loaded)


def test_ticker_page_model_sets_default_fetch_time() -> None:
    page = TickerReferencePage.from_payload(
        {"results": [fixture("active_stock.json")]},
        request_url="https://api.polygon.io/v3/reference/tickers?apiKey=<redacted>",
    )

    assert page.fetched_at is not None
    assert page.fetched_at.tzinfo is not None
