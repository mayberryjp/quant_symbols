from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_symbols.vendors.massive.errors import MassiveMalformedPayloadError
from quant_symbols.vendors.massive.models import TickerReferencePage


FIXTURES = Path(__file__).parent / "fixtures" / "massive"
REQUEST_URL = "https://api.polygon.io/v3/reference/tickers?apiKey=<redacted>"


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_ticker_reference_page_parses_one_valid_ticker() -> None:
    page = TickerReferencePage.from_payload(
        {
            "status": "OK",
            "request_id": "abc",
            "count": 1,
            "results": [fixture("active_stock.json")],
        },
        request_url=REQUEST_URL,
    )

    result = page.results[0]
    assert page.status == "OK"
    assert page.request_id == "abc"
    assert page.count == 1
    assert result.ticker == "AAPL"
    assert result.name == "Apple Inc."
    assert result.market == "stocks"
    assert result.locale == "us"
    assert result.primary_exchange == "XNAS"
    assert result.type == "CS"
    assert result.active is True
    assert result.currency_name == "usd"
    assert result.cik == "0000320193"
    assert result.composite_figi == "BBG000B9XRY4"
    assert result.share_class_figi == "BBG001S5N8V8"
    assert result.last_updated_utc == "2025-05-01T00:00:00Z"
    assert result.delisted_utc is None
    assert result.raw == fixture("active_stock.json")


def test_ticker_reference_page_parses_multiple_tickers() -> None:
    page = TickerReferencePage.from_payload(
        {"results": [fixture("active_stock.json"), fixture("inactive_stock.json")]},
        request_url=REQUEST_URL,
    )

    assert [result.ticker for result in page.results] == ["AAPL", "SBNY"]
    assert page.results[1].active is False
    assert page.results[1].delisted_utc == "2023-03-13T00:00:00Z"


def test_ticker_reference_preserves_unknown_extra_fields_in_raw_payload() -> None:
    record = fixture("active_stock.json")
    record["provider_extra"] = {"kept": True}

    page = TickerReferencePage.from_payload({"results": [record]}, request_url=REQUEST_URL)

    assert page.results[0].raw["provider_extra"] == {"kept": True}


def test_ticker_reference_handles_missing_optional_fields() -> None:
    page = TickerReferencePage.from_payload(
        {"results": [{"ticker": "MSFT"}]},
        request_url=REQUEST_URL,
    )

    result = page.results[0]
    assert result.ticker == "MSFT"
    assert result.name is None
    assert result.market is None
    assert result.locale is None
    assert result.primary_exchange is None
    assert result.type is None
    assert result.active is None
    assert result.currency_name is None
    assert result.cik is None
    assert result.composite_figi is None
    assert result.share_class_figi is None
    assert result.last_updated_utc is None
    assert result.delisted_utc is None
    assert result.raw == {"ticker": "MSFT"}


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"status": "OK"},
        {"results": {"ticker": "AAPL"}},
        {"results": ["AAPL"]},
        {"results": [{}]},
    ],
)
def test_ticker_reference_page_fails_for_invalid_response_shape(payload: object) -> None:
    with pytest.raises(MassiveMalformedPayloadError):
        TickerReferencePage.from_payload(payload, request_url=REQUEST_URL)  # type: ignore[arg-type]
