"""Vision analysis for photo-aware video editing.

Providers:
- Ollama: automatic local discovery of a vision-capable model.
- OpenAI-compatible HTTP endpoint: configurable via environment variables.
- Local Pillow/OpenCV fallback when no Vision model is available.

Set VISION_PROVIDER=disabled to force the local fallback (useful for tests).
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - optional dependency
    pillow_heif = None

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None

PROMPT = """Analyze this photo for an automatic memory-video editor.
Return ONLY valid JSON with these fields:
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
All four scores must be between 0 and 1. Judge the photograph itself, not image
quality alone. Importance means how much screen time a human editor would likely
give it in a personal memory montage. More people can increase importance when
faces are clearly visible, but do not reward a crowded image automatically.
Use recommended_pacing = fast, normal, slow, or hold. No markdown or explanation."""


class VisionError(RuntimeError):
    """Raised when an external vision provider cannot be used."""


def _timeout() -> float:
    try:
        return max(1.0, float(os.getenv("VISION_TIMEOUT_SEC", "45")))
    except ValueError:
        return 45.0


def _ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _provider() -> str:
    return os.getenv("VISION_PROVIDER", "auto").lower().strip()


def _base_url() -> str:
    return os.getenv("VISION_BASE_URL", "").rstrip("/")


def _api_key() -> str:
    return os.getenv("VISION_API_KEY", "")


def _configured_model() -> str:
    return os.getenv("VISION_MODEL", "").strip()


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
    try:
        people = max(0, min(20, int(data.get("people_count", data.get("face_count", 0)))))
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


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout or _timeout()) as response:
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
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=82, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")


def _ollama_model() -> str | None:
    configured = _configured_model()
    if configured:
        return configured
    req = urllib.request.Request(f"{_ollama_url()}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=2.0) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    models = [str(m.get("name", "")) for m in data.get("models", []) if isinstance(m, dict)]
    tokens = ("vl", "vision", "llava", "gemma3", "minicpm", "qwen2-vl", "qwen2.5vl", "qwen3-vl")
    for model in models:
        if any(token in model.lower() for token in tokens):
            return model
    return None


def _analyze_ollama(image_b64: str) -> dict[str, Any]:
    model = _ollama_model()
    if not model:
        raise VisionError("Nessun modello Vision Ollama disponibile")
    result = _post_json(
        f"{_ollama_url()}/api/chat",
        {"model": model, "messages": [{"role": "user", "content": PROMPT, "images": [image_b64]}], "stream": False, "format": "json", "options": {"temperature": 0}},
    )
    message = result.get("message") or {}
    return _normalize_profile(_extract_json(str(message.get("content", ""))))


def _analyze_openai_compatible(image_b64: str) -> dict[str, Any]:
    base = _base_url()
    model = _configured_model()
    if not base or not model:
        raise VisionError("VISION_BASE_URL e VISION_MODEL non configurati")
    result = _post_json(
        f"{base}/chat/completions",
        {"model": model, "temperature": 0, "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]}]},
        {"Authorization": f"Bearer {_api_key()}"} if _api_key() else None,
    )
    choices = result.get("choices") or []
    content = ((choices[0] if choices else {}).get("message") or {}).get("content", "")
    if isinstance(content, list):
        content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return _normalize_profile(_extract_json(str(content)))


def _technical_fallback(path: Path) -> dict[str, Any]:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1000, 1000))
        gray = ImageOps.grayscale(im)
        stat = ImageStat.Stat(gray)
        contrast = max(0.0, min(1.0, stat.stddev[0] / 75.0))
        rgb = ImageStat.Stat(im).mean
        color = max(0.0, min(1.0, (max(rgb) - min(rgb)) / 90.0))
        if cv2 is not None:
            import numpy as np
            arr = np.array(im)
            g = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            lap = float(cv2.Laplacian(g, cv2.CV_64F).var())
            sharpness = max(0.0, min(1.0, lap ** 0.5 / 45.0))
            edges = cv2.Canny(g, 80, 160)
            interest = max(0.0, min(1.0, float((edges > 0).mean()) * 5.0))
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            faces = cascade.detectMultiScale(g, scaleFactor=1.12, minNeighbors=5, minSize=(32, 32)) if not cascade.empty() else []
            people = int(len(faces))
        else:
            sharpness = max(0.0, min(1.0, stat.var[0] ** 0.5 / 80.0))
            interest = max(0.0, min(1.0, contrast * 0.7 + sharpness * 0.3))
            people = 0
        importance = max(0.0, min(1.0, 0.35 * interest + 0.25 * sharpness + 0.15 * contrast + 0.10 * color + 0.15 * min(1.0, people / 3.0)))
        return {
            "ai_used": False,
            "importance": round(importance, 3),
            "emotional_intensity": round(min(1.0, contrast * 0.7 + interest * 0.3), 3),
            "subject_clarity": round((sharpness + contrast) / 2.0, 3),
            "visual_interest": round(interest, 3),
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
    """Analyze one photo, preferring configured/local AI and falling back locally."""
    provider = _provider()
    if provider == "disabled":
        result = _technical_fallback(path)
        result["vision_provider"] = "disabled"
        return result

    image_b64 = _image_b64(path)
    providers = [provider] if provider in {"ollama", "openai", "openai_compatible"} else ["ollama", "openai"]
    errors: list[str] = []
    for selected in providers:
        try:
            result = _analyze_ollama(image_b64) if selected == "ollama" else _analyze_openai_compatible(image_b64)
            result["vision_provider"] = selected
            return result
        except Exception as exc:
            errors.append(f"{selected}: {exc}")

    result = _technical_fallback(path)
    result["vision_provider"] = "fallback"
    result["vision_error"] = " | ".join(errors[-2:]) if errors else None
    return result
