from __future__ import annotations

from quant_symbols.api.app import create_app
from quant_symbols.api.readiness import ReadinessStatus
from quant_symbols.api.testing import TestClient
from quant_symbols.signal_pipeline.models import (
    ManualWatchlistRequest,
    SignalListParams,
    SignalSubmission,
    WatchlistListParams,
    WatchlistPatch,
)


def test_signal_pipeline_health_does_not_touch_database():
    def fail_if_called() -> ReadinessStatus:
        raise AssertionError("readiness should not be called")

    client = TestClient(create_app(readiness_check=fail_if_called))

    response = client.get("/signal-pipeline/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "signal-pipeline"}


def test_post_signals_accepts_valid_submission():
    seen: list[SignalSubmission] = []

    def fake_accept(submission: SignalSubmission) -> dict[str, object]:
        seen.append(submission)
        return {
            "status": "accepted",
            "signal_event_id": 123,
            "watchlist_status": "pending_processing",
        }

    client = TestClient(create_app(signal_accept=fake_accept))

    response = client.post(
        "/signals",
        json={
            "source": "momentum-v1",
            "idempotency_key": "momentum-v1:2026-06-09:AAPL",
            "ticker": "aapl",
            "signal_type": "watchlist_candidate",
            "direction": "long",
            "score": 0.87,
            "confidence": 0.72,
            "reason": "Relative strength breakout",
            "tags": ["momentum", "breakout"],
            "metadata": {"strategy_version": "momentum-v1.0"},
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "signal_event_id": 123,
        "watchlist_status": "pending_processing",
    }
    assert seen == [
        SignalSubmission(
            source="momentum-v1",
            idempotency_key="momentum-v1:2026-06-09:AAPL",
            ticker="AAPL",
            signal_type="watchlist_candidate",
            reason="Relative strength breakout",
            direction="long",
            score=0.87,
            confidence=0.72,
            tags=("momentum", "breakout"),
            metadata={"strategy_version": "momentum-v1.0"},
        )
    ]


def test_post_signals_duplicate_returns_existing_event():
    def fake_accept(_submission: SignalSubmission) -> dict[str, object]:
        return {
            "status": "duplicate",
            "signal_event_id": 123,
            "watchlist_status": "accepted",
        }

    client = TestClient(create_app(signal_accept=fake_accept))

    response = client.post(
        "/signals",
        json={
            "source": "momentum-v1",
            "idempotency_key": "dup",
            "ticker": "AAPL",
            "signal_type": "watchlist_candidate",
            "reason": "Already submitted",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"


def test_post_signals_rejects_missing_reason_and_invalid_score():
    called = False

    def fail_if_called(_submission: SignalSubmission) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    client = TestClient(create_app(signal_accept=fail_if_called))

    response = client.post(
        "/signals",
        json={
            "source": "momentum-v1",
            "idempotency_key": "bad",
            "ticker": "AAPL",
            "signal_type": "watchlist_candidate",
            "score": 1.5,
        },
    )

    assert response.status_code == 422
    assert called is False


def test_list_signals_parses_filters_and_pagination():
    seen: list[SignalListParams] = []

    def fake_list(params: SignalListParams) -> dict[str, object]:
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(signal_list=fake_list))

    response = client.get("/signals?source=momentum-v1&ticker=AAPL&status=pending&signal_type=watchlist_candidate&limit=25&offset=50")

    assert response.status_code == 200
    assert seen == [
        SignalListParams(
            source="momentum-v1",
            ticker="AAPL",
            status="pending",
            signal_type="watchlist_candidate",
            limit=25,
            offset=50,
        )
    ]


def test_manual_watchlist_post_and_patch_routes():
    seen_create: list[ManualWatchlistRequest] = []
    seen_patch: list[tuple[int, WatchlistPatch]] = []

    def fake_create(request: ManualWatchlistRequest) -> dict[str, object]:
        seen_create.append(request)
        return {
            "status": "active",
            "watchlist_entry_id": 456,
            "symbol_id": 1,
            "canonical_ticker": "AAPL",
        }

    def fake_patch(entry_id: int, patch: WatchlistPatch) -> dict[str, object]:
        seen_patch.append((entry_id, patch))
        return {"id": entry_id, "active": False, "status": "inactive"}

    client = TestClient(create_app(watchlist_create=fake_create, watchlist_patch=fake_patch))

    post_response = client.post(
        "/watchlist",
        json={
            "ticker": "aapl",
            "source": "operator",
            "reason": "Manual review candidate",
            "tags": ["manual"],
            "metadata": {"note": "morning review"},
        },
    )
    patch_response = client.patch(
        "/watchlist/456",
        json={"active": False, "update_reason": "review complete"},
    )

    assert post_response.status_code == 201
    assert post_response.json()["watchlist_entry_id"] == 456
    assert seen_create == [
        ManualWatchlistRequest(
            ticker="AAPL",
            source="operator",
            reason="Manual review candidate",
            tags=("manual",),
            metadata={"note": "morning review"},
        )
    ]
    assert patch_response.status_code == 200
    assert seen_patch == [(456, WatchlistPatch(active=False, update_reason="review complete"))]


def test_watchlist_read_routes_parse_filters_and_not_found():
    seen: list[WatchlistListParams] = []

    def fake_list(params: WatchlistListParams) -> dict[str, object]:
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(
        create_app(
            watchlist_list=fake_list,
            watchlist_detail=lambda _entry_id: None,
            watchlist_by_ticker=lambda ticker, **_kwargs: {
                "id": 456,
                "submitted_ticker": ticker,
                "canonical_ticker": "AAPL",
            },
        )
    )

    list_response = client.get("/watchlist?active=false&source=operator&ticker=AAPL&market=stocks&locale=us&tag=manual&limit=10&offset=5")
    detail_response = client.get("/watchlist/999")
    ticker_response = client.get("/watchlist/by-ticker/AAPL")

    assert list_response.status_code == 200
    assert seen == [
        WatchlistListParams(
            active=False,
            source="operator",
            ticker="AAPL",
            market="stocks",
            locale="us",
            tag="manual",
            limit=10,
            offset=5,
        )
    ]
    assert detail_response.status_code == 404
    assert ticker_response.status_code == 200
    assert ticker_response.json()["canonical_ticker"] == "AAPL"


def test_signal_pipeline_ready_includes_status_counts():
    client = TestClient(
        create_app(
            readiness_check=lambda: ReadinessStatus(
                database="ok",
                schema_version="0002_signal_watchlist_pipeline",
                tables=7,
                signal_tables=4,
            ),
            signal_pipeline_status=lambda: {
                "status": "ok",
                "signal_event_counts": {"pending": 2},
                "latest_worker": None,
            },
        )
    )

    response = client.get("/signal-pipeline/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "schema_version": "0002_signal_watchlist_pipeline",
        "pipeline": {
            "status": "ok",
            "signal_event_counts": {"pending": 2},
            "latest_worker": None,
        },
    }
