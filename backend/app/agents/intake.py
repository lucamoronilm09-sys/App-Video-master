"""Agente 0: Intake.

Valida i file ed estrae metadata. Per le foto calcola anche segnali tecnici
reali (volti, composizione, dettaglio, nitidezza, contrasto e interesse colore)
che il Vision Analyzer può integrare nel punteggio editoriale.
"""
from __future__ import annotations

import asyncio
import math
import uuid
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

try:
    import cv2
except ImportError:
    cv2 = None

from app.services.media_inspect import inspect_media


def _photo_content_features(path: Path) -> tuple[int, float, float, float, float, float]:
    """Return face_count, composition, detail, sharpness, contrast, color."""
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((1000, 1000))
            gray_pil = ImageOps.grayscale(im)
            stats = ImageStat.Stat(gray_pil)
            contrast = max(0.0, min(1.0, stats.stddev[0] / 75.0))
            rgb_mean = ImageStat.Stat(im).mean
            colorfulness = max(0.0, min(1.0, (max(rgb_mean) - min(rgb_mean)) / 90.0))

            if cv2 is not None:
                import numpy as np
                rgb = np.array(im)
                gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
                edges = cv2.Canny(gray, 80, 160)
                edge_density = float((edges > 0).mean())
                hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
                cv2.normalize(hist, hist)
                vals = hist[hist > 0]
                entropy = float(-(vals * np.log2(vals)).sum())
                complexity = max(0.0, min(1.0, 0.55 * (entropy / 6.0) + 0.45 * min(1.0, edge_density * 5.0)))

                laplacian = cv2.Laplacian(gray, cv2.CV_64F)
                sharpness = max(0.0, min(1.0, math.sqrt(max(0.0, float(laplacian.var()))) / 45.0))
                detail = max(0.0, min(1.0, 0.55 * sharpness + 0.45 * min(1.0, edge_density * 5.0)))

                cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
                faces = cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(32, 32)) if not cascade.empty() else []
                return (
                    int(len(faces)), round(complexity, 3), round(detail, 3),
                    round(sharpness, 3), round(contrast, 3), round(colorfulness, 3),
                )

            # Pillow-only fallback.
            variance = max(0.0, float(stats.var[0]))
            sharpness = min(1.0, math.sqrt(variance) / 80.0)
            detail = max(0.0, min(1.0, 0.65 * contrast + 0.35 * sharpness))
            complexity = max(0.0, min(1.0, 0.65 * contrast + 0.35 * detail))
            return 0, round(complexity, 3), round(detail, 3), round(sharpness, 3), round(contrast, 3), round(colorfulness, 3)
    except Exception:
        return 0, 0.5, 0.5, 0.5, 0.5, 0.5


async def _process_one(path: Path, source: str, drive_file_id: str | None) -> dict | None:
    try:
        meta = await inspect_media(path)
        face_count, composition, detail, sharpness, contrast, color = (0, 0.5, 0.5, 0.5, 0.5, 0.5)
        if meta["type"] == "photo":
            values = await asyncio.to_thread(_photo_content_features, path)
            face_count, composition, detail, sharpness, contrast, color = values
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
            "composition_score": composition,
            "detail_score": detail,
            "sharpness_score": sharpness,
            "contrast_score": contrast,
            "color_score": color,
            "order_index": 0,
        }
    except Exception as exc:
        return {"error": {"stage": "intake", "message": f"{path.name}: {exc}"}}


async def run(project_state: dict) -> dict:
    staging = project_state.get("media_staging", [])
    if not staging:
        return project_state
    tasks = [
        _process_one(Path(item["path"]), item.get("source", "local"), item.get("drive_file_id"))
        for item in staging
    ]
    results = await asyncio.gather(*tasks)
    new_media: list[dict] = []
    new_errors = list(project_state.get("errors", []))
    current_count = len(project_state.get("media", []))
    for result in results:
        if result is None:
            continue
        if "error" in result:
            new_errors.append(result["error"])
        else:
            result["order_index"] = current_count + len(new_media)
            new_media.append(result)
    project_state["media"].extend(new_media)
    project_state["errors"] = new_errors
    project_state["media_staging"] = []
    return project_state
