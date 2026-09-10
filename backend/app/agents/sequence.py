"""Agente 2a: Sequence.

Prepara i media per il montaggio. L'analisi semantica delle foto viene eseguita
qui perché è indipendente dall'audio; la durata finale viene scelta dall'Edit
Director dopo che anche l'audio è stato analizzato.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.services.vision_analyzer import analyze_photo

MAX_VIDEO_SEC = 8.0
PROVISIONAL_PHOTO_SEC = 3.5


async def _analyze_one_photo(item: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(item.get("path", "")))
    if not path.is_file():
        profile = {
            "ai_used": False,
            "vision_provider": "unavailable",
            "importance": 0.5,
            "emotional_intensity": 0.5,
            "subject_clarity": 0.5,
            "visual_interest": 0.5,
            "people_count": int(item.get("face_count") or 0),
            "is_group_photo": bool((item.get("face_count") or 0) >= 2),
            "recommended_pacing": "normal",
        }
    else:
        try:
            profile = await asyncio.to_thread(analyze_photo, path)
        except Exception as exc:
            profile = {
                "ai_used": False,
                "vision_provider": "error",
                "vision_error": str(exc),
                "importance": 0.5,
                "emotional_intensity": 0.5,
                "subject_clarity": 0.5,
                "visual_interest": 0.5,
                "people_count": int(item.get("face_count") or 0),
                "is_group_photo": bool((item.get("face_count") or 0) >= 2),
                "recommended_pacing": "normal",
            }
    item["vision_analysis"] = profile
    item["vision_ai_used"] = bool(profile.get("ai_used"))
    item["scene_type"] = profile.get("scene_type")
    item["people_count"] = profile.get("people_count", item.get("face_count", 0))
    item["importance_score"] = profile.get("importance", 0.5)
    return item


def _provisional_duration(item: dict[str, Any]) -> float:
    """Duration shown before music is available; Edit Director replaces it."""
    profile = item.get("vision_analysis") or {}
    importance = max(0.0, min(1.0, float(profile.get("importance", 0.5))))
    return round(2.5 + 2.0 * importance, 2)


async def run(project_state: dict) -> dict:
    media_list: list[dict[str, Any]] = project_state.get("media", [])
    tasks = [_analyze_one_photo(item) for item in media_list if item.get("type") == "photo"]
    if tasks:
        await asyncio.gather(*tasks)

    clips: list[dict[str, Any]] = []
    for item in media_list:
        if item.get("type") == "photo":
            # Pydantic richiede un float nel ProjectState: questo valore è solo
            # provvisorio. L'Edit Director lo sostituisce con la durata musicale.
            item["duration_sec"] = _provisional_duration(item)
            item["duration_source"] = "vision_provisional"
            item["trim_start_sec"] = None
            item["trim_end_sec"] = None
        else:
            dur = float(item.get("duration_sec") or 0.0)
            if dur > MAX_VIDEO_SEC:
                start = round((dur - MAX_VIDEO_SEC) / 2.0, 2)
                item["trim_start_sec"] = start
                item["trim_end_sec"] = round(start + MAX_VIDEO_SEC, 2)
            else:
                item["trim_start_sec"] = None
                item["trim_end_sec"] = None
        clips.append(dict(item))

    project_state["clips"] = clips
    return project_state
