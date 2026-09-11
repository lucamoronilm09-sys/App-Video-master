"""Agente clip_overrides: applica le scelte manuali dell'utente sull'EDL.

Sta tra Edit Director e Timeline Compiler nelle catene edit/render (e nel
retry QA): il regista rigenera il piano, poi questo agente riapplica gli
override salvati in state["clip_overrides"] {media_id: {duration_sec?,
transition_out?, ken_burns?}} e ricalcola gli start. Senza override è un
no-op (l'output del Director passa invariato, idempotenza preservata).

Regole (stesse della validazione endpoint, qui come difesa in profondità):
- duration foto 1.0-12.0s; video 0.5s-sorgente con trim ricentrato;
- transition_out 0.0 (stacco voluto dall'utente) - 1.5s, propagata anche
  come transition_in della clip successiva; prima/ultima restano 0;
- ken_burns: movimento (o "static") con parametri deterministici, solo foto.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

from app.agents import edit_director
from app.agents.timeline_core import compute_timeline, edl_to_timeline_entries

PHOTO_MANUAL_MIN_SEC = 1.0
PHOTO_MANUAL_MAX_SEC = 12.0
VIDEO_MANUAL_MIN_SEC = 0.5
TRANS_MANUAL_MAX_SEC = 1.5


def _rng(project_id: str, media_id: str) -> random.Random:
    seed = hashlib.sha256(f"{project_id}|{media_id}".encode("utf-8")).digest()
    return random.Random(seed)


def static_ken_burns() -> dict[str, Any]:
    return {"movement": "static", "zoom_from": 1.0, "zoom_to": 1.0,
            "pan_x_from": 0.5, "pan_x_to": 0.5, "pan_y_from": 0.5, "pan_y_to": 0.5}


def ken_burns_for(movement: str, project_id: str, media_id: str) -> dict[str, Any]:
    """Parametri Ken Burns deterministici per un movimento scelto dall'utente."""
    if movement == "static":
        return static_ken_burns()
    if movement not in edit_director.MOVEMENTS:
        raise ValueError(f"movimento sconosciuto: {movement}")
    return edit_director._ken_burns_params(movement, _rng(project_id, media_id))


def apply_override_to_media(media_item: dict, duration_sec: float) -> None:
    """Per i video ricentra il trim sulla nuova durata (validata dal chiamante)."""
    if media_item.get("type") != "video":
        return
    src = float(media_item.get("duration_sec") or 0.0)
    if not (VIDEO_MANUAL_MIN_SEC <= duration_sec <= src):
        raise ValueError(
            f"durata video {duration_sec}s fuori [0.5, {src:.1f}]s (sorgente)")
    start = round(min(max((src - duration_sec) / 2.0, 0.0), src - duration_sec), 2)
    media_item["trim_start_sec"] = start
    media_item["trim_end_sec"] = round(start + duration_sec, 2)


def _check_transition(value: float, is_last: bool) -> float:
    t = round(float(value), 2)
    if is_last and t != 0.0:
        raise ValueError("l'ultima clip non può avere transizione in uscita (deve restare 0)")
    if t != 0.0 and not (0.0 < t <= TRANS_MANUAL_MAX_SEC):
        raise ValueError(f"transizione {t}s fuori [0.0, {TRANS_MANUAL_MAX_SEC}]s")
    return t


async def run(project_state: dict) -> dict:
    edl_raw: list[dict[str, Any]] = project_state.get("edit_decision_list", [])
    if not edl_raw:
        return project_state
    overrides: dict[str, dict] = project_state.get("clip_overrides") or {}
    if not overrides:
        return project_state  # no-op: il piano del Director resta intatto

    media_by_id = {m["id"]: m for m in project_state.get("media", [])}
    pid = str(project_state.get("project_id", ""))
    n = len(edl_raw)
    
    # Lavora su una copia dell'EDL per applicare gli override
    edl = [dict(e) for e in edl_raw]
    
    for i, e in enumerate(edl):
        ov = overrides.get(e.get("media_id", "")) or {}
        if not ov:
            continue
        m = media_by_id.get(e["media_id"])
        if m is None:
            raise ValueError(f"override su media inesistente: {e['media_id']}")
        if "duration_sec" in ov and ov["duration_sec"] is not None:
            d = round(float(ov["duration_sec"]), 2)
            if m.get("type") == "photo":
                if not (PHOTO_MANUAL_MIN_SEC <= d <= PHOTO_MANUAL_MAX_SEC):
                    raise ValueError(
                        f"durata foto {d}s fuori [{PHOTO_MANUAL_MIN_SEC}, "
                        f"{PHOTO_MANUAL_MAX_SEC}]s")
                e["duration_sec"] = d
            else:
                apply_override_to_media(m, d)
                e["duration_sec"] = d
        if "transition_out" in ov and ov["transition_out"] is not None:
            t = _check_transition(ov["transition_out"], is_last=(i == n - 1))
            e["transition_out"] = t
            # La coerenza transition_out/transition_in verrà gestita da compute_timeline
        if "ken_burns" in ov and ov["ken_burns"] is not None:
            if m.get("type") != "photo":
                raise ValueError("ken_burns assegnabile solo alle foto")
            e["ken_burns"] = ken_burns_for(str(ov["ken_burns"]), pid, str(m["id"]))

    # Usa la funzione centrale per ricalcolare start, transizioni coerenti e total_sec
    fps = 30  # default FPS per la quantizzazione
    computed_entries, total_sec = compute_timeline(edl, fps=fps)
    edl_coherent = edl_to_timeline_entries(edl, computed_entries)
    
    project_state["edit_decision_list"] = edl_coherent
    return project_state
