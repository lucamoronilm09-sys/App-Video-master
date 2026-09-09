"""Agente 2a: Sequence (architettura sez. 5).

Rispetta SEMPRE l'ordine manuale dell'utente (order_index): non riordina mai.
- Foto: durata base deterministica in [2.5, 6.0]s, derivata dall'hash del media id
  (ritmo naturale non uniforme + idempotenza: stesso progetto = stesse durate).
- Video: durata originale; se > MAX_VIDEO_SEC, trim centrale (trim_start/end_sec),
  altrimenti nessun trim.

Tocca solo i campi durata/trim dei media (disgiunti da Normalizer e Audio).
Idempotente: riesecuzioni successive danno lo stesso risultato.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

# Durata "naturale" di base assegnata a ogni foto dal Sequence Agent
# (prima di qualsiasi aggiustamento per beat-sync o fit-audio).
PHOTO_BASE_MIN_SEC = 2.5
PHOTO_BASE_MAX_SEC = 5.5
MAX_VIDEO_SEC = 8.0


def photo_duration(item: dict[str, Any]) -> float:
    """Durata 2.5–5.5s guidata da complessità, volti e componente stabile."""
    media_id = str(item.get("id", ""))
    seed = hashlib.sha256(media_id.encode("utf-8")).digest()
    rng = random.Random(seed)
    composition = max(0.0, min(1.0, float(item.get("composition_score") or 0.5)))
    faces = max(0, int(item.get("face_count") or 0))
    stable = rng.uniform(-0.15, 0.15)
    duration = 2.5 + 2.4 * composition + min(0.55, faces * 0.12) + stable
    return round(max(PHOTO_BASE_MIN_SEC, min(PHOTO_BASE_MAX_SEC, duration)), 2)


async def run(project_state: dict) -> dict:
    media_list: list[dict[str, Any]] = project_state.get("media", [])
    for item in media_list:
        if item.get("type") == "photo":
            item["duration_sec"] = photo_duration(item)
            item["trim_start_sec"] = None
            item["trim_end_sec"] = None
        else:  # video: mantiene la durata, eventuale trim centrale
            dur = float(item.get("duration_sec") or 0.0)
            if dur > MAX_VIDEO_SEC:
                start = round((dur - MAX_VIDEO_SEC) / 2.0, 2)
                item["trim_start_sec"] = start
                item["trim_end_sec"] = round(start + MAX_VIDEO_SEC, 2)
            else:
                item["trim_start_sec"] = None
                item["trim_end_sec"] = None
    return project_state
