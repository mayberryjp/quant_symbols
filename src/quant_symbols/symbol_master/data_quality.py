"""Symbol-master data quality checks for Massive/Polygon syncs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from quant_symbols.symbol_master.massive_mapper import SymbolCandidate
from quant_symbols.vendors.massive.models import TickerReference


EXPECTED_US_MARKET = "stocks"
EXPECTED_US_LOCALE = "us"
EXPECTED_US_CURRENCY = "USD"


@dataclass(frozen=True)
class QualityFinding:
    """Deterministic warning/error record emitted by symbol quality checks."""

    category: str
    severity: str
    ticker: str | None
    message: str
    field: str | None = None
    value: Any | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "category": self.category,
            "severity": self.severity,
            "ticker": self.ticker,
            "message": self.message,
        }
        if self.field is not None:
            payload["field"] = self.field
        if self.value is not None:
            payload["value"] = self.value
        return payload


@dataclass(frozen=True)
class ActiveState:
    """Comparable active/inactive state for one canonical market symbol."""

    canonical_ticker: str
    market: str
    locale: str
    active: bool

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.locale.lower(), self.market.lower(), self.canonical_ticker.upper())


@dataclass(frozen=True)
class ActiveInactiveDiff:
    """Active flag transition compared with the prior successful run."""

    canonical_ticker: str
    market: str
    locale: str
    previous_active: bool
    current_active: bool

    @property
    def direction(self) -> str:
        if self.previous_active and not self.current_active:
            return "deactivated"
        if not self.previous_active and self.current_active:
            return "reactivated"
        return "unchanged"

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_ticker": self.canonical_ticker,
            "market": self.market,
            "locale": self.locale,
            "previous_active": self.previous_active,
            "current_active": self.current_active,
            "direction": self.direction,
        }


class SymbolQualityChecker:
    """Stateful checker for one symbol sync run."""

    def __init__(self) -> None:
        self._seen_keys: dict[tuple[str, str, str], str] = {}

    def check(
        self,
        *,
        reference: TickerReference,
        candidate: SymbolCandidate | None,
        mapper_warnings: Iterable[str] = (),
    ) -> tuple[QualityFinding, ...]:
        findings: list[QualityFinding] = []
        ticker = _ticker(reference, candidate)
        findings.extend(_missing_field_findings(reference, ticker))

        if candidate is not None:
            key = (
                candidate.locale.lower(),
                candidate.market.lower(),
                candidate.canonical_ticker.upper(),
            )
            previous_ticker = self._seen_keys.get(key)
            if previous_ticker is None:
                self._seen_keys[key] = candidate.source_ticker
            else:
                findings.append(
                    QualityFinding(
                        category="duplicate_canonical_ticker",
                        severity="error",
                        ticker=candidate.canonical_ticker,
                        field="canonical_ticker",
                        value=candidate.canonical_ticker,
                        message=(
                            "duplicate canonical ticker within locale/market boundary: "
                            f"{candidate.locale}/{candidate.market}/{candidate.canonical_ticker} "
                            f"already seen as {previous_ticker}"
                        ),
                    )
                )
            findings.extend(_unexpected_universe_findings(candidate))

        for warning in mapper_warnings:
            category = _mapper_warning_category(warning)
            findings.append(
                QualityFinding(
                    category=category,
                    severity="warning",
                    ticker=ticker,
                    field="security_type" if category == "unsupported_security_type" else None,
                    message=warning,
                )
            )
        return tuple(findings)


def active_state_from_candidate(candidate: SymbolCandidate) -> ActiveState:
    return ActiveState(
        canonical_ticker=candidate.canonical_ticker,
        market=candidate.market,
        locale=candidate.locale,
        active=candidate.active,
    )


def calculate_active_inactive_diffs(
    *,
    previous: Mapping[tuple[str, str, str], ActiveState],
    current: Mapping[tuple[str, str, str], ActiveState],
) -> tuple[ActiveInactiveDiff, ...]:
    """Compare current run states against a prior successful-run baseline."""

    diffs: list[ActiveInactiveDiff] = []
    for key in sorted(current):
        current_state = current[key]
        previous_state = previous.get(key)
        if previous_state is None or previous_state.active == current_state.active:
            continue
        diffs.append(
            ActiveInactiveDiff(
                canonical_ticker=current_state.canonical_ticker,
                market=current_state.market,
                locale=current_state.locale,
                previous_active=previous_state.active,
                current_active=current_state.active,
            )
        )
    return tuple(diffs)


def finding_category_counts(findings: Iterable[QualityFinding], *, severity: str) -> dict[str, int]:
    counter = Counter(finding.category for finding in findings if finding.severity == severity)
    return dict(sorted(counter.items()))


def top_warning_categories(findings: Iterable[QualityFinding], *, limit: int = 5) -> list[dict[str, Any]]:
    counter = Counter(finding.category for finding in findings if finding.severity == "warning")
    return [
        {"category": category, "count": count}
        for category, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _missing_field_findings(reference: TickerReference, ticker: str | None) -> list[QualityFinding]:
    raw = reference.raw
    field_map = {
        "name": raw.get("name"),
        "exchange": raw.get("primary_exchange"),
        "currency": raw.get("currency_name"),
        "market": raw.get("market"),
        "locale": raw.get("locale"),
        "security_type": raw.get("type"),
        "active": raw.get("active"),
        "vendor_identifier": raw.get("ticker"),
    }
    findings: list[QualityFinding] = []
    for field_name, value in field_map.items():
        if _blank(value):
            findings.append(
                QualityFinding(
                    category="missing_field",
                    severity="warning",
                    ticker=ticker,
                    field=field_name,
                    message=f"missing or blank required symbol field: {field_name}",
                )
            )
    return findings


def _unexpected_universe_findings(candidate: SymbolCandidate) -> list[QualityFinding]:
    checks = (
        ("market", candidate.market, EXPECTED_US_MARKET),
        ("locale", candidate.locale, EXPECTED_US_LOCALE),
        ("currency", candidate.currency, EXPECTED_US_CURRENCY),
    )
    findings: list[QualityFinding] = []
    for field_name, value, expected in checks:
        if value.lower() != expected.lower():
            findings.append(
                QualityFinding(
                    category="unexpected_us_universe_value",
                    severity="warning",
                    ticker=candidate.canonical_ticker,
                    field=field_name,
                    value=value,
                    message=f"unexpected {field_name} for U.S. stock/ETF universe: {value}",
                )
            )
    return findings


def _mapper_warning_category(warning: str) -> str:
    if "security type" in warning:
        return "unsupported_security_type"
    if "primary exchange" in warning:
        return "unexpected_exchange"
    if "currency" in warning:
        return "unexpected_us_universe_value"
    return "mapper_warning"


def _ticker(reference: TickerReference, candidate: SymbolCandidate | None) -> str | None:
    if candidate is not None:
        return candidate.canonical_ticker
    return reference.ticker.strip().upper() if reference.ticker.strip() else None


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False
