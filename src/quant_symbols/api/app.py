from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Callable, Dict, Optional, Union

from bottle import Bottle, request, response

from quant_symbols.api.readiness import (
    ReadinessStatus,
    check_database_readiness,
    sanitize_readiness_error,
)
from quant_symbols.api.signal_pipeline import (
    accept_signal,
    create_watchlist,
    get_signal,
    get_signal_pipeline_status,
    get_watchlist,
    list_signals,
    list_watchlist,
    lookup_watchlist_by_ticker,
    update_watchlist,
)
from quant_symbols.api.symbols import (
    SymbolCountParams,
    SymbolListParams,
    SymbolTickerLookupParams,
    count_symbols,
    get_symbol_by_id,
    get_symbol_by_ticker,
    list_symbols,
)
from quant_symbols.api.sync_status import (
    SyncLatestParams,
    SyncRunListParams,
    get_latest_sync_run,
    get_sync_run,
    list_sync_runs,
)
from quant_symbols.api.traceability import (
    RawPayloadListParams,
    VendorRunListParams,
    VendorRunStatus,
    get_vendor_run,
    list_symbol_aliases,
    list_symbol_raw_payloads,
    list_symbol_vendor_ids,
    list_vendor_runs,
)
from quant_symbols.signal_pipeline.models import (
    SignalListParams,
    SignalValidationError,
    WatchlistListParams,
    manual_watchlist_from_payload,
    signal_submission_from_payload,
    watchlist_patch_from_payload,
)

SERVICE_NAME = "quant-symbols-api"

log = logging.getLogger(SERVICE_NAME)


ReadinessCheck = Callable[[], Union[ReadinessStatus, Dict[str, Any]]]
SymbolList = Callable[[SymbolListParams], Dict[str, Any]]
SymbolCount = Callable[[SymbolCountParams], Dict[str, Any]]
SymbolDetail = Callable[[int], Optional[Dict[str, Any]]]
SymbolByTicker = Callable[[SymbolTickerLookupParams], Optional[Dict[str, Any]]]
SymbolAliases = Callable[[int], Optional[Dict[str, Any]]]
SymbolVendorIds = Callable[[int], Optional[Dict[str, Any]]]
SymbolRawPayloads = Callable[[RawPayloadListParams], Optional[Dict[str, Any]]]
VendorRuns = Callable[[VendorRunListParams], Dict[str, Any]]
VendorRunDetail = Callable[[int], Optional[Dict[str, Any]]]
SyncLatest = Callable[[SyncLatestParams], Optional[Dict[str, Any]]]
SyncRuns = Callable[[SyncRunListParams], Dict[str, Any]]
SyncRunDetail = Callable[[int], Optional[Dict[str, Any]]]
SignalAccept = Callable[[Any], Dict[str, Any]]
SignalListCallable = Callable[[SignalListParams], Dict[str, Any]]
SignalDetail = Callable[[int], Optional[Dict[str, Any]]]
WatchlistListCallable = Callable[[WatchlistListParams], Dict[str, Any]]
WatchlistDetail = Callable[[int], Optional[Dict[str, Any]]]
WatchlistByTicker = Callable[[str], Optional[Dict[str, Any]]]
WatchlistCreate = Callable[[Any], Dict[str, Any]]
WatchlistPatchCallable = Callable[[int, Any], Optional[Dict[str, Any]]]
SignalPipelineStatus = Callable[[], Dict[str, Any]]

VALID_RUN_STATUSES = frozenset(("running", "succeeded", "failed", "cancelled"))


# ---------------------------------------------------------------------------
# Query-parameter helpers
# ---------------------------------------------------------------------------

class _ValidationError(Exception):
    pass


def _int_param(raw: str | None, *, default: int, ge: int | None = None, le: int | None = None) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise _ValidationError("invalid integer parameter")
    if ge is not None and value < ge:
        raise _ValidationError(f"value must be >= {ge}")
    if le is not None and value > le:
        raise _ValidationError(f"value must be <= {le}")
    return value


def _bool_param(raw: str | None, *, default: bool | None = None) -> bool | None:
    if raw is None or raw == "":
        return default
    lower = raw.lower()
    if lower in ("true", "1", "yes"):
        return True
    if lower in ("false", "0", "no"):
        return False
    return default


