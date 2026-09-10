"""Project State: unico canale di comunicazione tra gli agenti (JSON su filesystem).

Il formato rispetta lo schema definito in architettura-video-maker-ia.md (sez. 4),
piu' due campi operativi documentati in PROGRESS.md:
- "errors": lista di errori non bloccanti (usata gia' da Intake, RF-architettura);
- "pipeline_log": traccia degli step eseguiti (per la UI di avanzamento in M8).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import (
    PROJECTS_DIR,
    MEDIA_SUBDIR,
    AUDIO_SUBDIR,
    OUTPUT_SUBDIR,
    THUMBS_SUBDIR,
    DEFAULT_OUTPUT_SPEC,
    DEFAULT_STYLE_PROFILE,
)

SCHEMA_VERSION = 1


def new_project_state() -> dict:
    pid = uuid.uuid4().hex[:8]
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": pid,
        "name": "Nuovo progetto",
        "media": [],
        "audio_tracks": [],
        "audio": {
            "path": None,
            "duration_sec": 0.0,
            "bpm": 0.0,
            "beat_markers_sec": [],
            "energy_curve": [],
        },
        "style_profile": DEFAULT_STYLE_PROFILE,
        "output_spec": dict(DEFAULT_OUTPUT_SPEC),
        "edit_decision_list": [],
        "clip_overrides": {},
        "render_manifest": None,
        "qa_report": None,
        "errors": [],
        "pipeline_log": [],
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def media_dir(project_id: str) -> Path:
    return project_dir(project_id) / MEDIA_SUBDIR


def audio_dir(project_id: str) -> Path:
    return project_dir(project_id) / AUDIO_SUBDIR


def output_dir(project_id: str) -> Path:
    return project_dir(project_id) / OUTPUT_SUBDIR


def thumbs_dir(project_id: str) -> Path:
    return project_dir(project_id) / THUMBS_SUBDIR


def ensure_project_dirs(project_id: str) -> Path:
    """Crea (se assenti) le cartella di lavoro del progetto."""
    d = project_dir(project_id)
    for sub in (MEDIA_SUBDIR, AUDIO_SUBDIR, OUTPUT_SUBDIR, THUMBS_SUBDIR):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def state_path(project_id: str) -> Path:
    return project_dir(project_id) / "state.json"


def save_state(state: dict) -> dict:
    ensure_project_dirs(state["project_id"])
    state["updated_at"] = time.time()
    state_path(state["project_id"]).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return state


def load_state(project_id: str) -> dict:
    p = state_path(project_id)
    if not p.exists():
        raise FileNotFoundError(f"Progetto inesistente: {project_id}")
    state = json.loads(p.read_text(encoding="utf-8"))
    # Compatibilita' con progetti creati prima del campo name.
    if not state.get("name"):
        state["name"] = "Nuovo progetto"
    return state


def list_projects() -> list[dict[str, Any]]:
    if not PROJECTS_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted(PROJECTS_DIR.iterdir()):
        sp = d / "state.json"
        if not sp.exists():
            continue
        try:
            st = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            continue
        manifest = st.get("render_manifest") or {}
        out.append(
            {
                "project_id": st.get("project_id"),
                "name": st.get("name") or "Nuovo progetto",
                "media_count": len(st.get("media", [])),
                "has_audio": bool((st.get("audio") or {}).get("path")),
                "has_render": manifest.get("status") == "done",
                "updated_at": st.get("updated_at"),
            }
        )
    return out
