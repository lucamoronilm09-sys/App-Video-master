"""Test autenticazione API key."""
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

# Usa raise_server_exceptions=False per permettere ai middleware di
# restituire risposte HTTP 401/403 senza sollevare eccezioni Python
client = TestClient(app, raise_server_exceptions=False)


def test_health_no_auth_required():
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_no_api_key_configured_allows_access():
    with patch.dict("os.environ", {}, clear=False):
        os.environ.pop("API_KEY", None)
        from importlib import reload
        import app.main

        reload(app.main)
        test_client = TestClient(app.main.app, raise_server_exceptions=False)
        resp = test_client.get("/api/projects")
        assert resp.status_code == 200


def test_api_key_required_when_configured():
    with patch.dict("os.environ", {"API_KEY": "test-key-123"}):
        from importlib import reload
        import app.main

        reload(app.main)
        test_client = TestClient(app.main.app, raise_server_exceptions=False)
        resp = test_client.get("/api/projects")
        assert resp.status_code == 401


def test_valid_api_key_allows_access():
    with patch.dict("os.environ", {"API_KEY": "test-key-123"}):
        from importlib import reload
        import app.main

        reload(app.main)
        test_client = TestClient(app.main.app, raise_server_exceptions=False)
        resp = test_client.get("/api/projects", headers={"X-API-Key": "test-key-123"})
        assert resp.status_code == 200


def test_wrong_api_key_rejected():
    with patch.dict("os.environ", {"API_KEY": "test-key-123"}):
        from importlib import reload
        import app.main

        reload(app.main)
        test_client = TestClient(app.main.app, raise_server_exceptions=False)
        resp = test_client.get("/api/projects", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401


def test_api_key_allowed_in_cors_preflight():
    with patch.dict(
        "os.environ",
        {
            "API_KEY": "test-key-123",
            "CORS_ORIGINS": "http://localhost:3000",
        },
    ):
        from importlib import reload
        import app.main

        reload(app.main)
        test_client = TestClient(app.main.app, raise_server_exceptions=False)
        resp = test_client.options(
            "/api/projects",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
        )
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert "x-api-key" in resp.headers["access-control-allow-headers"].lower()
