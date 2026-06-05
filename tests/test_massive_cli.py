from __future__ import annotations

import pytest

from quant_symbols.vendors.massive import cli


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


def test_help_documents_only_live_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "--live" in captured.out
    assert "--ticker" not in captured.out
    assert "--limit" not in captured.out
