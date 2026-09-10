"""Agente 0: Intake (architettura sez. 5).

Valida i file, estrae metadata (width, height, duration, orientation, type)
in parallelo con ffprobe (video) e Pillow (immagini). Errori per-file vanno in
state["errors"] (non bloccanti); i file validi popolano state["media"].
"""
from __future__ import annotations

import asyncio
import math
import uuid
from pathlib import Path

from PIL import Image, ImageOps
from PIL import ImageStat

try:
    import cv2
except ImportError:
    cv2 = None

from app.services.media_inspect import inspect_media


def _photo_content_features(path: Path) -> tuple[int, float]:
    """Stima volti e complessità visiva su una copia ridotta della foto.

    Se OpenCV non è disponibile, usa un fallback Pillow-only invece del valore
    fisso 0.5: in questo modo le foto non ricevono tutte la stessa durata.
    """
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((1000, 1000))

            if cv2 is not None:
                import numpy as np
                gray = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)
                edges = cv2.Canny(gray, 80, 160)
                edge_density = float((edges > 0).mean())
                hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
                cv2.normalize(hist, hist)
                vals = hist[hist > 0]
                entropy = float(-(vals * np.log2(vals)).sum())
                cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
                faces = cascade.detectMultiScale(
                    gray, scaleFactor=1.12, minNeighbors=5, minSize=(32, 32)
                ) if not cascade.empty() else []
                complexity = max(
                    0.0,
                    min(1.0, 0.55 * (entropy / 6.0) + 0.45 * min(1.0, edge_density * 5.0)),
                )
                return int(len(faces)), round(complexity, 3)

            # Fallback robusto senza OpenCV: entropia dell'istogramma + varianza.
            gray = ImageOps.grayscale(im)
            hist = gray.histogram()
            total = sum(hist) or 1
            entropy = -sum((n / total) * math.log2(n / total) for n in hist if n)
            variance = ImageStat.Stat(gray).var[0]
            variance_score = min(1.0, math.sqrt(max(0.0, variance)) / 80.0)
            entropy_score = min(1.0, entropy / 7.5)
            complexity = max(0.0, min(1.0, 0.65 * entropy_score + 0.35 * variance_score))
            return 0, round(complexity, 3)
    except Exception:
        return 0, 0.5


async def _process_one(path: Path, source: str, drive_file_id: str | None) -> dict | None:
    try:
        meta = await inspect_media(path)
        face_count, composition_score = (0, 0.5)
        if meta["type"] == "photo":
            face_count, composition_score = await asyncio.to_thread(_photo_content_features, path)
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
            "source_fps": meta.get("source_fps"),
            "face_count": face_count,
            "composition_score": composition_score,
            "order_index": 0,
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
    project_state["media_staging"] = []
    return project_state
