"""Endpoint dedicati alla gestione dei media caricati nel progetto."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.routes import _ensure_path_within_project, _get_state_or_404
from app.pipeline import state as state_store

router = APIRouter()


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

    # Elimina il file sorgente, solo se resta nella sandbox del progetto.
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

    # Rimuove tutte le thumbnail generate per questo media e qualsiasi larghezza.
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

    # L'EDL è ormai potenzialmente incoerente: ripartirà dal prossimo
    # "Genera montaggio". Gli override della clip eliminata vanno rimossi,
    # quelli delle altre clip restano validi.
    state.setdefault("clip_overrides", {}).pop(media_id, None)
    state["edit_decision_list"] = []
    state["render_manifest"] = None
    state["qa_report"] = None

    # Qualsiasi render esistente può contenere il media cancellato.
    output = state_store.output_dir(project_id)
    if output.exists():
        for child in output.iterdir():
            try:
                if child.is_dir():
                    import shutil
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
