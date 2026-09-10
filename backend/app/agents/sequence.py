"""Agente 2a: Sequence.

Stima una durata cinematografica per ogni foto usando i segnali visivi
calcolati da Intake: composizione, dettaglio, contrasto, nitidezza, colore
e presenza di persone. Il vincolo è sempre 2.5–5.5s.
L'ordine manuale non viene mai modificato.
"""
from __future__ import annotations

import math
from typing import Any

PHOTO_MIN_SEC = 2.5
PHOTO_MAX_SEC = 5.5
MAX_VIDEO_SEC = 8.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _safe_float(item: dict[str, Any], key: str, default: float) -> float:
    try:
        value = float(item.get(key) if item.get(key) is not None else default)
    except (TypeError, ValueError):
        value = default
    return _clamp01(value)


def _photo_visual_score(item: dict[str, Any]) -> float:
    """Score 0–1 della quantità di informazione visiva da mostrare."""
    composition = _safe_float(item, "composition_score", 0.50)
    detail = _safe_float(item, "detail_score", composition)
    contrast = _safe_float(item, "contrast_score", 0.50)
    sharpness = _safe_float(item, "sharpness_score", 0.50)
    color = _safe_float(item, "color_score", 0.50)

    try:
        faces = max(0, int(item.get("face_count") or 0))
    except (TypeError, ValueError):
        faces = 0
    # 1–4 volti danno un incremento utile senza dominare gli altri segnali.
    face_score = _clamp01(math.log1p(faces) / math.log(5.0))

    score = (
        0.28 * composition
        + 0.24 * detail
        + 0.16 * sharpness
        + 0.12 * contrast
        + 0.08 * color
        + 0.12 * face_score
    )
    return _clamp01(score)


def photo_duration(item: dict[str, Any]) -> float:
    """Durata adattiva sempre compresa tra 2.5 e 5.5 secondi."""
    score = _photo_visual_score(item)

    # Curva morbida: foto semplici ~2.8–3.4s, normali ~3.5–4.3s,
    # immagini ricche/importanti ~4.4–5.5s.
    duration = PHOTO_MIN_SEC + (PHOTO_MAX_SEC - PHOTO_MIN_SEC) * (score ** 0.78)

    faces = max(0, int(item.get("face_count") or 0))
    if faces >= 2:
        duration += min(0.45, 0.10 * (faces - 1))

    if _safe_float(item, "detail_score", 0.50) >= 0.82:
        duration += 0.25
    if _safe_float(item, "composition_score", 0.50) >= 0.85:
        duration += 0.25

    return round(max(PHOTO_MIN_SEC, min(PHOTO_MAX_SEC, duration)), 2)


async def run(project_state: dict) -> dict:
    media_list: list[dict[str, Any]] = project_state.get("media", [])
    clips: list[dict[str, Any]] = []

    for item in media_list:
        if item.get("type") == "photo":
            duration = photo_duration(item)
            item["duration_sec"] = duration
            item["trim_start_sec"] = None
            item["trim_end_sec"] = None
        else:
            dur = float(item.get("duration_sec") or 0.0)
            if dur > MAX_VIDEO_SEC:
                start = round((dur - MAX_VIDEO_SEC) / 2.0, 2)
                item["trim_start_sec"] = start
                item["trim_end_sec"] = round(start + MAX_VIDEO_SEC, 2)
                item["duration_sec"] = MAX_VIDEO_SEC
            else:
                item["trim_start_sec"] = None
                item["trim_end_sec"] = None
        clips.append(dict(item))

    project_state["clips"] = clips
    return project_state
