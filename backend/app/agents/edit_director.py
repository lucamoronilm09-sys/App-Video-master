"""Agente 3: Edit Director — montaggio photo-aware, music-aware e story-aware."""
from __future__ import annotations

import hashlib
import random
from typing import Any

from app.agents.timeline_core import compute_timeline, edl_to_timeline_entries
from app.services.editor_intelligence import music_structure, prompt_preferences, story_chapters

TRANS_MIN_SEC = 0.5
TRANS_MAX_SEC = 0.9
ZOOM_MAX = 1.15
PHOTO_MIN_SEC = 2.0
PHOTO_MAX_SEC = 7.0
MOVEMENTS = ("pan_left", "pan_right", "zoom_in_slow", "zoom_out_slow", "pan_and_zoom_diag")


def _rng(project_id: str) -> random.Random:
    return random.Random(hashlib.sha256(project_id.encode("utf-8")).digest())


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _f(value: Any, default: float = 0.5) -> float:
    try: return _clamp(float(value), 0.0, 1.0)
    except (TypeError, ValueError): return default


def _vision(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("vision_analysis")
    return value if isinstance(value, dict) else {}


def _people_factor(people: int, faces_clear: float) -> float:
    base = _clamp(people / 4.0, 0.0, 1.0)
    return base * (0.45 + 0.55 * _f(faces_clear, 0.5))


def _photo_score(item: dict[str, Any], pref: dict[str, float] | None = None) -> float:
    v = _vision(item)
    try: people = max(0, int(v.get("people_count", item.get("face_count", 0))))
    except (TypeError, ValueError): people = 0
    raw = (
        0.27 * _f(v.get("story_value", v.get("importance", item.get("importance_score", 0.5))))
        + 0.16 * _f(v.get("emotional_intensity", 0.5)) + 0.13 * _f(v.get("attention_score", 0.5))
        + 0.10 * _f(v.get("subject_clarity", item.get("detail_score", 0.5)))
        + 0.09 * _f(v.get("composition_balance", item.get("composition_score", 0.5)))
        + 0.09 * _f(v.get("visual_quality", item.get("sharpness_score", 0.5)))
        + 0.06 * _f(v.get("visual_interest", item.get("composition_score", 0.5)))
        + 0.07 * _people_factor(people, _f(v.get("faces_clear", 0.5))) + 0.03 * _f(item.get("color_score", 0.5))
    )
    repetition = _f(v.get("repetition_risk", 0.25), 0.25)
    raw -= 0.12 * repetition
    pref = pref or {}
    raw += 0.10 * pref.get("people", 0.0) * _people_factor(people, 0.7)
    raw += 0.08 * pref.get("landscape", 0.0) * (1.0 if v.get("is_landscape") else 0.0)
    raw += 0.06 * pref.get("emotional", 0.0) * _f(v.get("emotional_intensity", 0.5))
    return _clamp(raw, 0.0, 1.0)


def _raw_photo_duration(item: dict[str, Any], music_energy: float, pref: dict[str, float]) -> float:
    v = _vision(item)
    score = _photo_score(item, pref)
    duration = PHOTO_MIN_SEC + (PHOTO_MAX_SEC - PHOTO_MIN_SEC) * (score ** 0.82)
    duration += 0.75 * _f(v.get("story_value", v.get("importance", 0.5)), 0.5)
    duration += 0.40 * _f(v.get("emotional_intensity", 0.5)) + 0.25 * _f(v.get("attention_score", 0.5))
    duration += 0.20 * _f(v.get("faces_clear", 0.5)) if bool(v.get("is_group_photo")) else 0.0
    duration -= 0.85 * _f(music_energy, 0.5) + 0.45 * _f(v.get("repetition_risk", 0.25), 0.25)
    duration += {"fast": -0.75, "normal": 0.0, "slow": 0.75, "hold": 1.20}.get(str(v.get("recommended_pacing", "normal")).lower(), 0.0)
    duration += 0.55 * pref.get("slow", 0.0) - 0.55 * pref.get("fast", 0.0)
    if bool(v.get("is_closeup")): duration += 0.20
    if bool(v.get("is_action")): duration -= 0.35
    if str(v.get("recommended_focus", "scene")) == "detail": duration += 0.20
    return _clamp(duration, PHOTO_MIN_SEC, PHOTO_MAX_SEC)


def _energy_at(energy: list[Any], t: float) -> float:
    if not energy: return 0.5
    return _f(energy[max(0, min(len(energy) - 1, int(t)))], 0.5)


def _music_grid(audio: dict[str, Any]) -> list[float]:
    try: return sorted(float(x) for x in (audio.get("beat_times_sec") or audio.get("beat_markers_sec") or []))
    except (TypeError, ValueError): return []


def _fit_total(durations: list[float], media: list[dict[str, Any]], target: float, pref: dict[str, float]) -> list[float]:
    out = list(durations)
    diff = target - sum(out)
    if not out or target <= 0 or abs(diff) < 0.01: return out
    photos = [i for i, m in enumerate(media) if m.get("type") == "photo"]
    ranked = sorted(photos, key=lambda i: _photo_score(media[i], pref), reverse=diff > 0)
    remaining = abs(diff)
    for i in ranked:
        if remaining <= 0.01: break
        room = PHOTO_MAX_SEC - out[i] if diff > 0 else out[i] - PHOTO_MIN_SEC
        change = min(max(0.0, room), remaining)
        out[i] = round(out[i] + change if diff > 0 else out[i] - change, 3)
        remaining -= change
    return out


def _initial_durations(media: list[dict[str, Any]], audio: dict[str, Any], pref: dict[str, float]) -> list[float]:
    energy = list(audio.get("energy_curve") or []); out: list[float] = []; cursor = 0.0
    for item in media:
        if item.get("type") == "photo": duration = _raw_photo_duration(item, _energy_at(energy, cursor), pref)
        else:
            ts, te = item.get("trim_start_sec"), item.get("trim_end_sec")
            duration = max(0.5, float(te) - float(ts)) if ts is not None and te is not None else max(0.5, float(item.get("duration_sec") or 0.0))
        out.append(round(duration, 3)); cursor += duration
    return out


def _snap_to_beats(media: list[dict[str, Any]], wanted: list[float], beats: list[float], target_total: float) -> list[float]:
    if not beats or target_total <= 0: return wanted
    out = list(wanted); cursor = 0.0
    for i, item in enumerate(media):
        if i == len(media) - 1:
            if item.get("type") == "photo": out[i] = _clamp(round(target_total - cursor, 3), PHOTO_MIN_SEC, PHOTO_MAX_SEC)
            break
        if item.get("type") == "photo":
            target_end = cursor + out[i]; remaining_photos = sum(1 for m in media[i + 1:] if m.get("type") == "photo")
            max_end = min(cursor + PHOTO_MAX_SEC, target_total - PHOTO_MIN_SEC * remaining_photos)
            candidates = [b for b in beats if cursor + PHOTO_MIN_SEC - 1e-6 <= b <= max_end + 1e-6]
            if candidates:
                near = min(candidates, key=lambda b: abs(b - target_end)); candidate_duration = near - cursor
                if abs(candidate_duration - out[i]) <= 0.75: out[i] = round(candidate_duration, 3)
        cursor += out[i]
    return out


def _choose_movement(item: dict[str, Any], rng: random.Random, index: int) -> str:
    v = _vision(item); focus = str(v.get("recommended_focus", "scene")).lower(); center = str(v.get("attention_center", "unknown")).lower()
    if bool(v.get("is_closeup")) or focus == "people": return ("zoom_in_slow", "pan_left", "pan_right")[index % 3]
    if bool(v.get("is_landscape")) or focus == "scene":
        return "pan_left" if center in {"left", "left_center"} else "pan_right" if center in {"right", "right_center"} else ("pan_left", "pan_right", "pan_and_zoom_diag")[index % 3]
    if focus == "detail": return "zoom_in_slow"
    return MOVEMENTS[index % len(MOVEMENTS)] if index % 2 == 0 else rng.choice(list(MOVEMENTS))


def _ken_burns_params(movement: str, rng: random.Random) -> dict[str, Any]:
    if movement == "zoom_in_slow": return {"movement": movement, "zoom_from": 1.0, "zoom_to": round(rng.uniform(1.08, ZOOM_MAX), 3), "pan_x_from": 0.5, "pan_x_to": 0.5, "pan_y_from": 0.5, "pan_y_to": 0.5}
    if movement == "zoom_out_slow": return {"movement": movement, "zoom_from": round(rng.uniform(1.08, ZOOM_MAX), 3), "zoom_to": 1.0, "pan_x_from": 0.5, "pan_x_to": 0.5, "pan_y_from": 0.5, "pan_y_to": 0.5}
    if movement in ("pan_left", "pan_right"):
        x = (1.0, 0.0) if movement == "pan_left" else (0.0, 1.0)
        return {"movement": movement, "zoom_from": 1.1, "zoom_to": 1.1, "pan_x_from": x[0], "pan_x_to": x[1], "pan_y_from": 0.5, "pan_y_to": 0.5}
    xa = (0.0, 1.0) if rng.random() < 0.5 else (1.0, 0.0); ya = (0.0, 1.0) if rng.random() < 0.5 else (1.0, 0.0)
    return {"movement": movement, "zoom_from": 1.0, "zoom_to": 1.12, "pan_x_from": xa[0], "pan_x_to": xa[1], "pan_y_from": ya[0], "pan_y_to": ya[1]}


async def run(project_state: dict) -> dict:
    media = sorted(project_state.get("media", []), key=lambda m: m.get("order_index", 0))
    if not media:
        project_state["edit_decision_list"] = []
        return project_state
    
    audio = project_state.get("audio") or {}
    audio_dur = float(audio.get("duration_sec") or 0.0)
    beats = _music_grid(audio)
    pref = prompt_preferences(str(project_state.get("user_prompt", "")), str(project_state.get("style_profile", "")))
    project_state["story_chapters"] = story_chapters(media)
    project_state["music_structure"] = music_structure(audio)
    
    fixed_total = sum(
        max(0.5, float(m.get("trim_end_sec") - m.get("trim_start_sec")))
        if m.get("type") == "video" and m.get("trim_start_sec") is not None and m.get("trim_end_sec") is not None
        else (0.0 if m.get("type") == "photo" else max(0.5, float(m.get("duration_sec") or 0.0)))
        for m in media
    )
    photo_count = sum(m.get("type") == "photo" for m in media)
    minimum_total = fixed_total + photo_count * PHOTO_MIN_SEC
    target_total = max(audio_dur, minimum_total) if audio_dur > 0 else 0.0
    
    durations = _initial_durations(media, audio, pref)
    if target_total > 0:
        durations = _fit_total(durations, media, target_total, pref)
        durations = _snap_to_beats(media, durations, beats, target_total)
        diff = round(target_total - sum(durations), 3)
        if abs(diff) > 0.01:
            last_photo = next((j for j in reversed(range(len(media))) if media[j].get("type") == "photo"), None)
            if last_photo is not None:
                durations[last_photo] = round(_clamp(durations[last_photo] + diff, PHOTO_MIN_SEC, PHOTO_MAX_SEC), 3)
    
    rng = _rng(str(project_state.get("project_id", "")))
    edl_raw: list[dict[str, Any]] = []
    photo_index = 0
    energy = list(audio.get("energy_curve") or [])
    cursor = 0.0
    
    for i, item in enumerate(media):
        duration = round(float(durations[i]), 3)
        v = _vision(item)
        
        if item.get("type") == "photo":
            item["duration_sec"] = duration
            item["ai_duration_sec"] = duration
            item["ai_edit_score"] = round(_photo_score(item, pref), 3)
            item["duration_source"] = "ai_music" if audio_dur > 0 else "vision"
            item["music_sync"] = bool(beats)
            item["vision_ai_used"] = bool(v.get("ai_used", item.get("vision_ai_used", False)))
            item["people_count"] = int(v.get("people_count", item.get("people_count", 0)) or 0)
            item["importance_score"] = round(_photo_score(item, pref), 3)
            movement = _choose_movement(item, rng, photo_index)
            kb = _ken_burns_params(movement, rng)
            photo_index += 1
        else:
            kb = None
        
        # Calcola transizione: prima clip sempre 0, altrimenti basata su energia o default
        # Se non c'è audio (energy_curve vuota), usa un default di 0.8s per transizioni fluide
        if i == 0:
            transition_in = 0.0
        elif not energy or len(energy) == 0:
            # Nessun audio: usa transizione default fluida
            transition_in = 0.8
        else:
            transition_in = round(_clamp(0.78 - 0.28 * _energy_at(energy, cursor), TRANS_MIN_SEC, TRANS_MAX_SEC), 3)
        
        edl_raw.append({
            "media_id": item["id"],
            "start_sec_in_final_video": round(cursor, 3),
            "duration_sec": duration,
            "ken_burns": kb,
            "transition_in": transition_in,
            "transition_out": transition_in if i < len(media) - 1 else 0.0,
            "editorial_score": round(_photo_score(item, pref), 3) if item.get("type") == "photo" else None,
            "duration_reason": "vision+music" if item.get("type") == "photo" and audio_dur > 0 else "vision" if item.get("type") == "photo" else "source-video-duration",
            "vision_scene": v.get("scene_type") if item.get("type") == "photo" else None,
        })
        
        cursor += duration
        if transition_in > 0:
            cursor -= transition_in
    
    # Usa la funzione centrale per calcolare la timeline coerente
    # Questo garantisce che start, duration, transition siano allineati
    fps = 30  # default, verrà sovrascritto da output_spec se presente
    computed_entries, total_sec = compute_timeline(edl_raw, fps=fps)
    edl = edl_to_timeline_entries(edl_raw, computed_entries)
    
    project_state["edit_decision_list"] = edl
    project_state["edit_summary"] = {
        "vision_photos": sum(1 for m in media if m.get("type") == "photo" and m.get("vision_ai_used")),
        "total_photos": photo_count,
        "music_synced": bool(beats),
        "bpm": audio.get("bpm", 0.0),
        "average_photo_score": round(sum(_photo_score(m, pref) for m in media if m.get("type") == "photo") / max(1, photo_count), 3),
        "story_chapters": len(project_state["story_chapters"]),
        "music_climax_sec": project_state["music_structure"].get("climax_sec"),
        "prompt_active": bool(str(project_state.get("user_prompt", "")).strip()),
        "planned_duration_sec": total_sec,
    }
    return project_state