def _status_param(raw: str | None) -> str | None:
    if raw is None or raw == "":
        return None
    if raw not in VALID_RUN_STATUSES:
        raise _ValidationError(f"status must be one of {sorted(VALID_RUN_STATUSES)}")
    return raw


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _status_payload(status: Union[ReadinessStatus, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(status, ReadinessStatus):
        return status.as_json()
    return {"status": "ok", **status}


def _not_found(error: str = "symbol not found") -> dict:
    response.status = 404
    return {"status": "not_found", "error": error}


def _server_error(exc: Exception) -> dict:
    log.exception("handler_error: %s", exc)
    response.status = 500
    return {
        "status": "error",
        "error": sanitize_readiness_error(exc, os.environ.get("DATABASE_URL")),
    }


def _validation_error_response(detail: str = "validation error") -> dict:
    response.status = 422
    return {"detail": detail}


def _json_payload() -> Any:
    try:
        payload = request.json
    except Exception as exc:
        raise _ValidationError("request body must be valid JSON") from exc
    if payload is None:
        raise _ValidationError("request body must be a JSON object")
    return payload


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(
    readiness_check: ReadinessCheck = check_database_readiness,
    symbol_list: SymbolList = list_symbols,
    symbol_count: SymbolCount = count_symbols,
    symbol_detail: SymbolDetail = get_symbol_by_id,
    symbol_by_ticker: SymbolByTicker = get_symbol_by_ticker,
    symbol_aliases: SymbolAliases = list_symbol_aliases,
    symbol_vendor_ids: SymbolVendorIds = list_symbol_vendor_ids,
    symbol_raw_payloads: SymbolRawPayloads = list_symbol_raw_payloads,
    vendor_runs: VendorRuns = list_vendor_runs,
    vendor_run_detail: VendorRunDetail = get_vendor_run,
    sync_latest: SyncLatest = get_latest_sync_run,
    sync_runs: SyncRuns = list_sync_runs,
    sync_run_detail: SyncRunDetail = get_sync_run,
    signal_accept: SignalAccept = accept_signal,
    signal_list: SignalListCallable = list_signals,
    signal_detail: SignalDetail = get_signal,
    watchlist_list: WatchlistListCallable = list_watchlist,
    watchlist_detail: WatchlistDetail = get_watchlist,
    watchlist_by_ticker: WatchlistByTicker = lookup_watchlist_by_ticker,
    watchlist_create: WatchlistCreate = create_watchlist,
    watchlist_patch: WatchlistPatchCallable = update_watchlist,
    signal_pipeline_status: SignalPipelineStatus = get_signal_pipeline_status,
) -> Bottle:
    api = Bottle()
    api.title = SERVICE_NAME

    # -- request logging hooks ------------------------------------------

    @api.hook("before_request")
    def _log_before() -> None:
        request._log_start = time.perf_counter()  # type: ignore[attr-defined]
        log.info(
            "request_start method=%s path=%s query=%s",
            request.method, request.path, request.query_string,
        )

    @api.hook("after_request")
    def _log_after() -> None:
        start = getattr(request, "_log_start", None)
        if start is not None:
            duration_ms = (time.perf_counter() - start) * 1000
            log.info(
                "request_end method=%s path=%s status=%d duration_ms=%.1f",
                request.method, request.path, response.status_code, duration_ms,
            )

    # -- health / readiness ---------------------------------------------

    @api.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": SERVICE_NAME}

    @api.get("/ready")
    def ready() -> dict:
        try:
            return _status_payload(readiness_check())
        except Exception as exc:
            response.status = 503
            return {
                "status": "not_ready",
                "database": "error",
                "error": sanitize_readiness_error(exc, os.environ.get("DATABASE_URL")),
            }

    # -- signal pipeline ------------------------------------------------

    @api.get("/signal-pipeline/health")
    def signal_pipeline_health() -> dict:
        return {"status": "ok", "service": "signal-pipeline"}

    @api.get("/signal-pipeline/ready")
    def signal_pipeline_ready() -> dict:
        try:
            status = _status_payload(readiness_check())
            pipeline = signal_pipeline_status()
        except Exception as exc:
            response.status = 503
            return {
                "status": "not_ready",
                "database": "error",
                "error": sanitize_readiness_error(exc, os.environ.get("DATABASE_URL")),
            }
        return {"status": "ok", "database": status["database"], "schema_version": status["schema_version"], "pipeline": pipeline}

    @api.post("/signals")
    def signals_post() -> dict:
        try:
            submission = signal_submission_from_payload(_json_payload())
        except (SignalValidationError, _ValidationError) as exc:
            return _validation_error_response(str(exc))
        try:
            result = signal_accept(submission)
        except Exception as exc:
            return _server_error(exc)
        if result.get("status") == "duplicate":
            response.status = 200
        else:
            response.status = 202
        return result

    @api.get("/signals/<signal_event_id>")
    def signal_detail_route(signal_event_id: str) -> dict:
        try:
            sid = int(signal_event_id)
        except (ValueError, TypeError):
            return _validation_error_response("signal_event_id must be an integer")
        try:
            result = signal_detail(sid)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("signal event not found")
        return result

    @api.get("/signals")
    def signals_get() -> dict:
        try:
            limit = _int_param(request.query.get("limit"), default=100, ge=1, le=500)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()
        params = SignalListParams(
            source=request.query.get("source") or None,
            ticker=request.query.get("ticker") or None,
            status=request.query.get("status") or None,
            signal_type=request.query.get("signal_type") or None,
            limit=limit,
            offset=offset,
        )
        try:
            return signal_list(params)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/watchlist/by-ticker/<ticker>")
    def watchlist_by_ticker_route(ticker: str) -> dict:
        try:
            result = watchlist_by_ticker(
                ticker,
                market=request.query.get("market", "stocks"),
                locale=request.query.get("locale", "us"),
            )
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("watchlist entry not found")
        return result

    @api.get("/watchlist/<watchlist_entry_id>")
    def watchlist_detail_route(watchlist_entry_id: str) -> dict:
        try:
            wid = int(watchlist_entry_id)
        except (ValueError, TypeError):
            return _validation_error_response("watchlist_entry_id must be an integer")
        try:
            result = watchlist_detail(wid)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("watchlist entry not found")
        return result

    @api.get("/watchlist")
    def watchlist_get() -> dict:
        try:
            limit = _int_param(request.query.get("limit"), default=100, ge=1, le=500)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()
        params = WatchlistListParams(
            active=_bool_param(request.query.get("active"), default=True),
            source=request.query.get("source") or None,
            ticker=request.query.get("ticker") or None,
            market=request.query.get("market") or None,
            locale=request.query.get("locale") or None,
            tag=request.query.get("tag") or None,
            signal_type=request.query.get("signal_type") or None,
            limit=limit,
            offset=offset,
        )
        try:
            return watchlist_list(params)
        except Exception as exc:
            return _server_error(exc)

    @api.post("/watchlist")
    def watchlist_post() -> dict:
        try:
            manual_request = manual_watchlist_from_payload(_json_payload())
        except (SignalValidationError, _ValidationError) as exc:
            return _validation_error_response(str(exc))
        try:
            response.status = 201
            return watchlist_create(manual_request)
        except Exception as exc:
            return _server_error(exc)

    @api.patch("/watchlist/<watchlist_entry_id>")
    def watchlist_patch_route(watchlist_entry_id: str) -> dict:
        try:
            wid = int(watchlist_entry_id)
            patch = watchlist_patch_from_payload(_json_payload())
        except (ValueError, TypeError):
            return _validation_error_response("watchlist_entry_id must be an integer")
        except (SignalValidationError, _ValidationError) as exc:
            return _validation_error_response(str(exc))
        try:
            result = watchlist_patch(wid, patch)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("watchlist entry not found")
        return result

    # -- symbol by ticker -----------------------------------------------

    @api.get("/symbols/by-ticker/<ticker>")
    def symbol_by_ticker_route(ticker: str) -> dict:
        active = _bool_param(request.query.get("active"), default=True)
        params = SymbolTickerLookupParams(
            ticker=ticker,
            market=request.query.get("market", "stocks"),
            locale=request.query.get("locale", "us"),
            active=active,
        )
        try:
            symbol = symbol_by_ticker(params)
        except Exception as exc:
            return _server_error(exc)
        if symbol is None:
            return _not_found()
        return symbol

    # -- symbol sub-resources (must precede /symbols/<symbol_id>) -------

    @api.get("/symbols/count")
    def symbol_count_route() -> dict:
        if request.query.get("limit") is not None or request.query.get("offset") is not None:
            return _validation_error_response("limit and offset are not supported for symbol counts")
        active = _bool_param(request.query.get("active"))
        raw_q = request.query.get("q")
        q = raw_q.strip() if raw_q and raw_q.strip() else None
        params = SymbolCountParams(
            active=active,
            market=request.query.get("market") or None,
            locale=request.query.get("locale") or None,
            q=q,
        )
        try:
            return symbol_count(params)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/symbols/<symbol_id>/aliases")
    def symbol_aliases_route(symbol_id: str) -> dict:
        try:
            sid = int(symbol_id)
        except (ValueError, TypeError):
            return _validation_error_response("symbol_id must be an integer")
        try:
            result = symbol_aliases(sid)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found()
        return result

    @api.get("/symbols/<symbol_id>/vendor-ids")
    def symbol_vendor_ids_route(symbol_id: str) -> dict:
        try:
            sid = int(symbol_id)
        except (ValueError, TypeError):
            return _validation_error_response("symbol_id must be an integer")
        try:
            result = symbol_vendor_ids(sid)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found()
        return result

    @api.get("/symbols/<symbol_id>/raw-payloads")
    def symbol_raw_payloads_route(symbol_id: str) -> dict:
        try:
            sid = int(symbol_id)
        except (ValueError, TypeError):
            return _validation_error_response("symbol_id must be an integer")
        try:
            limit = _int_param(request.query.get("limit"), default=50, ge=1, le=100)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()
        params = RawPayloadListParams(symbol_id=sid, limit=limit, offset=offset)
        try:
            result = symbol_raw_payloads(params)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found()
        return result

    # -- symbol detail ---------------------------------------------------

    @api.get("/symbols/<symbol_id>")
    def symbol_detail_route(symbol_id: str) -> dict:
        try:
            sid = int(symbol_id)
        except (ValueError, TypeError):
            return _validation_error_response("symbol_id must be an integer")
        try:
            symbol = symbol_detail(sid)
        except Exception as exc:
            return _server_error(exc)
        if symbol is None:
            return _not_found()
        return symbol

    # -- vendor runs -----------------------------------------------------

    @api.get("/vendor-runs/<run_id>")
    def vendor_run_detail_route(run_id: str) -> dict:
        try:
            rid = int(run_id)
        except (ValueError, TypeError):
            return _validation_error_response("run_id must be an integer")
        try:
            result = vendor_run_detail(rid)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("vendor run not found")
        return result

    @api.get("/vendor-runs")
    def vendor_runs_route() -> dict:
        try:
            status = _status_param(request.query.get("status"))
            limit = _int_param(request.query.get("limit"), default=20, ge=1, le=100)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()
        params = VendorRunListParams(
            vendor=request.query.get("vendor", "massive"),
            endpoint=request.query.get("endpoint") or None,
            status=status,
            limit=limit,
            offset=offset,
        )
        try:
            return vendor_runs(params)
        except Exception as exc:
            return _server_error(exc)

    # -- sync ------------------------------------------------------------

    @api.get("/sync/latest")
    def sync_latest_route() -> dict:
        params = SyncLatestParams(
            vendor=request.query.get("vendor", "massive"),
            endpoint=request.query.get("endpoint", "/v3/reference/tickers"),
        )
        try:
            result = sync_latest(params)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("sync run not found")
        return {"status": "ok", "latest": result}

    @api.get("/sync/runs/<run_id>")
    def sync_run_detail_route(run_id: str) -> dict:
        try:
            rid = int(run_id)
        except (ValueError, TypeError):
            return _validation_error_response("run_id must be an integer")
        try:
            result = sync_run_detail(rid)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("sync run not found")
        return result

    @api.get("/sync/runs")
    def sync_runs_route() -> dict:
        try:
            status = _status_param(request.query.get("status"))
            limit = _int_param(request.query.get("limit"), default=20, ge=1, le=100)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()
        params = SyncRunListParams(
            vendor=request.query.get("vendor", "massive"),
            endpoint=request.query.get("endpoint", "/v3/reference/tickers"),
            status=status,
            limit=limit,
            offset=offset,
        )
        try:
            return sync_runs(params)
        except Exception as exc:
            return _server_error(exc)

    # -- symbol list (broadest match, defined last) ----------------------

    @api.get("/symbols")
    def symbols() -> dict:
        try:
            limit = _int_param(request.query.get("limit"), default=100, ge=1, le=500)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()
        active = _bool_param(request.query.get("active"))
        raw_q = request.query.get("q")
        q = raw_q.strip() if raw_q and raw_q.strip() else None
        params = SymbolListParams(
            active=active,
            market=request.query.get("market") or None,
            locale=request.query.get("locale") or None,
            q=q,
            limit=limit,
            offset=offset,
        )
        try:
            return symbol_list(params)
        except Exception as exc:
            return _server_error(exc)

    return api


# ---------------------------------------------------------------------------
# Module-level setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
    force=True,
)

print(
    f"[{SERVICE_NAME}] module={__file__} python={sys.executable} "
    f"version={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    file=sys.stderr,
    flush=True,
)

app = create_app()


if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("API_LISTEN_ADDRESS", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    log.info("Starting API server on %s:%d...", host, port)
    serve(app, host=host, port=port, threads=20)
