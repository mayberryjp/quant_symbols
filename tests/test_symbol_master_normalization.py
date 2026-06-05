from __future__ import annotations

from quant_symbols.symbol_master.normalization import map_massive_ticker_raw_record


def raw_record(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
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
        "last_updated_utc": "2024-01-02T03:04:05Z",
        "delisted_utc": None,
    }
    payload.update(overrides)
    return payload


def test_common_stock_maps_to_equity_candidate() -> None:
    candidate = map_massive_ticker_raw_record(raw_record())

    assert candidate.source_ticker == "AAPL"
    assert candidate.canonical_ticker == "AAPL"
    assert candidate.name == "Apple Inc."
    assert candidate.market == "stocks"
    assert candidate.locale == "us"
    assert candidate.primary_exchange_code == "XNAS"
    assert candidate.currency_name == "usd"
    assert candidate.asset_type == "equity"
    assert candidate.security_type == "common_stock"
    assert candidate.provider_type == "CS"
    assert candidate.active is True
    assert candidate.cik == "0000320193"
    assert candidate.composite_figi == "BBG000B9XRY4"
    assert candidate.share_class_figi == "BBG001S5N8V8"
    assert candidate.last_updated_utc is not None
    assert candidate.delisted_utc is None


def test_etf_maps_to_fund_candidate() -> None:
    candidate = map_massive_ticker_raw_record(raw_record(ticker="SPY", type="ETF"))

    assert candidate.asset_type == "fund"
    assert candidate.security_type == "etf"
    assert candidate.provider_type == "ETF"


def test_unknown_type_is_preserved_as_unknown() -> None:
    candidate = map_massive_ticker_raw_record(raw_record(type="RIGHT"))

    assert candidate.asset_type == "unknown"
    assert candidate.security_type == "unknown"
    assert candidate.provider_type == "RIGHT"


def test_missing_optional_fields_do_not_crash() -> None:
    candidate = map_massive_ticker_raw_record({"ticker": "MSFT", "type": "CS"})

    assert candidate.source_ticker == "MSFT"
    assert candidate.canonical_ticker == "MSFT"
    assert candidate.name is None
    assert candidate.market is None
    assert candidate.locale is None
    assert candidate.primary_exchange_code is None
    assert candidate.currency_name is None
    assert candidate.active is None
    assert candidate.cik is None
    assert candidate.composite_figi is None
    assert candidate.share_class_figi is None
    assert candidate.last_updated_utc is None
    assert candidate.delisted_utc is None


def test_canonical_ticker_is_uppercased_while_source_is_preserved() -> None:
    candidate = map_massive_ticker_raw_record(raw_record(ticker="brk.b"))

    assert candidate.source_ticker == "brk.b"
    assert candidate.canonical_ticker == "BRK.B"


def test_raw_provider_dictionary_is_preserved_without_mutation() -> None:
    provider_payload = raw_record(ticker="meta", name="Meta Platforms, Inc.")
    original_payload = dict(provider_payload)

    candidate = map_massive_ticker_raw_record(provider_payload)

    assert provider_payload == original_payload
    assert candidate.raw_record == original_payload
    assert candidate.raw_record is not provider_payload


def test_mapper_requires_no_database_session_or_engine() -> None:
    candidate = map_massive_ticker_raw_record(raw_record(ticker="NVDA"))

    assert candidate.canonical_ticker == "NVDA"
