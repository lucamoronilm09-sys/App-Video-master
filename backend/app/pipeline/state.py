"""Project State: unico canale di comunicazione tra gli agenti (JSON su filesystem)."""
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
from app.validators import InvalidProjectIDError, validate_project_id

SCHEMA_VERSION = 1


def new_project_state() -> dict:
    pid = uuid.uuid4().hex[:8]
    now = time.time()
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": pid,
        "name": "Nuovo progetto",
        "user_prompt": "",
        "media": [],
        "audio_tracks": [],
        "audio": {"path": None, "duration_sec": 0.0, "bpm": 0.0, "beat_markers_sec": [], "energy_curve": []},
        "style_profile": DEFAULT_STYLE_PROFILE,
        "output_spec": dict(DEFAULT_OUTPUT_SPEC),
        "edit_decision_list": [],
        "story_chapters": [],
        "music_structure": {},
        "clip_overrides": {},
        "ai_feedback": None,
        "ai_feedback_history": [],
        "render_manifest": None,
        "qa_report": None,
        "errors": [],
        "pipeline_log": [],
        "created_at": now,
        "updated_at": now,
    }


def project_dir(project_id: str) -> Path:
    validate_project_id(project_id)
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
    validate_project_id(project_id)
    d = project_dir(project_id)
    for sub in (MEDIA_SUBDIR, AUDIO_SUBDIR, OUTPUT_SUBDIR, THUMBS_SUBDIR):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def state_path(project_id: str) -> Path:
    return project_dir(project_id) / "state.json"


def save_state(state: dict) -> dict:
    from app.logging_config import get_logger, safe_log_dict

    logger = get_logger(__name__)
    project_id = state["project_id"]
    ensure_project_dirs(project_id)
    state["updated_at"] = time.time()
    p = state_path(project_id)
    tmp = p.with_suffix(".tmp.json")
    try:
        log_data = safe_log_dict({"project_id": project_id, "media_count": len(state.get("media", [])), "has_render": bool(state.get("render_manifest"))})
        logger.debug("Salvataggio stato per %s: %s", project_id, log_data)
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
        logger.info("Stato salvato per progetto %s", project_id)
    except Exception as exc:
        logger.error("Errore nel salvataggio stato per %s: %s", project_id, exc, exc_info=True)
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        raise
    return state


def load_state(project_id: str) -> dict:
    """Carica lo stato; un ID malformato viene trattato come progetto inesistente."""
    try:
        validate_project_id(project_id)
    except InvalidProjectIDError as exc:
        raise FileNotFoundError(f"Progetto inesistente: {project_id}") from exc
    p = state_path(project_id)
    if not p.exists():
        raise FileNotFoundError(f"Progetto inesistente: {project_id}")
    state = json.loads(p.read_text(encoding="utf-8"))
    defaults = {"name": "Nuovo progetto", "user_prompt": "", "story_chapters": [], "music_structure": {}, "ai_feedback": None, "ai_feedback_history": []}
    for key, value in defaults.items():
        if key not in state:
            state[key] = value
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
        out.append({"project_id": st.get("project_id"), "name": st.get("name") or "Nuovo progetto", "media_count": len(st.get("media", [])), "has_audio": bool((st.get("audio") or {}).get("path")), "has_render": manifest.get("status") == "done", "updated_at": st.get("updated_at")})
    return out
