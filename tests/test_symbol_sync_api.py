from __future__ import annotations

import pytest


def test_latest_symbol_sync_health_endpoint_serializes_domain_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    testclient = pytest.importorskip("fastapi.testclient")

    expected = {
        "run_id": 42,
        "vendor": "massive",
        "endpoint": "/v3/reference/tickers",
        "status": "succeeded",
        "started_at": "2026-06-05T00:00:00+00:00",
        "completed_at": "2026-06-05T00:01:00+00:00",
        "counts": {
            "records_seen": 5,
            "raw_payloads": 5,
            "inserted": 5,
            "updated": 0,
            "unchanged": 0,
            "deactivated": 0,
            "reactivated": 0,
            "skipped": 0,
            "warned": 0,
            "errored": 0,
        },
        "warnings": {"total": 0, "categories": {}},
        "errors": {"total": 0, "categories": {}},
        "active_inactive_diffs": {
            "deactivated_count": 0,
            "reactivated_count": 0,
            "deactivated": [],
            "reactivated": [],
        },
        "top_warning_categories": [],
        "error_message": None,
    }

    class FakeJob:
        def __init__(self, *, engine: object | None = None) -> None:
            self.engine = engine

        def latest_health(self) -> dict[str, object]:
            return expected

    import quant_symbols.symbol_master.massive_sync as massive_sync

    monkeypatch.setattr(massive_sync, "MassiveSymbolSyncJob", FakeJob)

    from quant_symbols.api import create_app

    client = testclient.TestClient(create_app(engine=object()))

    response = client.get("/jobs/symbol-sync/latest")

    assert response.status_code == 200
    assert response.json() == expected
