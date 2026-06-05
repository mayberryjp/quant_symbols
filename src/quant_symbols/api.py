"""Read-only backend API for symbol sync health."""

from __future__ import annotations

import os
from typing import Any


def create_app(*, engine: Any | None = None) -> Any:
    """Create the FastAPI app.

    The import is local so CLI-only usage does not require FastAPI at import time.
    """

    try:
        from fastapi import FastAPI, HTTPException
    except ModuleNotFoundError as exc:
        raise RuntimeError("FastAPI is required for quant_symbols.api") from exc

    app = FastAPI(title="quant_symbols")

    @app.get("/jobs/symbol-sync/latest")
    def latest_symbol_sync_health() -> dict[str, Any]:
        from quant_symbols.symbol_master.massive_sync import MassiveSymbolSyncJob

        health = MassiveSymbolSyncJob(engine=engine or _engine()).latest_health()
        if health is None:
            raise HTTPException(status_code=404, detail="symbol sync health not found")
        return health

    return app


def _engine() -> Any:
    try:
        from sqlalchemy import create_engine
    except ModuleNotFoundError as exc:
        raise RuntimeError("SQLAlchemy is required for database-backed API routes") from exc
    return create_engine(
        os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://quant:quant_dev_password@localhost:5432/quant",
        ),
        pool_pre_ping=True,
    )


app = create_app()
