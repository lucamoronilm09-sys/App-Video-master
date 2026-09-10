"""Agente 2a: Sequence.

Assegna la durata alle foto in base alla composizione rilevata da Intake,
sempre nell'intervallo 2.5–5.5s. Le immagini più semplici restano brevi;
scene con più persone o maggiore complessità visiva ricevono più tempo.
L'ordine manuale non viene mai modificato.
"""
from __future__ import annotations

from typing import Any

PHOTO_BASE_MIN_SEC = 2.5
PHOTO_BASE_MAX_SEC = 5.5
PHOTO_MAX_SEC = PHOTO_BASE_MAX_SEC
MAX_VIDEO_SEC = 8.0


def photo_duration(item: dict[str, Any]) -> float:
    """Durata naturale 2.5–5.5s, determinata dalla composizione della foto."""
    composition = max(0.0, min(1.0, float(item.get("composition_score") or 0.5)))
    faces = max(0, int(item.get("face_count") or 0))

    # La complessità visiva è il segnale principale. I volti aggiungono
    # progressivamente tempo, con un tetto per evitare che le foto di gruppo
    # diventino sproporzionatamente lunghe.
    complexity_bonus = 2.2 * composition
    people_bonus = min(0.8, faces * 0.16)
    duration = PHOTO_BASE_MIN_SEC + complexity_bonus + people_bonus
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
                item["duration_sec"] = MAX_VIDEO_SEC
            else:
                item["trim_start_sec"] = None
                item["trim_end_sec"] = None
        clips.append(dict(item))

    project_state["clips"] = clips
    return project_state
