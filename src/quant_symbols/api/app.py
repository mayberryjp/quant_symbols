from __future__ import annotations

import os
from typing import Any, Callable, Dict, Union

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from quant_symbols.api.readiness import (
    ReadinessStatus,
    check_database_readiness,
    sanitize_readiness_error,
)

SERVICE_NAME = "quant-symbols-api"


ReadinessCheck = Callable[[], Union[ReadinessStatus, Dict[str, Any]]]


def _status_payload(status: Union[ReadinessStatus, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(status, ReadinessStatus):
        return status.as_json()
    return {"status": "ok", **status}


def create_app(readiness_check: ReadinessCheck = check_database_readiness) -> FastAPI:
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

    return api


app = create_app()
