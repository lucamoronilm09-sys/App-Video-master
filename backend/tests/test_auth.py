"""Test autenticazione API key."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_no_auth_required():
    resp = client.get("/api/health")
    assert resp.status_code == 200

def test_no_api_key_configured_allows_access():
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("API_KEY", None)
        resp = client.get("/api/projects")
        assert resp.status_code == 200

def test_api_key_required_when_configured():
    with patch.dict("os.environ", {"API_KEY": "test-key-123"}):
        resp = client.get("/api/projects")
        assert resp.status_code == 401
        
def test_valid_api_key_allows_access():
    with patch.dict("os.environ", {"API_KEY": "test-key-123"}):
        resp = client.get("/api/projects", headers={"X-API-Key": "test-key-123"})
        assert resp.status_code == 200

def test_wrong_api_key_rejected():
    with patch.dict("os.environ", {"API_KEY": "test-key-123"}):
        resp = client.get("/api/projects", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401
