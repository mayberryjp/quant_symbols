from __future__ import annotations

from pathlib import Path

from quant_symbols.cli import build_parser
from quant_symbols.symbol_master.fixtures import load_massive_fixture_pages
from quant_symbols.symbol_master.massive_sync import MassiveSymbolSyncJob, SyncOptions


FIXTURES = Path(__file__).parent / "fixtures" / "massive"


def test_cli_exposes_symbol_sync_commands() -> None:
    parser = build_parser()

    assert parser.parse_args(["symbols", "sync", "--fixture", str(FIXTURES), "--dry-run"]).func.__name__ == "symbols_sync"
    assert parser.parse_args(["symbols", "sync-summary", "--latest"]).func.__name__ == "symbols_sync_summary"


def test_fixture_loader_builds_deterministic_page() -> None:
    pages = load_massive_fixture_pages(FIXTURES)

    assert len(pages) == 1
    assert [result.ticker for result in pages[0].results] == ["AAPL", "BABA", "SPY", "SBNY", "META"]


def test_dry_run_maps_fixture_without_database_writes() -> None:
    summary = MassiveSymbolSyncJob().run(SyncOptions(fixture=FIXTURES, dry_run=True))

    assert summary.status == "ok"
    assert summary.pages == 1
    assert summary.records_seen == 5
    assert summary.raw_payloads == 0
    assert summary.symbols_inserted == 5
    assert summary.exchanges_inserted == 3
    assert summary.vendor_ids_inserted == 5
    assert summary.aliases_inserted == 10
    assert summary.errors == 0


def test_failure_path_marks_run_failed_and_preserves_counts(monkeypatch) -> None:
    class FakeRepository:
        finished: dict[str, object] = {}

        def __init__(self, _connection: object) -> None:
            pass

        def vendor_source_id(self, _code: str) -> int:
            return 1

        def start_run(self, **_kwargs: object) -> int:
            return 123

        def insert_raw_payload(self, **_kwargs: object) -> object:
            raise RuntimeError("page fixture://boom failed")

        def finish_run(self, **kwargs: object) -> None:
            FakeRepository.finished = kwargs

    class FakeConnection:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, *_exc: object) -> None:
            return None

    class FakeEngine:
        def begin(self) -> FakeConnection:
            return FakeConnection()

    import quant_symbols.symbol_master.massive_sync as massive_sync

    monkeypatch.setattr(massive_sync, "SymbolMasterRepository", FakeRepository)

    summary = MassiveSymbolSyncJob(engine=FakeEngine()).run(SyncOptions(fixture=FIXTURES))

    assert summary.status == "failed"
    assert summary.run_id == 123
    assert summary.records_seen == 1
    assert "fixture://boom" in str(summary.error_message)
    assert FakeRepository.finished["run_id"] == 123
    assert FakeRepository.finished["status"] == "failed"
    assert FakeRepository.finished["records_seen"] == 1
    assert FakeRepository.finished["symbols_new"] == 0
    assert FakeRepository.finished["symbols_delisted"] == 0
    assert "fixture://boom" in str(FakeRepository.finished["error_message"])
