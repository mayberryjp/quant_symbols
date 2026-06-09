from __future__ import annotations

from typing import Any

from quant_symbols.signal_pipeline.models import (
    ManualWatchlistRequest,
    SignalListParams,
    SignalSubmission,
    WatchlistListParams,
    WatchlistPatch,
)
from quant_symbols.signal_pipeline.repository import (
    create_manual_watchlist_entry,
    get_signal_event,
    get_watchlist_by_ticker,
    get_watchlist_entry,
    list_signal_events,
    list_watchlist_entries,
    patch_watchlist_entry,
    signal_pipeline_status,
    submit_signal_event,
)


def accept_signal(submission: SignalSubmission) -> dict[str, Any]:
    return submit_signal_event(submission)


def list_signals(params: SignalListParams) -> dict[str, Any]:
    return list_signal_events(params)


def get_signal(signal_event_id: int) -> dict[str, Any] | None:
    return get_signal_event(signal_event_id)


def list_watchlist(params: WatchlistListParams) -> dict[str, Any]:
    return list_watchlist_entries(params)


def get_watchlist(watchlist_entry_id: int) -> dict[str, Any] | None:
    return get_watchlist_entry(watchlist_entry_id)


def lookup_watchlist_by_ticker(ticker: str, *, market: str = "stocks", locale: str = "us") -> dict[str, Any] | None:
    return get_watchlist_by_ticker(ticker, market=market, locale=locale)


def create_watchlist(request: ManualWatchlistRequest) -> dict[str, Any]:
    return create_manual_watchlist_entry(request)


def update_watchlist(watchlist_entry_id: int, patch: WatchlistPatch) -> dict[str, Any] | None:
    return patch_watchlist_entry(watchlist_entry_id, patch)


def get_signal_pipeline_status() -> dict[str, Any]:
    return signal_pipeline_status()
