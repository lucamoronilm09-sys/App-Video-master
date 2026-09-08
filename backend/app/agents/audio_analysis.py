"""Agente 2b: Audio Analysis (architettura sez. 5).

Analizza la traccia utente (delegando a app.services.audio_features, numpy +
ffmpeg): bpm stimato, beat_markers_sec (solo beat strutturali/forti, uno per
battuta), energy_curve 0..1 a passi di 1s. Non modifica il file audio.
File mancante/analysis fallita -> entry in errors[] (non bloccante per i media).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.audio_features import analyze_audio


async def run(project_state: dict) -> dict:
    audio = project_state.setdefault("audio", {})
    path = audio.get("path")
    if not path:
        return project_state  # nessuna traccia caricata: niente da analizzare
    if not Path(path).is_file():
        project_state.setdefault("errors", []).append(
            {"stage": "audio_analysis", "message": f"File audio mancante: {path}"}
        )
        return project_state
    try:
        result = await asyncio.to_thread(analyze_audio, Path(path))
    except Exception as exc:
        project_state.setdefault("errors", []).append(
            {"stage": "audio_analysis", "message": str(exc)}
        )
        return project_state
    audio.update(result)
    return project_state
