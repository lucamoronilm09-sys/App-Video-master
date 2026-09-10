"""Vision analysis for photo-aware video editing.

The service is intentionally provider-agnostic:
- Ollama is tried automatically when available and exposes a vision model.
- An OpenAI-compatible endpoint can be configured through environment variables.
- If no vision model is available, a deterministic Pillow/OpenCV fallback is used.

The returned profile is consumed by the Edit Director to decide photo duration,
beat placement and editing intensity.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat, ImageOps

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None


VISION_TIMEOUT_SEC = float(os.getenv("VISION_TIMEOUT_SEC", "45"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
VISION_PROVIDER = os.getenv("VISION_PROVIDER", "auto").lower()
VISION_BASE_URL = os.getenv("VISION_BASE_URL", "").rstrip("/")
VISION_API_KEY = os.getenv("VISION_API_KEY", "")
VISION_MODEL = os.getenv("VISION_MODEL", "").strip()

PROMPT = """Analyze this photo for an automatic memory-video editor.
Return ONLY valid JSON with these numeric fields in [0,1] and boolean/string fields:
{
  "importance": 0.0,
  "emotional_intensity": 0.0,
  "subject_clarity": 0.0,
  "visual_interest": 0.0,
  "people_count": 0,
  "is_group_photo": false,
  "is_portrait": false,
  "is_landscape": false,
  "is_action": false,
  "is_closeup": false,
  "scene_type": "unknown",
  "recommended_pacing": "normal"
}
Judge the photograph itself, not image quality alone. Importance means how much
screen time a human editor would likely give it in a personal memory montage.
More people can increase importance when faces are clearly visible, but do not
reward a crowded image automatically. Use recommended_pacing = fast, normal,
slow, or hold. Do not include markdown or explanations."""


class VisionError(RuntimeError):
    """Raised when an external vision provider cannot be used."""


def _clamp01(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise VisionError("Il modello Vision non ha restituito JSON")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise VisionError("Risposta Vision non valida")
    return data


def _normalize_profile(data: dict[str, Any]) -> dict[str, Any]:
    people = data.get("people_count", data.get("face_count", 0))
    try:
        people = max(0, min(20, int(people)))
    except (TypeError, ValueError):
        people = 0
    pacing = str(data.get("recommended_pacing", "normal")).lower()
    if pacing not in {"fast", "normal", "slow", "hold"}:
        pacing = "normal"
    return {
        "ai_used": True,
        "importance": round(_clamp01(data.get("importance"), 0.55), 3),
        "emotional_intensity": round(_clamp01(data.get("emotional_intensity"), 0.5), 3),
        "subject_clarity": round(_clamp01(data.get("subject_clarity"), 0.5), 3),
        "visual_interest": round(_clamp01(data.get("visual_interest"), 0.5), 3),
        "people_count": people,
        "is_group_photo": bool(data.get("is_group_photo", people >= 2)),
        "is_portrait": bool(data.get("is_portrait", False)),
        "is_landscape": bool(data.get("is_landscape", False)),
        "is_action": bool(data.get("is_action", False)),
        "is_closeup": bool(data.get("is_closeup", False)),
        "scene_type": str(data.get("scene_type", "unknown"))[:80],
        "recommended_pacing": pacing,
    }


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=VISION_TIMEOUT_SEC) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VisionError(str(exc)) from exc
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VisionError("Provider Vision ha restituito una risposta non JSON") from exc
    if not isinstance(result, dict):
        raise VisionError("Risposta provider Vision non valida")
    return result


def _image_b64(path: Path) -> str:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1280, 1280))
        # JPEG ridotto: velocizza sensibilmente l'analisi e limita il payload.
        from io import BytesIO
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=82, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")


def _ollama_model() -> str | None:
    if VISION_MODEL:
        return VISION_MODEL
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    models = [str(m.get("name", "")) for m in data.get("models", []) if isinstance(m, dict)]
    vision_tokens = ("vl", "vision", "llava", "gemma3", "minicpm", "qwen2-vl", "qwen2.5vl", "qwen3-vl")
    for model in models:
        lower = model.lower()
        if any(token in lower for token in vision_tokens):
            return model
    return None


def _analyze_ollama(image_b64: str) -> dict[str, Any]:
    model = _ollama_model()
    if not model:
        raise VisionError("Nessun modello Vision Ollama disponibile")
    result = _post_json(
        f"{OLLAMA_URL}/api/chat",
        {
            "model": model,
            "messages": [{"role": "user", "content": PROMPT, "images": [image_b64]}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
    )
    message = result.get("message") or {}
    return _normalize_profile(_extract_json(str(message.get("content", ""))))


def _analyze_openai_compatible(image_b64: str) -> dict[str, Any]:
    if not VISION_BASE_URL or not VISION_MODEL:
        raise VisionError("VISION_BASE_URL e VISION_MODEL non configurati")
    url = f"{VISION_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {VISION_API_KEY}"} if VISION_API_KEY else {}
    result = _post_json(
        url,
        {
            "model": VISION_MODEL,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    ],
                }
            ],
        },
        headers,
    )
    choices = result.get("choices") or []
    content = ((choices[0] if choices else {}).get("message") or {}).get("content", "")
    if isinstance(content, list):
        content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return _normalize_profile(_extract_json(str(content)))


def _technical_fallback(path: Path) -> dict[str, Any]:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1000, 1000))
        gray = ImageOps.grayscale(im)
        stat = ImageStat.Stat(gray)
        contrast = max(0.0, min(1.0, stat.stddev[0] / 75.0))
        color = max(0.0, min(1.0, ImageStat.Stat(im).mean[0] / 255.0))
        if cv2 is not None:
            import numpy as np
            arr = np.array(im)
            g = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            lap = float(cv2.Laplacian(g, cv2.CV_64F).var())
            sharpness = max(0.0, min(1.0, lap ** 0.5 / 45.0))
            edges = cv2.Canny(g, 80, 160)
            visual_interest = max(0.0, min(1.0, float((edges > 0).mean()) * 5.0))
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            faces = cascade.detectMultiScale(g, scaleFactor=1.12, minNeighbors=5, minSize=(32, 32)) if not cascade.empty() else []
            people = int(len(faces))
        else:
            sharpness = max(0.0, min(1.0, stat.var[0] ** 0.5 / 80.0))
            visual_interest = max(0.0, min(1.0, contrast * 0.7 + sharpness * 0.3))
            people = 0
        importance = max(0.0, min(1.0, 0.35 * visual_interest + 0.25 * sharpness + 0.20 * contrast + 0.20 * min(1.0, people / 3.0)))
        return {
            "ai_used": False,
            "importance": round(importance, 3),
            "emotional_intensity": round(min(1.0, contrast * 0.7 + visual_interest * 0.3), 3),
            "subject_clarity": round((sharpness + contrast) / 2.0, 3),
            "visual_interest": round(visual_interest, 3),
            "people_count": people,
            "is_group_photo": people >= 2,
            "is_portrait": im.height > im.width,
            "is_landscape": im.width > im.height,
            "is_action": False,
            "is_closeup": False,
            "scene_type": "unknown",
            "recommended_pacing": "slow" if importance >= 0.75 else "normal",
        }


def analyze_photo(path: Path) -> dict[str, Any]:
    """Return semantic pacing features for one photo."""
    image_b64 = _image_b64(path)
    errors: list[str] = []

    providers: list[str]
    if VISION_PROVIDER == "ollama":
        providers = ["ollama"]
    elif VISION_PROVIDER in {"openai", "openai_compatible"}:
        providers = ["openai"]
    else:
        providers = ["ollama", "openai"]

    for provider in providers:
        try:
            if provider == "ollama":
                profile = _analyze_ollama(image_b64)
            else:
                profile = _analyze_openai_compatible(image_b64)
            profile["vision_provider"] = provider
            return profile
        except Exception as exc:
            errors.append(f"{provider}: {exc}")

    fallback = _technical_fallback(path)
    fallback["vision_provider"] = "fallback"
    fallback["vision_error"] = " | ".join(errors[-2:]) if errors else None
    return fallback
