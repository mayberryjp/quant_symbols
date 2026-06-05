"""Fixture loading for local symbol sync smoke runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from quant_symbols.vendors.massive.models import TickerReferencePage


def load_massive_fixture_pages(path: str | Path) -> tuple[TickerReferencePage, ...]:
    """Load Massive ticker records or pages from a JSON file/directory."""

    fixture_path = Path(path)
    if fixture_path.is_dir():
        records = [_read_json(file_path) for file_path in sorted(fixture_path.glob("*.json"))]
        return (_page_from_records(records, request_url=f"fixture://{fixture_path.as_posix()}"),)
    payload = _read_json(fixture_path)
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return (
            TickerReferencePage.from_payload(
                payload,
                request_url=f"fixture://{fixture_path.as_posix()}",
                fetched_at=datetime.now(timezone.utc),
            ),
        )
    if isinstance(payload, list):
        return (_page_from_records(payload, request_url=f"fixture://{fixture_path.as_posix()}"),)
    if isinstance(payload, dict):
        return (_page_from_records([payload], request_url=f"fixture://{fixture_path.as_posix()}"),)
    raise ValueError(f"fixture must contain a JSON object or list: {fixture_path}")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _page_from_records(records: Iterable[Any], *, request_url: str) -> TickerReferencePage:
    record_list = list(records)
    payload = {
        "status": "OK",
        "request_id": "fixture",
        "count": len(record_list),
        "results": record_list,
    }
    return TickerReferencePage.from_payload(
        payload,
        request_url=request_url,
        fetched_at=datetime.now(timezone.utc),
    )
