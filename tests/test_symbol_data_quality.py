from __future__ import annotations

from quant_symbols.symbol_master.data_quality import (
    ActiveState,
    SymbolQualityChecker,
    calculate_active_inactive_diffs,
)
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
        "composite_figi": "BBG000B9XRY4",
        "share_class_figi": "BBG001S5N8V8",
    }
    payload.update(overrides)
    return TickerReference.from_payload(payload)


def findings_for(*references: TickerReference) -> list[tuple[str, str, str | None]]:
    checker = SymbolQualityChecker()
    output = []
    for reference in references:
        mapped = map_ticker_reference(reference)
        output.extend(
            (finding.category, finding.severity, finding.field)
            for finding in checker.check(
                reference=reference,
                candidate=mapped.candidate,
                mapper_warnings=mapped.warnings,
            )
        )
    return output


def test_quality_detects_duplicate_canonical_ticker_within_market_locale() -> None:
    findings = findings_for(
        ref(ticker="AAPL", composite_figi="BBG000B9XRY4"),
        ref(ticker="aapl", composite_figi="BBG000B9XRY5"),
    )

    assert ("duplicate_canonical_ticker", "error", "canonical_ticker") in findings


def test_quality_warns_for_missing_required_provider_fields() -> None:
    findings = findings_for(
        ref(
            ticker="MISS",
            name=" ",
            primary_exchange=None,
            currency_name=None,
            market=None,
            locale=None,
            type=None,
            active=None,
        )
    )

    missing_fields = [field for category, severity, field in findings if category == "missing_field" and severity == "warning"]
    assert missing_fields == [
        "name",
        "exchange",
        "currency",
        "market",
        "locale",
        "security_type",
        "active",
    ]


def test_quality_warns_for_unsupported_classification_and_unexpected_universe_values() -> None:
    findings = findings_for(
        ref(
            ticker="ODD",
            market="crypto",
            locale="global",
            currency_name="eur",
            type="MYSTERY",
        )
    )

    assert ("unsupported_security_type", "warning", "security_type") in findings
    assert findings.count(("unexpected_us_universe_value", "warning", "market")) == 1
    assert findings.count(("unexpected_us_universe_value", "warning", "locale")) == 1
    assert findings.count(("unexpected_us_universe_value", "warning", "currency")) == 1


def test_active_inactive_diffs_compare_previous_successful_baseline() -> None:
    previous = {
        ("us", "stocks", "AAPL"): ActiveState("AAPL", "stocks", "us", True),
        ("us", "stocks", "SBNY"): ActiveState("SBNY", "stocks", "us", False),
    }
    current = {
        ("us", "stocks", "AAPL"): ActiveState("AAPL", "stocks", "us", False),
        ("us", "stocks", "SBNY"): ActiveState("SBNY", "stocks", "us", True),
    }

    diffs = calculate_active_inactive_diffs(previous=previous, current=current)

    assert [diff.direction for diff in diffs] == ["deactivated", "reactivated"]
