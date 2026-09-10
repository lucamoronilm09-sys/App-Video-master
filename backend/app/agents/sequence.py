"""Agente 2a: Sequence.

Assegna una durata dinamica alle foto in base alla rilevanza visiva:
complessità, dettaglio, contrasto, nitidezza, volti e score compositivo.
Le foto ordinarie durano circa 3–5s; quelle dense/importanti possono arrivare
fino a 8s. L'ordine manuale non viene mai modificato.
"""
from __future__ import annotations

import math
from typing import Any

PHOTO_BASE_MIN_SEC = 3.0
PHOTO_BASE_MAX_SEC = 8.0
PHOTO_MAX_SEC = PHOTO_BASE_MAX_SEC
MAX_VIDEO_SEC = 8.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _photo_visual_score(item: dict[str, Any]) -> float:
    """Combina i segnali visivi prodotti da Intake in uno score 0–1."""
    composition = _clamp01(float(item.get("composition_score") or 0.5))
    detail = _clamp01(float(item.get("detail_score") or composition))
    contrast = _clamp01(float(item.get("contrast_score") or 0.5))
    sharpness = _clamp01(float(item.get("sharpness_score") or 0.5))
    color = _clamp01(float(item.get("color_score") or 0.5))
    faces = max(0, int(item.get("face_count") or 0))
    face_score = _clamp01(math.log1p(faces) / math.log(9.0))

    return _clamp01(
        0.28 * composition
        + 0.24 * detail
        + 0.16 * sharpness
        + 0.12 * contrast
        + 0.08 * color
        + 0.12 * face_score
    )


def photo_duration(item: dict[str, Any]) -> float:
    """Durata cinematografica adattiva 3–8s."""
    score = _photo_visual_score(item)
    # Curva non lineare: evita che tutte le foto si concentrino vicino al valore
    # medio e riserva 7–8s alle immagini davvero ricche/importanti.
    duration = PHOTO_BASE_MIN_SEC + (PHOTO_BASE_MAX_SEC - PHOTO_BASE_MIN_SEC) * (score ** 0.72)

    faces = max(0, int(item.get("face_count") or 0))
    detail = _clamp01(float(item.get("detail_score") or 0.0))
    if faces >= 2:
        duration += min(0.8, 0.2 * faces)
    if detail >= 0.82:
        duration += 0.45

    return round(_clamp01((duration - PHOTO_BASE_MIN_SEC) / (PHOTO_BASE_MAX_SEC - PHOTO_BASE_MIN_SEC)) * (PHOTO_BASE_MAX_SEC - PHOTO_BASE_MIN_SEC) + PHOTO_BASE_MIN_SEC, 2)


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
