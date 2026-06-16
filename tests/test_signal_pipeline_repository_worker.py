from __future__ import annotations

import pytest

from quant_symbols.signal_pipeline.models import (
    SignalValidationError,
    signal_submission_from_payload,
)
from quant_symbols.signal_pipeline.repository import SignalPipelineRepository
from quant_symbols.signal_pipeline.worker import SignalPipelineWorker, WorkerOptions


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def one(self):
        if not self._rows:
            raise AssertionError("expected one row")
        return self._rows[0]

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _SignalInsertConnection:
    def __init__(self, *, duplicate: bool = False):
        self.duplicate = duplicate
        self.executed: list[tuple[str, dict]] = []

    def execute(self, sql, values=None):
        text = str(sql)
        params = values or {}
        self.executed.append((text, params))
        if "INSERT INTO signals.signal_sources" in text:
            return _Result([{"id": 7}])
        if "INSERT INTO signals.signal_events" in text:
            return _Result([] if self.duplicate else [{"id": 123, "status": "pending"}])
        if "SELECT id, status" in text and "FROM signals.signal_events" in text:
            return _Result([{"id": 123, "status": "accepted"}])
        raise AssertionError(f"unexpected SQL: {text}")


def test_repository_signal_submission_is_duplicate_safe():
    submission = signal_submission_from_payload(
        {
            "source": "momentum-v1",
            "idempotency_key": "momentum-v1:AAPL",
            "ticker": "AAPL",
            "signal_type": "watchlist_candidate",
            "reason": "breakout",
            "tags": ["momentum"],
            "metadata": {"lookback": 20},
        }
    )
    connection = _SignalInsertConnection()

    result = SignalPipelineRepository(connection).submit_signal_event(submission)

    assert result == {
        "status": "accepted",
        "signal_event_id": 123,
        "watchlist_status": "pending_processing",
    }
    insert_values = connection.executed[1][1]
    assert insert_values["source_id"] == 7
    assert insert_values["external_event_id"] == "momentum-v1:AAPL"
    assert insert_values["tags"] == '["momentum"]'
    assert "ON CONFLICT (source_id, external_event_id) DO NOTHING" in connection.executed[1][0]


def test_repository_duplicate_submission_returns_existing_event():
    submission = signal_submission_from_payload(
        {
            "source": "momentum-v1",
            "idempotency_key": "momentum-v1:AAPL",
            "ticker": "AAPL",
            "signal_type": "watchlist_candidate",
            "reason": "breakout",
        }
    )

    result = SignalPipelineRepository(_SignalInsertConnection(duplicate=True)).submit_signal_event(submission)

    assert result == {
        "status": "duplicate",
        "signal_event_id": 123,
        "watchlist_status": "accepted",
    }


def test_signal_submission_validation_bounds_tags_score_and_metadata():
    with pytest.raises(SignalValidationError, match="score must be between 0 and 1"):
        signal_submission_from_payload(
            {
                "source": "s",
                "idempotency_key": "k",
                "ticker": "AAPL",
                "signal_type": "watchlist_candidate",
                "reason": "r",
                "score": -0.1,
            }
        )
    with pytest.raises(SignalValidationError, match="tags may contain at most"):
        signal_submission_from_payload(
            {
                "source": "s",
                "idempotency_key": "k",
                "ticker": "AAPL",
                "signal_type": "watchlist_candidate",
                "reason": "r",
                "tags": [str(i) for i in range(21)],
            }
        )
    with pytest.raises(SignalValidationError, match="metadata must be an object"):
        signal_submission_from_payload(
            {
                "source": "s",
                "idempotency_key": "k",
                "ticker": "AAPL",
                "signal_type": "watchlist_candidate",
                "reason": "r",
                "metadata": [],
            }
        )


class _FakeBegin:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self.state

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, state):
        self.state = state

    def begin(self):
        return _FakeBegin(self.state)


def test_worker_processes_claimed_events(monkeypatch):
    state = {"heartbeats": []}

    class FakeRepo:
        def __init__(self, connection):
            self.connection = connection

        def claim_pending_signal_events(self, *, batch_size):
            assert batch_size == 2
            return ({"id": 10},)

        def process_signal_event(self, event):
            return {"status": "accepted", "signal_event_id": event["id"], "watchlist_entry_id": 20}

        def record_worker_heartbeat(self, **kwargs):
            state["heartbeats"].append(kwargs)

    monkeypatch.setattr("quant_symbols.signal_pipeline.worker.SignalPipelineRepository", FakeRepo)

    worker = SignalPipelineWorker(
        engine=_FakeEngine(state),
        options=WorkerOptions(batch_size=2, run_once=True),
    )

    assert worker.run_once() == {"processed": 1, "accepted": 1, "unresolved": 0, "failed": 0}
    assert state["heartbeats"][0]["last_processed_signal_event_id"] == 10


def test_worker_marks_failed_event(monkeypatch):
    state = {"failed": [], "heartbeats": []}

    class FakeRepo:
        def __init__(self, connection):
            self.connection = connection

        def claim_pending_signal_events(self, *, batch_size):
            return ({"id": 10},)

        def process_signal_event(self, event):
            raise RuntimeError("boom")

        def fail_signal_event(self, event_id, error_message):
            state["failed"].append((event_id, error_message))

        def record_worker_heartbeat(self, **kwargs):
            state["heartbeats"].append(kwargs)

    monkeypatch.setattr("quant_symbols.signal_pipeline.worker.SignalPipelineRepository", FakeRepo)

    worker = SignalPipelineWorker(engine=_FakeEngine(state), options=WorkerOptions(run_once=True))

    assert worker.run_once() == {"processed": 0, "accepted": 0, "unresolved": 0, "failed": 1}
    assert state["failed"] == [(10, "boom")]
    assert state["heartbeats"][0]["status"] == "error"
