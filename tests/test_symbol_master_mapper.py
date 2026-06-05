from __future__ import annotations

from quant_symbols.symbol_master.massive_mapper import map_ticker_reference
from quant_symbols.vendors.massive.models import TickerReference


def ref(**overrides: object) -> TickerReference:
    payload = {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "market": "stocks",
        "locale": "us",
        "primary_exchange": "XNAS",
        "type": "CS",
        "active": True,
        "currency_name": "usd",
        "cik": "0000320193",
        "composite_figi": "BBG000B9XRY4",
        "share_class_figi": "BBG001S5N8V8",
    }
    payload.update(overrides)
    return TickerReference.from_payload(payload)


def test_mapper_preserves_active_common_stock_fields() -> None:
    mapped = map_ticker_reference(ref())

    assert mapped.candidate is not None
    assert mapped.candidate.canonical_ticker == "AAPL"
    assert mapped.candidate.name == "Apple Inc."
    assert mapped.candidate.market == "stocks"
    assert mapped.candidate.locale == "us"
    assert mapped.candidate.currency == "USD"
    assert mapped.candidate.primary_exchange is not None
    assert mapped.candidate.primary_exchange.mic == "XNAS"
    assert mapped.candidate.asset_class == "equity"
    assert mapped.candidate.security_type == "common_stock"
    assert mapped.candidate.active is True
    assert {alias.alias_type for alias in mapped.candidate.aliases} == {
        "composite_figi",
        "share_class_figi",
    }


def test_mapper_preserves_inactive_delisted_stock() -> None:
    mapped = map_ticker_reference(
        ref(ticker="SBNY", active=False, delisted_utc="2023-03-13T00:00:00Z")
    )

    assert mapped.candidate is not None
    assert mapped.candidate.active is False
    assert mapped.candidate.delisted_at is not None


def test_mapper_maps_etf_to_fund_security_type() -> None:
    mapped = map_ticker_reference(ref(ticker="SPY", type="ETF"))

    assert mapped.candidate is not None
    assert mapped.candidate.asset_class == "fund"
    assert mapped.candidate.security_type == "etf"


def test_mapper_preserves_adr_without_dropping() -> None:
    mapped = map_ticker_reference(ref(ticker="BABA", type="ADRC"))

    assert mapped.candidate is not None
    assert mapped.candidate.asset_class == "equity"
    assert mapped.candidate.security_type == "adr"
    assert mapped.candidate.source_security_type == "ADRC"


def test_mapper_allows_missing_name() -> None:
    mapped = map_ticker_reference(ref(name=None))

    assert mapped.candidate is not None
    assert mapped.candidate.name is None
    assert mapped.skipped_reason is None


def test_mapper_warns_for_unknown_exchange_and_type() -> None:
    mapped = map_ticker_reference(ref(primary_exchange="XZZZ", type="MYSTERY"))

    assert mapped.candidate is not None
    assert mapped.candidate.primary_exchange is not None
    assert mapped.candidate.primary_exchange.provisional is True
    assert mapped.candidate.asset_class == "other"
    assert mapped.candidate.security_type == "other"
    assert len(mapped.warnings) == 2


def test_mapper_warns_for_missing_type() -> None:
    mapped = map_ticker_reference(ref(type=None))

    assert mapped.candidate is not None
    assert mapped.candidate.security_type == "unknown"
    assert mapped.warnings == ("missing provider security type mapped to unknown",)


def test_mapper_adds_previous_ticker_alias_when_present() -> None:
    mapped = map_ticker_reference(ref(ticker="META", previous_ticker="FB"))

    assert mapped.candidate is not None
    assert ("previous_ticker", "FB") in {
        (alias.alias_type, alias.alias_value) for alias in mapped.candidate.aliases
    }
