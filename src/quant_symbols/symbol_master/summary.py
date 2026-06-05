"""Symbol sync counters and output formatting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quant_symbols.symbol_master.data_quality import (
    ActiveInactiveDiff,
    QualityFinding,
    finding_category_counts,
    top_warning_categories,
)


@dataclass
class SyncSummary:
    """Counters returned by the symbol sync job."""

    vendor: str = "massive"
    mode: str = "fixture"
    status: str = "ok"
    run_id: int | None = None
    pages: int = 0
    records_seen: int = 0
    raw_payloads: int = 0
    symbols_inserted: int = 0
    symbols_updated: int = 0
    symbols_unchanged: int = 0
    deactivated: int = 0
    reactivated: int = 0
    exchanges_inserted: int = 0
    exchanges_updated: int = 0
    exchanges_unchanged: int = 0
    vendor_ids_inserted: int = 0
    vendor_ids_updated: int = 0
    vendor_ids_unchanged: int = 0
    aliases_inserted: int = 0
    aliases_unchanged: int = 0
    skipped: int = 0
    warnings: int = 0
    errors: int = 0
    error_message: str | None = None
    warning_messages: list[str] = field(default_factory=list)
    quality_findings: list[QualityFinding] = field(default_factory=list)
    active_inactive_diffs: list[ActiveInactiveDiff] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        self.warnings += 1
        self.warning_messages.append(message)

    def add_finding(self, finding: QualityFinding) -> None:
        self.quality_findings.append(finding)
        if finding.severity == "warning":
            self.warnings += 1
            self.warning_messages.append(finding.message)
        elif finding.severity == "error":
            self.errors += 1

    def add_active_inactive_diffs(self, diffs: tuple[ActiveInactiveDiff, ...]) -> None:
        self.active_inactive_diffs.extend(diffs)
        for diff in diffs:
            if diff.direction == "deactivated":
                self.deactivated += 1
            elif diff.direction == "reactivated":
                self.reactivated += 1

    def merge_repository_counts(self, counts: dict[str, int]) -> None:
        for key, value in counts.items():
            if hasattr(self, key) and key not in {"deactivated", "reactivated"}:
                setattr(self, key, getattr(self, key) + value)

    def counts_payload(self) -> dict[str, int]:
        return {
            "pages": self.pages,
            "records_seen": self.records_seen,
            "raw_payloads": self.raw_payloads,
            "inserted": self.symbols_inserted,
            "updated": self.symbols_updated,
            "unchanged": self.symbols_unchanged,
            "deactivated": self.deactivated,
            "reactivated": self.reactivated,
            "skipped": self.skipped,
            "warned": self.warnings,
            "errored": self.errors,
            "exchanges_inserted": self.exchanges_inserted,
            "exchanges_updated": self.exchanges_updated,
            "exchanges_unchanged": self.exchanges_unchanged,
            "vendor_ids_inserted": self.vendor_ids_inserted,
            "vendor_ids_updated": self.vendor_ids_updated,
            "vendor_ids_unchanged": self.vendor_ids_unchanged,
            "aliases_inserted": self.aliases_inserted,
            "aliases_unchanged": self.aliases_unchanged,
        }

    def active_inactive_payload(self) -> dict[str, Any]:
        deactivated = [diff.as_dict() for diff in self.active_inactive_diffs if diff.direction == "deactivated"]
        reactivated = [diff.as_dict() for diff in self.active_inactive_diffs if diff.direction == "reactivated"]
        return {
            "deactivated_count": len(deactivated),
            "reactivated_count": len(reactivated),
            "deactivated": deactivated,
            "reactivated": reactivated,
        }

    def health_payload(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "mode": self.mode,
            "status": self.status,
            "run_id": self.run_id,
            "counts": self.counts_payload(),
            "warnings": {
                "total": self.warnings,
                "categories": finding_category_counts(self.quality_findings, severity="warning"),
            },
            "errors": {
                "total": self.errors,
                "categories": finding_category_counts(self.quality_findings, severity="error"),
            },
            "active_inactive_diffs": self.active_inactive_payload(),
            "top_warning_categories": top_warning_categories(self.quality_findings),
            "error_message": self.error_message,
        }

    def quality_findings_payload(self) -> list[dict[str, Any]]:
        return [finding.as_dict() for finding in self.quality_findings]

    def format_line(self) -> str:
        fields: list[tuple[str, object]] = [
            ("symbols_sync", self.status),
            ("vendor", self.vendor),
            ("mode", self.mode),
        ]
        if self.run_id is not None:
            fields.append(("run_id", self.run_id))
        fields.extend(
            [
                ("pages", self.pages),
                ("records_seen", self.records_seen),
                ("raw_payloads", self.raw_payloads),
                ("symbols_inserted", self.symbols_inserted),
                ("symbols_updated", self.symbols_updated),
                ("symbols_unchanged", self.symbols_unchanged),
                ("deactivated", self.deactivated),
                ("reactivated", self.reactivated),
                ("exchanges_inserted", self.exchanges_inserted),
                ("vendor_ids_inserted", self.vendor_ids_inserted),
                ("aliases_inserted", self.aliases_inserted),
                ("skipped", self.skipped),
                ("warnings", self.warnings),
                ("errors", self.errors),
            ]
        )
        if self.error_message:
            fields.append(("error", _single_token(self.error_message)))
        return " ".join(f"{key}={value}" for key, value in fields)


def _single_token(value: str) -> str:
    return value.strip().replace("\n", " ").replace("\r", " ").replace(" ", "_")[:180]
