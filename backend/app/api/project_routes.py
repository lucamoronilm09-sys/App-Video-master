"""API per metadati, feedback e duplicazione dei progetti."""
from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.schemas import ProjectFeedbackRequest, ProjectState, UpdateProjectRequest
from app.pipeline import state as state_store

router = APIRouter()


def _get_state_or_404(project_id: str) -> dict:
    try:
        return state_store.load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Progetto non trovato") from None


@router.patch("/projects/{project_id}", response_model=ProjectState)
def update_project(project_id: str, body: UpdateProjectRequest) -> dict:
    state = _get_state_or_404(project_id)
    if body.name is not None:
        name = " ".join(body.name.strip().split())
        if not name:
            raise HTTPException(status_code=400, detail="Il nome del progetto non può essere vuoto")
        state["name"] = name
    if body.user_prompt is not None:
        state["user_prompt"] = body.user_prompt.strip()
        # Un nuovo prompt invalida il vecchio piano: la prossima generazione lo ricalcola.
        state["qa_report"] = None
    if body.style_profile is not None:
        state["style_profile"] = body.style_profile.strip()[:60] or "album_memory"
        state["qa_report"] = None
    state_store.save_state(state)
    return state


@router.post("/projects/{project_id}/duplicate", response_model=ProjectState, status_code=201)
def duplicate_project(project_id: str) -> dict:
    """Crea una copia indipendente del progetto, media inclusi."""
    source = _get_state_or_404(project_id)
    new_id = uuid.uuid4().hex[:8]
    source_dir = state_store.project_dir(project_id)
    target_dir = state_store.project_dir(new_id)
    if target_dir.exists():
        raise HTTPException(status_code=500, detail="Impossibile creare l'ID del progetto duplicato")
    shutil.copytree(source_dir, target_dir)

    state = dict(source)
    state["project_id"] = new_id
    state["name"] = f"{source.get('name') or 'Nuovo progetto'} (copia)"
    now = time.time()
    state["created_at"] = now
    state["updated_at"] = now
    state_store.save_state(state)

    # I path assoluti del JSON originale restano validi solo se indicano la nuova cartella.
    old_root = str(source_dir.resolve())
    new_root = str(target_dir.resolve())

    def rewrite(value):
        if isinstance(value, str):
            return value.replace(old_root, new_root)
        if isinstance(value, list):
            return [rewrite(v) for v in value]
        if isinstance(value, dict):
            return {k: rewrite(v) for k, v in value.items()}
        return value

    state = rewrite(state)
    state_store.save_state(state)
    return state


@router.post("/projects/{project_id}/feedback", response_model=ProjectState)
def save_feedback(project_id: str, body: ProjectFeedbackRequest) -> dict:
    state = _get_state_or_404(project_id)
    feedback = {
        "rating": body.rating,
        "reasons": [r.strip() for r in body.reasons if r.strip()][:8],
        "note": body.note.strip(),
        "created_at": time.time(),
    }
    state["ai_feedback"] = feedback
    history = list(state.get("ai_feedback_history") or [])
    history.append(feedback)
    state["ai_feedback_history"] = history[-20:]
    state["qa_report"] = None
    state_store.save_state(state)
    return state
