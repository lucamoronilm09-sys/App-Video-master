"""Agente 2a: Sequence (architettura sez. 5).

Rispetta SEMPRE l'ordine manuale dell'utente (order_index): non riordina mai.
- Foto: durata deterministica in [2.5, 6.0]s, derivata dall'hash del media id.
- Video: durata originale; se > MAX_VIDEO_SEC, trim centrale.

Il campo `clips` è un alias compatibile con il vecchio stato applicativo: contiene
le stesse informazioni dei media già normalizzati per il montaggio. Il nuovo
pipeline state continua a usare `media` + `edit_decision_list` come contratto
principale.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

PHOTO_BASE_MIN_SEC = 2.5
PHOTO_BASE_MAX_SEC = 6.0
PHOTO_MAX_SEC = PHOTO_BASE_MAX_SEC
MAX_VIDEO_SEC = 8.0


def photo_duration(item: dict[str, Any]) -> float:
    """Durata naturale e deterministica di una foto: 2.5–6.0 secondi."""
    media_id = str(item.get("id", ""))
    seed = hashlib.sha256(media_id.encode("utf-8")).digest()
    rng = random.Random(seed)
    composition = max(0.0, min(1.0, float(item.get("composition_score") or 0.5)))
    faces = max(0, int(item.get("face_count") or 0))
    stable = rng.uniform(-0.15, 0.15)
    duration = PHOTO_BASE_MIN_SEC + 2.9 * composition + min(0.55, faces * 0.12) + stable
    return round(max(PHOTO_BASE_MIN_SEC, min(PHOTO_BASE_MAX_SEC, duration)), 2)


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
                # The effective duration used downstream is the trimmed duration.
                item["duration_sec"] = MAX_VIDEO_SEC
            else:
                item["trim_start_sec"] = None
                item["trim_end_sec"] = None

        clips.append(dict(item))

    project_state["clips"] = clips
    return project_state
