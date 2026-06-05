"""Symbol sync counters and output formatting."""

from __future__ import annotations

from dataclasses import dataclass, field


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

    def add_warning(self, message: str) -> None:
        self.warnings += 1
        self.warning_messages.append(message)

    def merge_repository_counts(self, counts: dict[str, int]) -> None:
        for key, value in counts.items():
            if hasattr(self, key):
                setattr(self, key, getattr(self, key) + value)

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
