from __future__ import annotations

import builtins
import importlib
import sys

from fastapi.testclient import TestClient

from quant_symbols.api.app import create_app
from quant_symbols.api.readiness import ReadinessError, ReadinessStatus


def test_health_returns_ok_without_database_access():
    def fail_if_called() -> ReadinessStatus:
        raise AssertionError("readiness check should not be called by /health")

    client = TestClient(create_app(readiness_check=fail_if_called))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "quant-symbols-api"}


def test_api_app_import_does_not_import_sqlalchemy_or_connect(monkeypatch):
    sys.modules.pop("quant_symbols.api.app", None)
    sys.modules.pop("quant_symbols.api.readiness", None)
    sys.modules.pop("quant_symbols.api", None)

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "sqlalchemy" or name.startswith("sqlalchemy."):
            raise AssertionError("API import should not import SQLAlchemy")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module("quant_symbols.api.app")

    assert module.app.title == "quant-symbols-api"


def test_ready_returns_ok_when_readiness_check_succeeds():
    client = TestClient(
        create_app(
            readiness_check=lambda: ReadinessStatus(
                database="ok",
                schema_version="0001_symbol_master_vendor_traceability",
                tables=7,
            )
        )
    )

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "schema_version": "0001_symbol_master_vendor_traceability",
        "tables": 7,
    }


def test_ready_returns_503_when_readiness_check_fails():
    def fail_readiness() -> ReadinessStatus:
        raise ReadinessError("schema_version=old expected=0001_symbol_master_vendor_traceability")

    client = TestClient(create_app(readiness_check=fail_readiness))

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "database": "error",
        "error": "schema_version=old expected=0001_symbol_master_vendor_traceability",
    }


def test_ready_error_redacts_secret_bearing_database_url(monkeypatch):
    database_url = "postgresql+psycopg://user:super-secret@db.example.test:5432/quant"
    monkeypatch.setenv("DATABASE_URL", database_url)

    def fail_readiness() -> ReadinessStatus:
        raise RuntimeError(f"could not connect to {database_url}")

    client = TestClient(create_app(readiness_check=fail_readiness))

    response = client.get("/ready")

    assert response.status_code == 503
    error = response.json()["error"]
    assert "super-secret" not in error
    assert database_url not in error
    assert "user:***@db.example.test:5432/quant" in error
