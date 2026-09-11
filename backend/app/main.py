"""Entrypoint FastAPI.

Avvio: uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
(dalla cartella backend/, con il venv attivo)
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.drive import router as drive_router
from app.api.media_routes import router as media_router
from app.api.project_routes import router as project_router
from app.config import PROJECTS_DIR
from app.jobs import manager as jobs


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
        print(f"[jobs] {recovered} job riaccodati dopo riavvio")
    worker = asyncio.create_task(jobs.worker_loop())
    try:
        yield
    finally:
        worker.cancel()


app = FastAPI(title="AI Video Maker", version="1.0.0", lifespan=lifespan)

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
