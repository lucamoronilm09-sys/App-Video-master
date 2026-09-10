"""Intelligenza editoriale deterministica costruita sui segnali IA già estratti."""
from __future__ import annotations

from typing import Any


def _f(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def music_structure(audio: dict[str, Any]) -> dict[str, Any]:
    energy = [_f(x, 0.5) for x in (audio.get("energy_curve") or [])]
    duration = float(audio.get("duration_sec") or len(energy) or 0.0)
    bpm = float(audio.get("bpm") or 0.0)
    if not energy or duration <= 0:
        return {"duration_sec": round(duration, 3), "bpm": bpm, "energy": "unknown", "sections": []}

    peak_idx = max(range(len(energy)), key=lambda i: energy[i])
    peak_t = min(duration, float(peak_idx))
    q = sum(energy) / len(energy)
    label = "alta" if q >= 0.68 else "media" if q >= 0.42 else "bassa"

    n = len(energy)
    cuts = [0, max(1, n // 4), max(2, n // 2), max(3, (3 * n) // 4), n]
    sections: list[dict[str, Any]] = []
    names = ["intro", "sviluppo", "climax", "finale"]
    for i in range(4):
        a, b = cuts[i], cuts[i + 1]
        if b <= a:
            continue
        sections.append({
            "start_sec": round(min(duration, float(a)), 3),
            "end_sec": round(min(duration, float(b)), 3),
            "label": names[i],
            "energy": round(sum(energy[a:b]) / max(1, b - a), 3),
        })
    return {"duration_sec": round(duration, 3), "bpm": round(bpm, 2), "energy": label,
            "sections": sections, "climax_sec": round(peak_t, 3), "peak_energy": round(energy[peak_idx], 3)}


def story_chapters(media: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not media:
        return []
    chapters: list[dict[str, Any]] = []
    current_kind: str | None = None
    current: list[tuple[int, dict[str, Any]]] = []
    scene_map = {
        "landscape": "Paesaggi", "city": "Luoghi", "nature": "Natura", "food": "Momenti quotidiani",
        "people": "Persone", "portrait": "Persone", "group": "Persone", "event": "Momenti importanti",
        "travel": "Viaggio", "action": "Azione", "unknown": "Momenti",
    }

    def flush() -> None:
        nonlocal current_kind, current
        if not current:
            return
        title = scene_map.get(current_kind or "unknown", "Momenti")
        ids = [m["id"] for _, m in current]
        chapters.append({"title": title, "kind": current_kind or "unknown", "media_ids": ids,
                         "start_index": current[0][0], "end_index": current[-1][0],
                         "reason": f"Raggruppamento semantico: {title.lower()}"})
        current_kind, current = None, []

    for i, item in enumerate(media):
        v = item.get("vision_analysis") or {}
        kind = str(v.get("scene_type") or item.get("scene_type") or "unknown").lower()
        people = int(v.get("people_count") or item.get("people_count") or 0)
        if people > 0 and kind in {"unknown", "portrait"}:
            kind = "people"
        if current_kind is None:
            current_kind = kind
        if kind != current_kind and len(current) >= 2:
            flush()
            current_kind = kind
        current.append((i, item))
    flush()
    return chapters


def prompt_preferences(prompt: str, style: str) -> dict[str, float]:
    text = f"{prompt} {style}".lower()
    pref = {"people": 0.0, "landscape": 0.0, "fast": 0.0, "slow": 0.0, "emotional": 0.0}
    groups = {
        "people": ("persona", "persone", "amici", "famiglia", "volti"),
        "landscape": ("paesaggio", "panorama", "natura", "luoghi", "viaggio"),
        "fast": ("veloce", "dinamico", "energico", "ritmato"),
        "slow": ("lento", "calmo", "cinematico", "emozionante", "delicato"),
        "emotional": ("emozionante", "emotivo", "ricordi", "sentimentale"),
    }
    for key, words in groups.items():
        pref[key] = min(1.0, 0.25 * sum(text.count(w) for w in words))
    return pref
