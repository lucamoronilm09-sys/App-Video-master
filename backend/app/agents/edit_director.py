"""Agente 3: Edit Director — montaggio photo-aware e music-aware."""
from __future__ import annotations

import hashlib
import random
from typing import Any

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
    try:
        return _clamp(float(value), 0.0, 1.0)
    except (TypeError, ValueError):
        return default


def _vision(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("vision_analysis")
    return value if isinstance(value, dict) else {}


def _photo_score(item: dict[str, Any]) -> float:
    v = _vision(item)
    try:
        people = max(0, int(v.get("people_count", item.get("face_count", 0))))
    except (TypeError, ValueError):
        people = 0
    return _clamp(
        0.36 * _f(v.get("importance", item.get("importance_score", 0.5)))
        + 0.18 * _f(v.get("emotional_intensity", 0.5))
        + 0.14 * _f(v.get("subject_clarity", item.get("detail_score", 0.5)))
        + 0.12 * _f(v.get("visual_interest", item.get("composition_score", 0.5)))
        + 0.08 * _f(item.get("sharpness_score", 0.5))
        + 0.05 * _f(item.get("contrast_score", 0.5))
        + 0.07 * _clamp(people / 4.0, 0.0, 1.0),
        0.0, 1.0,
    )


def _raw_photo_duration(item: dict[str, Any], music_energy: float) -> float:
    v = _vision(item)
    duration = PHOTO_MIN_SEC + (PHOTO_MAX_SEC - PHOTO_MIN_SEC) * (_photo_score(item) ** 0.72)
    duration += 0.55 * _f(v.get("emotional_intensity", 0.5))
    duration -= 0.75 * _f(music_energy, 0.5)
    duration += {"fast": -0.60, "slow": 0.65, "hold": 1.05}.get(str(v.get("recommended_pacing", "normal")).lower(), 0.0)
    if bool(v.get("is_group_photo")):
        duration += 0.25
    if bool(v.get("is_closeup")):
        duration += 0.15
    if bool(v.get("is_action")):
        duration -= 0.25
    return _clamp(duration, PHOTO_MIN_SEC, PHOTO_MAX_SEC)


def _energy_at(energy: list[Any], t: float) -> float:
    if not energy:
        return 0.5
    return _f(energy[max(0, min(len(energy) - 1, int(t)))], 0.5)


def _music_grid(audio: dict[str, Any]) -> list[float]:
    try:
        return sorted(float(x) for x in (audio.get("beat_times_sec") or audio.get("beat_markers_sec") or []))
    except (TypeError, ValueError):
        return []


def _fit_total(durations: list[float], media: list[dict[str, Any]], target: float) -> list[float]:
    out = list(durations)
    if not out or target <= 0:
        return out
    diff = target - sum(out)
    photos = [i for i, m in enumerate(media) if m.get("type") == "photo"]
    ranked = sorted(photos, key=lambda i: _photo_score(media[i]), reverse=diff > 0)
    remaining = abs(diff)
    for i in ranked:
        if remaining <= 0.01:
            break
        room = PHOTO_MAX_SEC - out[i] if diff > 0 else out[i] - PHOTO_MIN_SEC
        change = min(max(0.0, room), remaining)
        out[i] = round(out[i] + change if diff > 0 else out[i] - change, 3)
        remaining -= change
    return out


def _initial_durations(media: list[dict[str, Any]], audio: dict[str, Any]) -> list[float]:
    energy = list(audio.get("energy_curve") or [])
    out: list[float] = []
    cursor = 0.0
    for item in media:
        if item.get("type") == "photo":
            duration = _raw_photo_duration(item, _energy_at(energy, cursor))
        else:
            ts, te = item.get("trim_start_sec"), item.get("trim_end_sec")
            duration = max(0.5, float(te) - float(ts)) if ts is not None and te is not None else max(0.5, float(item.get("duration_sec") or 0.0))
        out.append(round(duration, 3))
        cursor += duration
    return out


def _snap_to_beats(media: list[dict[str, Any]], wanted: list[float], beats: list[float], target_total: float) -> list[float]:
    if not beats or target_total <= 0:
        return wanted
    out = list(wanted)
    cursor = 0.0
    # Only intermediate endpoints are snapped. The final item absorbs the exact remainder.
    for i, item in enumerate(media):
        if i == len(media) - 1:
            out[i] = max(0.1, round(target_total - cursor, 3))
            break
        if item.get("type") == "photo":
            target_end = cursor + out[i]
            candidates = [b for b in beats if cursor + PHOTO_MIN_SEC - 1e-6 <= b <= min(cursor + PHOTO_MAX_SEC, target_total - PHOTO_MIN_SEC) + 1e-6]
            if candidates:
                out[i] = round(min(candidates, key=lambda b: abs(b - target_end)) - cursor, 3)
        cursor += out[i]
    return out


def _ken_burns_params(movement: str, rng: random.Random) -> dict[str, Any]:
    if movement == "zoom_in_slow":
        return {"movement": movement, "zoom_from": 1.0, "zoom_to": round(rng.uniform(1.08, ZOOM_MAX), 3), "pan_x_from": 0.5, "pan_x_to": 0.5, "pan_y_from": 0.5, "pan_y_to": 0.5}
    if movement == "zoom_out_slow":
        return {"movement": movement, "zoom_from": round(rng.uniform(1.08, ZOOM_MAX), 3), "zoom_to": 1.0, "pan_x_from": 0.5, "pan_x_to": 0.5, "pan_y_from": 0.5, "pan_y_to": 0.5}
    if movement in ("pan_left", "pan_right"):
        x = (1.0, 0.0) if movement == "pan_left" else (0.0, 1.0)
        return {"movement": movement, "zoom_from": 1.1, "zoom_to": 1.1, "pan_x_from": x[0], "pan_x_to": x[1], "pan_y_from": 0.5, "pan_y_to": 0.5}
    xa = (0.0, 1.0) if rng.random() < 0.5 else (1.0, 0.0)
    ya = (0.0, 1.0) if rng.random() < 0.5 else (1.0, 0.0)
    return {"movement": movement, "zoom_from": 1.0, "zoom_to": 1.12, "pan_x_from": xa[0], "pan_x_to": xa[1], "pan_y_from": ya[0], "pan_y_to": ya[1]}


def _movement_cycle(n: int, rng: random.Random) -> list[str]:
    out: list[str] = []
    while len(out) < n:
        cycle = rng.sample(list(MOVEMENTS), len(MOVEMENTS))
        if out and cycle[0] == out[-1]:
            cycle[0], cycle[1] = cycle[1], cycle[0]
        out.extend(cycle)
    return out[:n]


async def run(project_state: dict) -> dict:
    media = sorted(project_state.get("media", []), key=lambda m: m.get("order_index", 0))
    if not media:
        project_state["edit_decision_list"] = []
        return project_state

    audio = project_state.get("audio") or {}
    audio_dur = float(audio.get("duration_sec") or 0.0)
    fixed_total = sum(
        max(0.5, float(m.get("trim_end_sec") - m.get("trim_start_sec"))) if m.get("type") == "video" and m.get("trim_start_sec") is not None and m.get("trim_end_sec") is not None
        else (0.0 if m.get("type") == "photo" else max(0.5, float(m.get("duration_sec") or 0.0)))
        for m in media
    )
    photo_count = sum(m.get("type") == "photo" for m in media)
    minimum_total = fixed_total + photo_count * PHOTO_MIN_SEC
    target_total = max(audio_dur, minimum_total) if audio_dur > 0 else 0.0

    durations = _initial_durations(media, audio)
    if target_total > 0:
        durations = _fit_total(durations, media, target_total)
        durations = _snap_to_beats(media, durations, audio_dur if audio_dur > 0 else target_total, target_total)
        # If the soundtrack is long enough, preserve it exactly; otherwise use the
        # minimum feasible video duration rather than creating zero/negative clips.
        durations = _fit_total(durations, media, target_total)

    rng = _rng(str(project_state.get("project_id", "")))
    movements = _movement_cycle(photo_count, rng)
    movement_index = 0
    beats = _music_grid(audio)
    energy = list(audio.get("energy_curve") or [])

    edl: list[dict[str, Any]] = []
    cursor = 0.0
    for i, item in enumerate(media):
        duration = round(float(durations[i]), 3)
        if item.get("type") == "photo":
            item["duration_sec"] = duration
            item["ai_duration_sec"] = duration
            item["ai_edit_score"] = round(_photo_score(item), 3)
            item["duration_source"] = "ai_music" if audio_dur > 0 else "vision"
            item["music_sync"] = bool(beats)
            kb = _ken_burns_params(movements[movement_index], rng)
            movement_index += 1
        else:
            kb = None

        transition_in = 0.0 if beats or i == 0 else round(_clamp(0.75 - 0.25 * _energy_at(energy, cursor), TRANS_MIN_SEC, TRANS_MAX_SEC), 3)
        edl.append({
            "media_id": item["id"],
            "start_sec_in_final_video": round(cursor, 3),
            "duration_sec": duration,
            "ken_burns": kb,
            "transition_in": transition_in,
            "transition_out": transition_in if i < len(media) - 1 else 0.0,
            "editorial_score": round(_photo_score(item), 3) if item.get("type") == "photo" else None,
            "duration_reason": "vision+music" if item.get("type") == "photo" and audio_dur > 0 else "vision" if item.get("type") == "photo" else "source-video-duration",
        })
        cursor += duration
        if transition_in > 0:
            cursor -= transition_in

    # With a real beat grid every transition is a hard musical cut, so the sum of
    # durations is also the final video duration. Correct any remaining fractional drift.
    if audio_dur > 0 and beats and edl:
        actual = sum(float(e["duration_sec"]) for e in edl)
        delta = round(audio_dur - actual, 3)
        if abs(delta) > 0.01:
            last_photo = next((j for j in reversed(range(len(edl))) if media[j].get("type") == "photo"), None)
            if last_photo is not None:
                new_d = _clamp(float(edl[last_photo]["duration_sec"]) + delta, PHOTO_MIN_SEC, PHOTO_MAX_SEC)
                edl[last_photo]["duration_sec"] = round(new_d, 3)
                media[last_photo]["duration_sec"] = edl[last_photo]["duration_sec"]
                cursor = 0.0
                for entry in edl:
                    entry["start_sec_in_final_video"] = round(cursor, 3)
                    cursor += float(entry["duration_sec"])

    project_state["edit_decision_list"] = edl
    project_state["edit_summary"] = {
        "vision_photos": sum(1 for m in media if m.get("type") == "photo" and m.get("vision_ai_used")),
        "total_photos": photo_count,
        "music_synced": bool(beats),
        "bpm": audio.get("bpm", 0.0),
        "planned_duration_sec": round(sum(float(e["duration_sec"]) for e in edl) - sum(float(e["transition_in"]) for e in edl[1:]), 3),
    }
    return project_state
