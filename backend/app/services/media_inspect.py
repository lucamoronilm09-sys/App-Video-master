"""Estrazione metadata reali: ffprobe per video, Pillow per immagini.
Usato dall'Intake Agent (M1)."""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

try:  # HEIC/HEIF iPhone (dipendenza opzionale ma in requirements)
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".mts"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tiff", ".tif"}


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


async def _run_ffprobe(path: Path) -> dict[str, Any] | None:
    """Estrae width, height, duration, codec via ffprobe JSON."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,codec_name,avg_frame_rate,r_frame_rate",
        "-of", "json",
        str(path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        data = json.loads(stdout.decode())
        streams = data.get("streams", [])
        if not streams:
            return None
        s = streams[0]
        return {
            "width": int(s.get("width", 0)),
            "height": int(s.get("height", 0)),
            "duration_sec": float(s.get("duration", 0.0)),
            "codec": s.get("codec_name"),
            # fps nativo del video (es. 25.0 PAL, 29.97 NTSC, 30.0): serve alla UI
            # per consigliare un fps di output senza conversioni che creano
            # micro-scatti (25->30 inietta 5 frame duplicati/s a cadenza irregolare).
            "source_fps": _parse_fps(s.get("avg_frame_rate")) or _parse_fps(s.get("r_frame_rate")),
        }
    except Exception:
        return None


def _parse_fps(value: object) -> float | None:
    """Parsa un frame rate ffprobe ('30000/1001', '25/1', '29.97') in float."""
    if not value or not isinstance(value, str):
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            fps = float(num) / float(den)
        else:
            fps = float(value)
    except (ValueError, ZeroDivisionError):
        return None
    if not 1.0 <= fps <= 240.0:
        return None
    return round(fps, 3)


async def _inspect_image(path: Path) -> dict[str, Any] | None:
    try:
        with Image.open(path) as im:
            # Foto telefono: le dimensioni vere sono nell'orientamento EXIF
            im = ImageOps.exif_transpose(im)
            w, h = im.size
        return {"width": w, "height": h, "duration_sec": 0.0, "codec": None}
    except Exception:
        return None


async def inspect_media(path: Path) -> dict[str, Any]:
    """Ritorna dict con width, height, duration_sec, type, orientation, codec.
    Solleva se file non supportato/corrotto."""
    if is_video(path):
        meta = await _run_ffprobe(path)
        if not meta or meta["width"] == 0:
            raise ValueError(f"Video non leggibile o senza stream video: {path.name}")
        meta["type"] = "video"
    elif is_image(path):
        meta = await _inspect_image(path)
        if not meta or meta["width"] == 0:
            raise ValueError(f"Immagine non leggibile: {path.name}")
        meta["type"] = "photo"
        meta["source_fps"] = None  # le foto non hanno un frame rate nativo
    else:
        raise ValueError(f"Estensione non supportata: {path.suffix}")

    w, h = meta["width"], meta["height"]
    if w >= h:
        meta["orientation"] = "landscape" if w > h else "square"
    else:
        meta["orientation"] = "portrait"
    return meta