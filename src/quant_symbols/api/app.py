from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Callable, Dict, Optional, Union

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from typing_extensions import Annotated

from quant_symbols.api.readiness import (
    ReadinessStatus,
    check_database_readiness,
    sanitize_readiness_error,
)
from quant_symbols.api.symbols import (
    SymbolListParams,
    SymbolTickerLookupParams,
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

SERVICE_NAME = "quant-symbols-api"

log = logging.getLogger(SERVICE_NAME)


ReadinessCheck = Callable[[], Union[ReadinessStatus, Dict[str, Any]]]
SymbolList = Callable[[SymbolListParams], Dict[str, Any]]
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


def _status_payload(status: Union[ReadinessStatus, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(status, ReadinessStatus):
        return status.as_json()
    return {"status": "ok", **status}


def create_app(
    readiness_check: ReadinessCheck = check_database_readiness,
    symbol_list: SymbolList = list_symbols,
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
) -> FastAPI:
    api = FastAPI(title=SERVICE_NAME)

    @api.on_event("startup")
    def _configure_logging() -> None:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        log.setLevel(logging.INFO)

    @api.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        method = request.method
        path = request.url.path
        query = str(request.url.query)
        log.info("request_start method=%s path=%s query=%s", method, path, query)
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            log.exception(
                "request_error method=%s path=%s duration_ms=%.1f",
                method, path, duration_ms,
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        log.info(
            "request_end method=%s path=%s status=%d duration_ms=%.1f",
            method, path, response.status_code, duration_ms,
        )
        return response

    @api.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME}

    @api.get("/ready")
    def ready():
        try:
            return _status_payload(readiness_check())
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "database": "error",
                    "error": sanitize_readiness_error(exc, os.environ.get("DATABASE_URL")),
                },
            )

    @api.get("/symbols/by-ticker/{ticker}")
    def symbol_by_ticker_route(
        ticker: str,
        market: str = "stocks",
        locale: str = "us",
        active: bool = True,
    ):
        params = SymbolTickerLookupParams(
            ticker=ticker,
            market=market,
            locale=locale,
            active=active,
        )
        try:
            symbol = symbol_by_ticker(params)
        except Exception as exc:
            return _server_error(exc)
        if symbol is None:
            return _not_found()
        return symbol

    @api.get("/symbols/{symbol_id}/aliases")
    def symbol_aliases_route(symbol_id: int):
        try:
            result = symbol_aliases(symbol_id)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found()
        return result

    @api.get("/symbols/{symbol_id}/vendor-ids")
    def symbol_vendor_ids_route(symbol_id: int):
        try:
            result = symbol_vendor_ids(symbol_id)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found()
        return result

    @api.get("/symbols/{symbol_id}/raw-payloads")
    def symbol_raw_payloads_route(
        symbol_id: int,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        params = RawPayloadListParams(symbol_id=symbol_id, limit=limit, offset=offset)
        try:
            result = symbol_raw_payloads(params)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found()
        return result

    @api.get("/symbols/{symbol_id}")
    def symbol_detail_route(symbol_id: int):
        try:
            symbol = symbol_detail(symbol_id)
        except Exception as exc:
            return _server_error(exc)
        if symbol is None:
            return _not_found()
        return symbol

    @api.get("/vendor-runs")
    def vendor_runs_route(
        vendor: str = "massive",
        endpoint: Optional[str] = None,
        status: Optional[VendorRunStatus] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        params = VendorRunListParams(
            vendor=vendor,
            endpoint=endpoint,
            status=status,
            limit=limit,
            offset=offset,
        )
        try:
            return vendor_runs(params)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/vendor-runs/{run_id}")
    def vendor_run_detail_route(run_id: int):
        try:
            result = vendor_run_detail(run_id)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("vendor run not found")
        return result

    @api.get("/sync/latest")
    def sync_latest_route(
        vendor: str = "massive",
        endpoint: str = "/v3/reference/tickers",
    ):
        params = SyncLatestParams(vendor=vendor, endpoint=endpoint)
        try:
            result = sync_latest(params)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("sync run not found")
        return {"status": "ok", "latest": result}

    @api.get("/sync/runs")
    def sync_runs_route(
        vendor: str = "massive",
        endpoint: str = "/v3/reference/tickers",
        status: Optional[VendorRunStatus] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        params = SyncRunListParams(
            vendor=vendor,
            endpoint=endpoint,
            status=status,
            limit=limit,
            offset=offset,
        )
        try:
            return sync_runs(params)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/sync/runs/{run_id}")
    def sync_run_detail_route(run_id: int):
        try:
            result = sync_run_detail(run_id)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("sync run not found")
        return result

    @api.get("/symbols")
    def symbols(
        active: Optional[bool] = None,
        market: Optional[str] = None,
        locale: Optional[str] = None,
        q: Optional[str] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        params = SymbolListParams(
            active=active,
            market=market,
            locale=locale,
            q=q.strip() if q and q.strip() else None,
            limit=limit,
            offset=offset,
        )
        try:
            return symbol_list(params)
        except Exception as exc:
            return _server_error(exc)

    return api


def _not_found(error: str = "symbol not found") -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"status": "not_found", "error": error},
    )


def _server_error(exc: Exception) -> JSONResponse:
    log.exception("handler_error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": sanitize_readiness_error(exc, os.environ.get("DATABASE_URL")),
        },
    )


app = create_app()
