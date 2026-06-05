from __future__ import annotations

from types import SimpleNamespace

import pytest

from quant_symbols.vendors.massive import cli


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


def fail_if_client_is_built() -> None:
    raise AssertionError("network client should not be built")


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
