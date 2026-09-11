"""API Google Drive (M7): OAuth2, browse account, import parallelo nel progetto.

Redirect URI da registrare in Google Cloud Console (URI di reindirizzamento
autorizzati): http://127.0.0.1:8000/api/drive/callback (per sviluppo) oppure
il valore di DRIVE_HOST (per produzione, es. https://api.example.com).
Scope: drive.readonly. Secret/token solo su disco (data/, gitignored).
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from googleapiclient.errors import HttpError

from app.agents import drive_import, intake, normalizer, sequence
from app.api.common import build_progress_payload, get_state_or_404, run_pipeline_stages, public_job_response
from app.api.schemas import DriveCredentialsRequest, DriveImportRequest, ProjectState
from app.jobs import manager as jobs
from app.pipeline import state as state_store
from app.services import drive_client as dc

logger = logging.getLogger(__name__)
router = APIRouter()
DEFAULT_DRIVE_HOST = "http://127.0.0.1:8000"


def _resolve_drive_host(request: Request | None = None) -> str:
    """Resolve the backend host used by Google's OAuth redirect.

    In local development the OAuth redirect MUST stay on the backend (:8000).
    The frontend is served on :3000 and proxies /api requests to FastAPI; using
    the incoming Host header here would incorrectly register localhost:3000 as
    Google's redirect URI. For production, DRIVE_HOST is authoritative.
    """
    env_host = os.getenv("DRIVE_HOST", "").strip()
    if env_host:
        return env_host.rstrip("/")
    return DEFAULT_DRIVE_HOST


def _drive_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, HttpError):
        status = exc.resp.status if hasattr(exc, "resp") and hasattr(exc.resp, "status") else 502
        if status == 401:
            return HTTPException(status_code=401, detail="Sessione Google Drive scaduta: riconnetti l'account e riprova")
        if status == 403:
            return HTTPException(status_code=403, detail=f"Google Drive ha negato l'accesso: {exc}")
        if status == 404:
            return HTTPException(status_code=404, detail=f"File/cartella non trovato su Drive: {exc}")
        if 400 <= status < 500:
            return HTTPException(status_code=status, detail=f"Errore Google Drive: {exc}")
        return HTTPException(status_code=502, detail=f"Errore Google Drive: {exc}")
    if isinstance(exc, TimeoutError):
        return HTTPException(status_code=504, detail="Timeout durante la comunicazione con Google Drive (riprova più tardi)")
    logger.exception("drive: errore non gestito")
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/drive/credentials")
def save_credentials(body: DriveCredentialsRequest) -> dict:
    if not body.client_id.strip() or not body.client_secret.strip():
        raise HTTPException(status_code=400, detail="client_id e client_secret obbligatori")
    dc.save_client_config(body.client_id, body.client_secret)
    dc.disconnect()
    return {"configured": True}


@router.get("/drive/status")
def drive_status() -> dict:
    configured = dc.load_client_config() is not None
    if not configured:
        return {"configured": False, "connected": False, "email": None}
    try:
        service = dc.get_drive_service()
        email = dc.get_account_email(service)
        return {"configured": True, "connected": True, "email": email}
    except Exception:
        return {"configured": True, "connected": False, "email": None}


@router.get("/drive/auth-url")
def drive_auth_url(request: Request) -> dict:
    try:
        host = _resolve_drive_host(request)
        return {"url": dc.get_authorization_url(host)}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


def _callback_page(ok: bool, message: str, status: int = 200) -> HTMLResponse:
    color, title = ("#34d399", "Drive collegato") if ok else ("#f87171", "Errore collegamento")
    if ok:
        script = """
<script>
(function () {
  try {
    if (window.opener && !window.opener.closed) {
      window.opener.postMessage({type: "drive-connected"}, "*");
      setTimeout(function () { window.close(); }, 600);
    } else {
      window.location.href = "http://localhost:3000";
    }
  } catch (e) {
    window.location.href = "http://localhost:3000";
  }
})();
</script>
"""
    else:
        script = ""
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><title>Google Drive</title></head>"
        f"<body style='margin:0;background:#0f172a;color:#e2e8f0;font-family:Arial,sans-serif;"
        f"display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center'>"
        f"<div style='max-width:560px;padding:32px'><h2 style='color:{color}'>{title}</h2>"
        f"<p>{message}</p><p style='color:#94a3b8;font-size:13px'>"
        f"{'La finestra si chiuderà automaticamente.' if ok else 'Chiudi questa finestra e torna all’app.'}</p></div>"
        f"{script}</body></html>", status_code=status)


@router.get("/drive/callback", response_class=HTMLResponse)
def drive_callback(request: Request,
                    code: str | None = Query(default=None),
                    state: str | None = Query(default=None)):
    host = _resolve_drive_host(request)
    if not code:
        return _callback_page(False, "Autorizzazione negata o codice mancante.", 400)
    try:
        dc.exchange_code_and_save(code, state or "", host)
    except Exception as exc:
        return _callback_page(False, f"{exc}", 400)
    return _callback_page(True, "Account collegato con successo.")


@router.post("/drive/disconnect")
def drive_disconnect() -> dict:
    dc.disconnect()
    return {"connected": False}


@router.get("/projects/{project_id}/drive/files")
def drive_files(project_id: str, folder_id: str = "root",
                page_token: str | None = None, page_size: int = 100,
                shared: bool = False) -> dict:
    _get_state_or_404(project_id)
    effective_shared = shared or folder_id == "shared"
    try:
        service = dc.get_drive_service()
        if effective_shared:
            batch = dc.list_shared_with_me(service, page_token, page_size)
            current = {"id": "shared", "name": "Condivisi con me"}
        else:
            batch = dc.list_children(service, folder_id, page_token, page_size)
            current = {"id": "root", "name": "Il mio Drive"} if folder_id == "root" \
                else dc.get_file_meta(service, folder_id)
    except Exception as exc:
        raise _drive_error(exc) from None
    return {"current": current, "entries": batch["entries"],
            "nextPageToken": batch.get("nextPageToken")}


@router.get("/projects/{project_id}/progress")
def project_progress(project_id: str) -> dict:
    """Snapshot leggero per il polling fallback della UI."""
    state = get_state_or_404(project_id)
    return build_progress_payload(state)


@router.post("/projects/{project_id}/drive/import", response_model=ProjectState)
async def drive_import_media(project_id: str, body: DriveImportRequest,
                             background: bool = False) -> dict:
    state = get_state_or_404(project_id)
    if not body.file_ids and not body.folder_ids:
        raise HTTPException(status_code=400, detail="Seleziona almeno un file o una cartella")
    if dc.load_credentials() is None:
        raise HTTPException(status_code=401,
                            detail="Drive non connesso: completa prima il collegamento OAuth")
    if background:
        try:
            job = jobs.submit(project_id, "drive_import",
                              {"file_ids": body.file_ids, "folder_ids": body.folder_ids})
        except jobs.JobExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return JSONResponse(status_code=202, content={"job": public_job_response(job)})
    state["drive_import_request"] = {"file_ids": body.file_ids, "folder_ids": body.folder_ids}
    state = await run_pipeline_stages(state, (("drive_import", drive_import.run),
                                      ("intake", intake.run),
                                      ("normalizer", normalizer.run),
                                      ("sequence", sequence.run)))
    state_store.save_state(state)
    return state
