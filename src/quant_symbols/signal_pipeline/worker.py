from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import time
from typing import Any

from quant_symbols.signal_pipeline.repository import SignalPipelineRepository


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerOptions:
    worker_name: str = "signal-watchlist-worker"
    batch_size: int = 50
    poll_interval_seconds: float = 5.0
    run_once: bool = False


class SignalPipelineWorker:
    def __init__(self, engine: Any, options: WorkerOptions | None = None) -> None:
        self.engine = engine
        self.options = options or WorkerOptions()

    def run_once(self) -> dict[str, int]:
        processed = 0
        accepted = 0
        unresolved = 0
        failed = 0
        last_event_id = None

        with self.engine.begin() as connection:
            repo = SignalPipelineRepository(connection)
            events = repo.claim_pending_signal_events(batch_size=self.options.batch_size)

        for event in events:
            event_id = int(event["id"])
            last_event_id = event_id
            try:
                with self.engine.begin() as connection:
                    repo = SignalPipelineRepository(connection)
                    result = repo.process_signal_event(event)
                    repo.record_worker_heartbeat(
                        worker_name=self.options.worker_name,
                        status="running",
                        last_processed_signal_event_id=event_id,
                        metadata={"last_result": result["status"]},
                    )
                processed += 1
                if result["status"] == "accepted":
                    accepted += 1
                elif result["status"] == "unresolved":
                    unresolved += 1
            except Exception as exc:
                failed += 1
                log.exception("signal_event_processing_failed event_id=%s", event_id)
                with self.engine.begin() as connection:
                    repo = SignalPipelineRepository(connection)
                    repo.fail_signal_event(event_id, str(exc))
                    repo.record_worker_heartbeat(
                        worker_name=self.options.worker_name,
                        status="error",
                        last_processed_signal_event_id=event_id,
                        metadata={"error": _redact(str(exc))},
                    )

        if not events:
            with self.engine.begin() as connection:
                SignalPipelineRepository(connection).record_worker_heartbeat(
                    worker_name=self.options.worker_name,
                    status="idle",
                    last_processed_signal_event_id=last_event_id,
                )

        return {
            "processed": processed,
            "accepted": accepted,
            "unresolved": unresolved,
            "failed": failed,
        }

    def run_forever(self) -> None:
        while True:
            summary = self.run_once()
            log.info("signal_pipeline_worker_summary=%s", summary)
            if self.options.run_once:
                return
            time.sleep(self.options.poll_interval_seconds)


def options_from_env(*, run_once: bool = False) -> WorkerOptions:
    return WorkerOptions(
        worker_name=os.environ.get("SIGNAL_WORKER_NAME", "signal-watchlist-worker"),
        batch_size=int(os.environ.get("SIGNAL_WORKER_BATCH_SIZE", "50")),
        poll_interval_seconds=float(os.environ.get("SIGNAL_WORKER_POLL_SECONDS", "5")),
        run_once=run_once,
    )


def build_engine() -> Any:
    from sqlalchemy import create_engine

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_engine(database_url, pool_pre_ping=True)


def _redact(message: str) -> str:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        message = message.replace(database_url, "<redacted database url>")
    return message[:1000]
