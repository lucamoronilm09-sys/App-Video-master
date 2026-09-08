"""Registro thread-safe delle frazioni di avanzamento (agenti -> job manager).

Modulo foglia (nessuna dipendenza interna): gli agenti segnalano qui,
il worker riversa i valori nel record persistente del job.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_levels: dict[str, tuple[float, str]] = {}


def set(job_id: str | None, fraction: float, note: str = "") -> None:
    if not job_id:
        return
    with _lock:
        _levels[job_id] = (max(0.0, min(1.0, fraction)), note)


def pop(job_id: str | None) -> tuple[float, str] | None:
    if not job_id:
        return None
    with _lock:
        return _levels.pop(job_id, None)


def peek(job_id: str | None) -> tuple[float, str] | None:
    if not job_id:
        return None
    with _lock:
        return _levels.get(job_id)
