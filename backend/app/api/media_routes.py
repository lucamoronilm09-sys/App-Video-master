"""Endpoint dedicati alla gestione dei media caricati nel progetto."""
from __future__ import annotations

from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.routes import (
    ALLOWED_IMAGE_EXTS,
    ALLOWED_VIDEO_EXTS,
    MAX_FILE_SIZE_BYTES,
    _ensure_path_within_project,
    _get_state_or_404,
    _validate_magic_bytes,
)
from app.agents import intake, normalizer, sequence
from app.pipeline import state as state_store

router = APIRouter()


async def _prepare_uploaded_media(project_id: str, file: UploadFile) -> tuple[Path, str]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTS and ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"Estensione non supportata: {ext or '(nessuna estensione)'}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"File troppo grande: massimo {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB")
    if not _validate_magic_bytes(content, ext):
        raise HTTPException(status_code=400, detail="Contenuto file non corrisponde all'estensione")

    media_dir = state_store.media_dir(project_id)
    media_dir.mkdir(parents=True, exist_ok=True)
    dest = media_dir / f"{uuid.uuid4().hex[:8]}{ext}"
    dest.write_bytes(content)
    return dest, ext


@router.patch("/projects/{project_id}/media/{media_id}/replace")
async def replace_media(project_id: str, media_id: str, file: UploadFile = File(...)) -> dict:
    """Sostituisce una foto/video mantenendo lo stesso slot nella timeline.

    Il nuovo file viene analizzato come un normale upload; mantiene l'id e la
    posizione della clip precedente, mentre durata, orientamento, qualità,
    Vision e gli altri metadata vengono ricalcolati.
    """
    state = _get_state_or_404(project_id)
    media = state.get("media", [])
    target_index = next((i for i, m in enumerate(media) if m.get("id") == media_id), None)
    if target_index is None:
        raise HTTPException(status_code=404, detail="Media non trovato")

    target = media[target_index]
    old_path = Path(str(target.get("path"))) if target.get("path") else None
    new_path, _ = await _prepare_uploaded_media(project_id, file)

    staging = [{
        "path": str(new_path),
        "source": "local",
        "drive_file_id": None,
    }]
    analysed = await intake._process_one(new_path, staging[0]["source"], staging[0]["drive_file_id"])
    if not analysed or "error" in analysed:
        new_path.unlink(missing_ok=True)
        detail = (analysed or {}).get("error", {}).get("message", "analisi del nuovo media fallita")
        raise HTTPException(status_code=400, detail=detail)

    # L'identità e la posizione della clip restano quelle dell'utente.
    analysed["id"] = media_id
    analysed["order_index"] = int(target.get("order_index", target_index))
    state["media"][target_index] = analysed

    # Il contenuto è nuovo: nessun override relativo al vecchio file deve essere
    # ereditato, perché durata e tipo possono essere cambiati (foto <-> video).
    state.setdefault("clip_overrides", {}).pop(media_id, None)
    state["edit_decision_list"] = []
    state["render_manifest"] = None
    state["qa_report"] = None

    # Cache preview e render precedenti devono essere rigenerati.
    thumbs = state_store.thumbs_dir(project_id)
    for thumb in thumbs.glob(f"{media_id}_w*.jpg") if thumbs.exists() else []:
        thumb.unlink(missing_ok=True)
    output = state_store.output_dir(project_id)
    if output.exists():
        for child in output.iterdir():
            try:
                shutil.rmtree(child) if child.is_dir() else child.unlink(missing_ok=True)
            except OSError:
                pass

    state = await normalizer.run(state)
    state = await sequence.run(state)
    state_store.save_state(state)

    if old_path:
        try:
            old_resolved = _ensure_path_within_project(project_id, old_path)
            if old_resolved != new_path and old_resolved.is_file():
                old_resolved.unlink()
        except HTTPException:
            raise
        except OSError:
            pass

    return state


@router.delete("/projects/{project_id}/media/{media_id}")
def delete_media(project_id: str, media_id: str) -> dict:
    """Elimina definitivamente una foto/video dal progetto.

    La rimozione invalida il montaggio e l'eventuale render precedente, perché
    entrambi potrebbero contenere la clip eliminata. Vengono rimossi anche il
    file originale e le anteprime cache associate.
    """
    state = _get_state_or_404(project_id)
    media = state.get("media", [])
    target = next((m for m in media if m.get("id") == media_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Media non trovato")

    raw_path = target.get("path")
    if raw_path:
        source = Path(raw_path)
        if not source.is_absolute():
            source = state_store.project_dir(project_id) / source
        try:
            resolved = _ensure_path_within_project(project_id, source)
            if resolved.is_file():
                resolved.unlink()
        except HTTPException:
            raise
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Impossibile eliminare il file media: {exc}") from None

    thumbs = state_store.thumbs_dir(project_id)
    if thumbs.exists():
        for thumb in thumbs.glob(f"{media_id}_w*.jpg"):
            try:
                thumb.unlink(missing_ok=True)
            except OSError:
                pass

    state["media"] = [m for m in media if m.get("id") != media_id]
    for index, item in enumerate(state["media"]):
        item["order_index"] = index

    state.setdefault("clip_overrides", {}).pop(media_id, None)
    state["edit_decision_list"] = []
    state["render_manifest"] = None
    state["qa_report"] = None

    output = state_store.output_dir(project_id)
    if output.exists():
        for child in output.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass

    state_store.save_state(state)
    return {
        "message": "Media eliminato con successo",
        "project_id": project_id,
        "media_id": media_id,
        "media_count": len(state["media"]),
        "state": state,
    }
