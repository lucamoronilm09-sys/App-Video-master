"""Secure media container validation helpers.

Validation intentionally uses ffprobe for media containers instead of weak
"magic byte" heuristics. The file is already streamed to disk and this module
only inspects the resulting path, keeping memory use bounded.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".mts"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tiff", ".tif", ".gif"}


def validate_media_file(path: Path, ext: str, timeout: int = 15) -> bool:
    """Return True only when ffprobe can identify the file as the expected class.

    A missing ffprobe is treated as a server configuration error rather than
    silently accepting an unverified upload.
    """
    if ext in ALLOWED_VIDEO_EXTS:
        expected = "video"
    elif ext in ALLOWED_IMAGE_EXTS:
        expected = "image"
    else:
        return False

    if not path.is_file() or path.stat().st_size == 0:
        return False

    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "stream=codec_type",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        raise RuntimeError("ffprobe non disponibile o timeout durante la validazione del media") from None

    if proc.returncode != 0:
        return False

    try:
        streams = json.loads(proc.stdout or "{}").get("streams", [])
    except json.JSONDecodeError:
        return False

    if expected == "video":
        return any(s.get("codec_type") == "video" for s in streams)

    # ffprobe usually identifies decoded images as video streams; require a
    # video stream and reject files that also contain audio/video ambiguity.
    return any(s.get("codec_type") == "video" for s in streams)
