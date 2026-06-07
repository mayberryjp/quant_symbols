from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional, Union

from fastapi import FastAPI, Query
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

SERVICE_NAME = "quant-symbols-api"


ReadinessCheck = Callable[[], Union[ReadinessStatus, Dict[str, Any]]]
SymbolList = Callable[[SymbolListParams], Dict[str, Any]]
SymbolDetail = Callable[[int], Optional[Dict[str, Any]]]
SymbolByTicker = Callable[[SymbolTickerLookupParams], Optional[Dict[str, Any]]]


def _status_payload(status: Union[ReadinessStatus, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(status, ReadinessStatus):
        return status.as_json()
    return {"status": "ok", **status}


def create_app(
    readiness_check: ReadinessCheck = check_database_readiness,
    symbol_list: SymbolList = list_symbols,
    symbol_detail: SymbolDetail = get_symbol_by_id,
    symbol_by_ticker: SymbolByTicker = get_symbol_by_ticker,
) -> FastAPI:
    api = FastAPI(title=SERVICE_NAME)

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

    @api.get("/symbols/{symbol_id}")
    def symbol_detail_route(symbol_id: int):
        try:
            symbol = symbol_detail(symbol_id)
        except Exception as exc:
            return _server_error(exc)
        if symbol is None:
            return _not_found()
        return symbol

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


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"status": "not_found", "error": "symbol not found"},
    )


def _server_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": sanitize_readiness_error(exc, os.environ.get("DATABASE_URL")),
        },
    )


app = create_app()
