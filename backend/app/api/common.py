"""Funzioni e helper condivisi tra i router API.

Questo modulo contiene utility utilizzate da più router per evitare
import circolari e accoppiamento indesiderato tra moduli.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.pipeline import state as state_store
from app.pipeline.orchestrator import run_stages as _orch_run_stages
from app.jobs import manager as jobs

# === SECURITY: Limiti e validazione ===
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500MB

ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".mts"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tiff", ".tif", ".gif"}

# Magic bytes per validazione contenuto reale
VIDEO_MAGIC = {
    b"\x00\x00\x00": "ftyp",
    b"\x1A\x45\xDF\xA3": "webm/mkv",
}
IMAGE_MAGIC = {
    b"\xFF\xD8\xFF": "jpeg", 
    b"\x89\x50\x4E\x47": "png",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",  # WebP usa RIFF header
}


def get_state_or_404(project_id: str) -> dict:
    """Carica lo stato del progetto o solleva HTTPException 404.
    
    Args:
        project_id: ID del progetto da caricare.
        
    Returns:
        Il dizionario dello stato del progetto.
        
    Raises:
        HTTPException: 404 se il progetto non esiste.
    """
    try:
        return state_store.load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Progetto non trovato") from None


async def run_pipeline_stages(state: dict, stages) -> dict:
    """Esegue una sequenza di stage della pipeline.
    
    Al primo errore salva lo stato corrente e solleva HTTPException 500.
    Gli errori e i log dei failed sono già registrati dal runner.
    
    Args:
        state: Lo stato corrente del progetto.
        stages: Sequenza di (nome_stage, funzione_stage) da eseguire.
        
    Returns:
        Lo stato aggiornato dopo l'esecuzione degli stage.
        
    Raises:
        HTTPException: 500 se un fallimento si verifica durante l'esecuzione.
    """
    try:
        return await _orch_run_stages(state, list(stages))
    except HTTPException:
        raise
    except Exception as exc:
        state_store.save_state(state)
        raise HTTPException(status_code=500, detail=f"{exc}") from None


def public_job_response(job: dict) -> dict:
    """Trasforma un oggetto job interno in formato pubblico per le API response.
    
    Args:
        job: Il dizionario del job interno.
        
    Returns:
        Un dizionario con i campi pubblici del job.
    """
    status_map = {"queued": "pending", "running": "running", "done": "completed", "failed": "failed"}
    return {
        "id": job.get("job_id") or job.get("id"),
        "kind": job.get("kind"),
        "status": status_map.get(job.get("status"), job.get("status")),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "progress": job.get("progress"),
    }


def build_progress_payload(state: dict) -> dict:
    """Crea un payload leggero per il polling dei progressi della pipeline.
    
    Args:
        state: Lo stato corrente del progetto.
        
    Returns:
        Un dizionario con informazioni sintetiche sui progressi.
    """
    manifest = state.get("render_manifest") or {}
    qa = state.get("qa_report") or {}
    return {
        "pipeline_log": (state.get("pipeline_log") or [])[-100:],
        "errors_count": len(state.get("errors", [])),
        "media_count": len(state.get("media", [])),
        "has_audio": bool((state.get("audio") or {}).get("path")),
        "has_edit": bool(state.get("edit_decision_list")),
        "has_render": bool(manifest.get("status") == "done"),
        "qa_status": qa.get("status"),
        "updated_at": state.get("updated_at", 0),
        "jobs": [public_job_response(j) for j in jobs.recent_for_project(state.get("project_id", ""), 5)],
    }


def ensure_path_within_project(project_id: str, path: Path) -> Path:
    """Verifica che un path sia dentro la sandbox del progetto.
    
    SECURITY: previene path-traversal attacks risolvendo il path assoluto
    e verificando che sia contenuto nella root del progetto.
    
    Args:
        project_id: ID del progetto che definisce la sandbox.
        path: Il percorso da verificare.
        
    Returns:
        Il percorso risolto e verificato.
        
    Raises:
        HTTPException: 404 se il percorso non è valido, 403 se fuori sandbox.
    """
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Percorso non valido")
    
    project_root = state_store.project_dir(project_id).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Accesso negato: percorso fuori sandbox")
    
    return resolved


def validate_magic_bytes(content: bytes, ext: str) -> bool:
    """Valida che il contenuto del file corrisponda ai magic bytes attesi.
    
    Args:
        content: I primi byte del file da validare.
        ext: L'estensione del file.
        
    Returns:
        True se i magic bytes corrispondono all'estensione, False altrimenti.
    """
    if not content:
        return False
    
    # Video: cerca signature ftyp o webm/mkv
    if ext in ALLOWED_VIDEO_EXTS:
        for magic, fmt in VIDEO_MAGIC.items():
            if content.startswith(magic):
                return True
        # Fallback: presenza di byte nulli tipici container video
        if b'\x00' in content[:512]:
            return True
    
    # Immagini: validazione per formati specifici
    if ext in ALLOWED_IMAGE_EXTS:
        # Controllo magic bytes specifici
        for magic, fmt in IMAGE_MAGIC.items():
            if content.startswith(magic):
                return True
        
        # JPEG: FF D8 FF
        if content.startswith(b"\xFF\xD8"):
            return True
        
        # PNG: 89 50 4E 47 0D 0A 1A 0A
        if content.startswith(b"\x89PNG"):
            return True
        
        # GIF: GIF87a o GIF89a
        if content.startswith(b"GIF8"):
            return True
        
        # WebP: RIFF....WEBP
        if content.startswith(b"RIFF") and b"WEBP" in content[:32]:
            return True
        
        # BMP: BM header
        if content.startswith(b"BM"):
            return True
        
        # TIFF: II (little-endian) o MM (big-endian)
        if content.startswith(b"II\x2A\x00") or content.startswith(b"MM\x00\x2A"):
            return True
        
        # HEIC/HEIF: ftyp box tipico
        if b"ftyp" in content[:32] or b"heic" in content[:64]:
            return True
    
    return False
