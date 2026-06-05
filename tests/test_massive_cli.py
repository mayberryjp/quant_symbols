from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from quant_symbols.symbol_master.massive_raw_storage import RawStorageSummary
from quant_symbols.vendors.massive import cli
from quant_symbols.vendors.massive.models import TickerReferencePage


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def iter_ticker_pages(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        page = SimpleNamespace(
            status="OK",
            count=1,
            request_id="request-1",
            results=(SimpleNamespace(ticker=str(kwargs["ticker"])),),
        )
        yield page


class FakeRawClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def iter_ticker_pages(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        yield TickerReferencePage.from_payload(
            {
                "status": "OK",
                "request_id": "raw-request-1",
                "count": 1,
                "results": [
                    {
                        "ticker": str(kwargs["ticker"]),
                        "name": "Microsoft Corporation",
                        "market": "stocks",
                    }
                ],
            },
            request_url="fake://massive/raw-fetch",
        )


class FakeRawStorageJob:
    def __init__(self, engine: object) -> None:
        self.engine = engine
        self.pages: tuple[TickerReferencePage, ...] = ()
        self.request_params: dict[str, Any] = {}

    def store_pages(
        self,
        pages: object,
        *,
        request_params: dict[str, Any],
    ) -> RawStorageSummary:
        self.pages = tuple(pages)  # type: ignore[arg-type]
        self.request_params = request_params
        records_seen = sum(len(page.results) for page in self.pages)
        return RawStorageSummary(
            status="ok",
            run_id=123,
            pages=len(self.pages),
            records_seen=records_seen,
            raw_payloads_inserted=records_seen,
            errors=0,
        )


def fail_if_client_is_built() -> None:
    raise AssertionError("network client should not be built")


def fail_if_engine_is_built() -> None:
    raise AssertionError("database engine should not be built")


def test_disabled_smoke_command_exits_zero_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.setattr(
        cli.MassiveClient,
        "from_env",
        staticmethod(fail_if_client_is_built),
    )

    exit_code = cli.main([])

    assert exit_code == 0
    assert capsys.readouterr().out == "live check disabled; pass --live with MASSIVE_API_KEY set\n"


def test_live_mode_fails_clearly_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)

    exit_code = cli.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "massive client error: MASSIVE_API_KEY is required" in captured.err
    assert "secret" not in captured.out
    assert "secret" not in captured.err


def test_live_mode_uses_injected_client_and_requested_ticker_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeClient()

    exit_code = cli.main(
        ["--live", "--ticker", "MSFT", "--limit", "1"],
        client_factory=lambda: client,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert client.calls == [{"ticker": "MSFT", "limit": 1, "max_pages": 1}]
    assert captured.err == ""
    assert captured.out == '{"count": 1, "request_id": "request-1", "status": "OK", "tickers": ["MSFT"]}\n'


def test_live_mode_defaults_to_tiny_aapl_request(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeClient()

    exit_code = cli.main(["--live"], client_factory=lambda: client)

    assert exit_code == 0
    assert client.calls == [{"ticker": "AAPL", "limit": 1, "max_pages": 1}]
    assert "AAPL" in capsys.readouterr().out


def test_live_mode_output_does_not_include_api_key(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeClient()

    exit_code = cli.main(["--live", "--ticker", "AAPL", "--limit", "1"], client_factory=lambda: client)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "test-secret" not in captured.out
    assert "test-secret" not in captured.err


def test_help_documents_live_ticker_and_limit_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "--live" in captured.out
    assert "--ticker" in captured.out
    assert "--limit" in captured.out


def test_raw_fetch_fixture_mode_does_not_need_api_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    jobs: list[FakeRawStorageJob] = []

    def job_factory(engine: object) -> FakeRawStorageJob:
        job = FakeRawStorageJob(engine)
        jobs.append(job)
        return job

    exit_code = cli.main(
        [
            "--raw-fetch",
            "--fixture",
            "tests/fixtures/massive/active_stock.json",
            "--ticker",
            "AAPL",
            "--limit",
            "1",
        ],
        client_factory=fail_if_client_is_built,
        engine_factory=lambda: object(),
        raw_storage_job_factory=job_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == (
        "massive_raw_fetch=ok run_id=123 mode=fixture status=ok "
        "records_seen=1 raw_payloads_inserted=1 errors=0\n"
    )
    assert len(jobs) == 1
    assert jobs[0].request_params == {
        "mode": "fixture",
        "ticker": "AAPL",
        "limit": 1,
        "fixture": "tests/fixtures/massive/active_stock.json",
    }
    assert jobs[0].pages[0].results[0].raw["ticker"] == "AAPL"


def test_raw_fetch_fixture_requires_fixture_path(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(
        ["--raw-fetch"],
        client_factory=fail_if_client_is_built,
        engine_factory=fail_if_engine_is_built,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "--fixture is required" in captured.err


def test_raw_fetch_live_without_api_key_fails_before_storage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)

    exit_code = cli.main(
        ["--raw-fetch", "--live"],
        engine_factory=fail_if_engine_is_built,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "massive client error: MASSIVE_API_KEY is required" in captured.err
    assert "secret" not in captured.err


def test_raw_fetch_live_uses_injected_client_and_storage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeRawClient()
    jobs: list[FakeRawStorageJob] = []

    def job_factory(engine: object) -> FakeRawStorageJob:
        job = FakeRawStorageJob(engine)
        jobs.append(job)
        return job

    exit_code = cli.main(
        ["--raw-fetch", "--live", "--ticker", "MSFT", "--limit", "1"],
        client_factory=lambda: client,
        engine_factory=lambda: object(),
        raw_storage_job_factory=job_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert client.calls == [{"ticker": "MSFT", "limit": 1, "max_pages": 1}]
    assert captured.err == ""
    assert captured.out == (
        "massive_raw_fetch=ok run_id=123 mode=live status=ok "
        "records_seen=1 raw_payloads_inserted=1 errors=0\n"
    )
    assert jobs[0].request_params == {"mode": "live", "ticker": "MSFT", "limit": 1}
    assert jobs[0].pages[0].results[0].ticker == "MSFT"


def test_raw_fetch_summary_and_params_do_not_include_api_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MASSIVE_API_KEY", "test-secret")
    jobs: list[FakeRawStorageJob] = []

    def job_factory(engine: object) -> FakeRawStorageJob:
        job = FakeRawStorageJob(engine)
        jobs.append(job)
        return job

    exit_code = cli.main(
        ["--raw-fetch", "--live", "--ticker", "AAPL", "--limit", "1"],
        client_factory=lambda: FakeRawClient(),
        engine_factory=lambda: object(),
        raw_storage_job_factory=job_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "test-secret" not in captured.out
    assert "test-secret" not in captured.err
    assert "test-secret" not in repr(jobs[0].request_params)
    assert "api" not in repr(jobs[0].request_params).lower()
