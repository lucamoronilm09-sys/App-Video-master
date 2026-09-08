"""Agente 0: Intake (architettura sez. 5).

Valida i file, estrae metadata (width, height, duration, orientation, type)
in parallelo con ffprobe (video) e Pillow (immagini). Errori per-file vanno in
state["errors"] (non bloccanti); i file validi popolano state["media"].
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from app.services.media_inspect import inspect_media


async def _process_one(path: Path, source: str, drive_file_id: str | None) -> dict | None:
    try:
        meta = await inspect_media(path)
        return {
            "id": uuid.uuid4().hex[:12],
            "source": source,
            "drive_file_id": drive_file_id,
            "path": str(path),
            "type": meta["type"],
            "orientation": meta["orientation"],
            "width": meta["width"],
            "height": meta["height"],
            "duration_sec": meta["duration_sec"],
            # fps nativo (solo video; None per foto o se non rilevabile)
            "source_fps": meta.get("source_fps"),
            "order_index": 0,  # Sequence Agent (M3) lo riassegnerà
        }
    except Exception as exc:
        return {"error": {"stage": "intake", "message": f"{path.name}: {exc}"}}


async def run(project_state: dict) -> dict:
    """Legge project_state["media_staging"] (lista di dict {path, source, drive_file_id?}),
    processa in parallelo, aggiorna media[] e errors[]."""
    staging = project_state.get("media_staging", [])
    if not staging:
        return project_state

    tasks = [
        _process_one(Path(item["path"]), item.get("source", "local"), item.get("drive_file_id"))
        for item in staging
    ]
    results = await asyncio.gather(*tasks)

    new_media = []
    new_errors = list(project_state.get("errors", []))
    current_count = len(project_state.get("media", []))

    for r in results:
        if r is None:
            continue
        if "error" in r:
            new_errors.append(r["error"])
        else:
            r["order_index"] = current_count + len(new_media)
            new_media.append(r)

    project_state["media"].extend(new_media)
    project_state["errors"] = new_errors
    project_state["media_staging"] = []  # consumato
    return project_state