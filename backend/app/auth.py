"""Middleware di autenticazione API key (opzionale)."""
import os
from fastapi import Request, HTTPException
from fastapi.security import APIKeyHeader

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def _get_api_key() -> str | None:
    return os.getenv("API_KEY") or None

async def verify_api_key(request: Request) -> None:
    """Verifica la API key se API_KEY è configurata."""
    expected = _get_api_key()
    if not expected:
        return  # auth disabilitata in sviluppo
    provided = request.headers.get(API_KEY_NAME)
    if not provided or provided != expected:
        raise HTTPException(
            status_code=401,
            detail="API key mancante o non valida",
            headers={"WWW-Authenticate": "ApiKey"},
        )
