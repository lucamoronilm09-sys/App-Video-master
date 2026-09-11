"""Entrypoint FastAPI.

Avvio: uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
(dalla cartella backend/, con il venv attivo)
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.logging_config import setup_logging, get_logger, set_request_id
from app.ratelimit import limiter

from app.api.routes import router
from app.api.drive import router as drive_router
from app.api.media_routes import router as media_router
from app.api.project_routes import router as project_router
from app.config import PROJECTS_DIR
from app.jobs import manager as jobs
from app.auth import verify_api_key


# Configura logging all'avvio
setup_logging()
logger = get_logger(__name__)


# Rate limiting globale (non modificare, usato internamente da SlowAPI)


def _parse_cors_origins() -> list[str]:
    """Legge gli origini CORS consentiti dalla variabile d'ambiente CORS_ORIGINS.

    Formato: lista separata da virgole (es. "https://app.example.com,http://localhost:3000").
    Se non impostata, ritorna i default di sviluppo (localhost/127.0.0.1 su porte 3000/8000).
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if origins:
            return origins
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    recovered = jobs.recover()
    if recovered:
        logger.info("%d job riaccodati dopo riavvio", recovered)
    worker = asyncio.create_task(jobs.worker_loop())
    try:
        yield
    finally:
        worker.cancel()
        logger.info("Worker loop cancellato durante shutdown")


app = FastAPI(title="AI Video Maker", version="1.0.0", lifespan=lifespan)

# Configura rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Auth middleware: opzionale, attiva solo se API_KEY è impostata
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Genera request_id per tracciamento
    request_id = str(uuid.uuid4())[:8]
    set_request_id(request_id)
    
    # Skip docs e openapi (sempre pubblici per documentazione)
    if (request.url.path.startswith("/docs")
        or request.url.path.startswith("/openapi.json")):
        return await call_next(request)
    
    try:
        # Verifica API key (include skip automatico per OPTIONS preflight)
        await verify_api_key(request)
    except HTTPException as exc:
        # Ritorna direttamente la risposta di errore senza chiamare call_next
        from fastapi.responses import JSONResponse
        logger.warning(
            "Richiesta %s bloccata: %s %s - %d",
            request_id, request.method, request.url.path, exc.status_code
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX"),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

app.include_router(router, prefix="/api")
app.include_router(drive_router, prefix="/api")
app.include_router(media_router, prefix="/api")
app.include_router(project_router, prefix="/api")
