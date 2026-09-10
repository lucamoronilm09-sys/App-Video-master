"""API per metadati del progetto."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas import ProjectState, UpdateProjectRequest
from app.pipeline import state as state_store

router = APIRouter()


def _get_state_or_404(project_id: str) -> dict:
    try:
        return state_store.load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Progetto non trovato") from None


@router.patch("/projects/{project_id}", response_model=ProjectState)
def update_project(project_id: str, body: UpdateProjectRequest) -> dict:
    """Aggiorna il nome visualizzato del progetto."""
    state = _get_state_or_404(project_id)
    name = " ".join(body.name.strip().split())
    if not name:
        raise HTTPException(status_code=400, detail="Il nome del progetto non può essere vuoto")
    state["name"] = name
    state_store.save_state(state)
    return state
