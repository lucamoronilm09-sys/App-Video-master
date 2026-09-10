"""Agente 3: Edit Director — montaggio photo-aware e music-aware.

La durata non viene più calcolata in Sequence. Qui sono disponibili sia il
profilo Vision della foto sia la struttura audio, quindi la scelta è fatta
sul contesto completo.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

TRANS_MIN_SEC = 0.5
TRANS_MAX_SEC = 0.9
ZOOM_MAX = 1.15
PHOTO_MIN_SEC = 2.0
PHOTO_MAX_SEC = 7.0
PHOTO_DEFAULT_SEC = 3.5
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
    profile = item.get("vision_analysis")
    return profile if isinstance(profile, dict) else {}


def _photo_score(item: dict[str, Any]) -> float:
    """How much editorial attention this photo deserves."""
    v = _vision(item)
    people = v.get("people_count", item.get("face_count", 0))
    try:
        people = max(0, int(people))
    except (TypeError, ValueError):
        people = 0

    importance = _f(v.get("importance", item.get("importance_score", 0.5)))
    emotion = _f(v.get("emotional_intensity", 0.5))
    clarity = _f(v.get("subject_clarity", item.get("detail_score", 0.5)))
    interest = _f(v.get("visual_interest", item.get("composition_score", 0.5)))
    sharpness = _f(item.get("sharpness_score", 0.5))
    contrast = _f(item.get("contrast_score", 0.5))
    faces = _clamp(people / 4.0, 0.0, 1.0)

    return _clamp(
        0.36 * importance
        + 0.18 * emotion
        + 0.14 * clarity
        + 0.12 * interest
        + 0.08 * sharpness
        + 0.05 * contrast
        + 0.07 * faces,
        0.0,
        1.0,
    )


def _raw_photo_duration(item: dict[str, Any], music_energy: float) -> float:
    v = _vision(item)
    score = _photo_score(item)
    pacing = str(v.get("recommended_pacing", "normal")).lower()

    # Base screen time from visual/editorial value.
    duration = PHOTO_MIN_SEC + (PHOTO_MAX_SEC - PHOTO_MIN_SEC) * (score ** 0.72)

    # Emotional/important photos get more time; energetic music tightens pacing.
    duration += 0.55 * _f(v.get("emotional_intensity", 0.5))
    duration -= 0.75 * _f(music_energy, 0.5)

    if pacing == "fast":
        duration -= 0.60
    elif pacing == "slow":
        duration += 0.65
    elif pacing == "hold":
        duration += 1.05

    if bool(v.get("is_group_photo")):
        duration += 0.25
    if bool(v.get("is_closeup")):
        duration += 0.15
    if bool(v.get("is_action")):
        duration -= 0.25

    return _clamp(duration, PHOTO_MIN_SEC, PHOTO_MAX_SEC)


def _nearest_grid_time(
    target: float,
    grid: list[float],
    minimum: float,
    maximum: float,
    remaining_slots: int,
    remaining_min: float,
) -> float | None:
    candidates = [t for t in grid if target - 1e-6 <= t <= maximum + 1e-6 and t >= minimum - 1e-6]
    if not candidates:
        return None
    valid: list[float] = []
    for t in candidates:
        if t + remaining_min * max(0, remaining_slots) <= maximum + 1e-6:
            valid.append(t)
    pool = valid or candidates
    return min(pool, key=lambda x: abs(x - target))


def _fit_total(durations: list[float], media: list[dict[str, Any]], target_total: float, overlaps: list[float]) -> list[float]:
    """Fit to the music duration while preserving editorial priority."""
    out = list(durations)
    if not out or target_total <= 0:
        return out
    current = sum(out) - sum(overlaps)
    diff = round(target_total - current, 3)
    photo_indices = [i for i, m in enumerate(media) if m.get("type") == "photo"]
    if not photo_indices or abs(diff) < 0.02:
        return out

    ranked = sorted(photo_indices, key=lambda i: _photo_score(media[i]), reverse=diff > 0)
    remaining = abs(diff)
    for i in ranked:
        if remaining < 0.01:
            break
        if diff > 0:
            room = PHOTO_MAX_SEC - out[i]
        else:
            room = out[i] - PHOTO_MIN_SEC
        change = min(max(0.0, room), remaining)
        out[i] = round(out[i] + change if diff > 0 else out[i] - change, 3)
        remaining -= change
    return out


def _ken_burns_params(movement: str, rng: random.Random) -> dict[str, Any]:
    if movement == "zoom_in_slow":
        zt = round(rng.uniform(1.08, ZOOM_MAX), 3)
        return {"movement": movement, "zoom_from": 1.0, "zoom_to": zt, "pan_x_from": 0.5, "pan_x_to": 0.5, "pan_y_from": 0.5, "pan_y_to": 0.5}
    if movement == "zoom_out_slow":
        zf = round(rng.uniform(1.08, ZOOM_MAX), 3)
        return {"movement": movement, "zoom_from": zf, "zoom_to": 1.0, "pan_x_from": 0.5, "pan_x_to": 0.5, "pan_y_from": 0.5, "pan_y_to": 0.5}
    if movement in ("pan_left", "pan_right"):
        x = (1.0, 0.0) if movement == "pan_left" else (0.0, 1.0)
        return {"movement": movement, "zoom_from": 1.1, "zoom_to": 1.1, "pan_x_from": x[0], "pan_x_to": x[1], "pan_y_from": 0.5, "pan_y_to": 0.5}
    xa = (0.0, 1.0) if rng.random() < 0.5 else (1.0, 0.0)
    ya = (0.0, 1.0) if rng.random() < 0.5 else (1.0, 0.0)
    return {"movement": movement, "zoom_from": 1.0, "zoom_to": 1.12, "pan_x_from": xa[0], "pan_x_to": xa[1], "pan_y_from": ya[0], "pan_y_to": ya[1]}


def _movement_cycle(n_photos: int, rng: random.Random) -> list[str]:
    out: list[str] = []
    while len(out) < n_photos:
        cycle = rng.sample(list(MOVEMENTS), len(MOVEMENTS))
        if out and cycle[0] == out[-1]:
            cycle[0], cycle[1] = cycle[1], cycle[0]
        out.extend(cycle)
    return out[:n_photos]


def _energy_at(energy: list[Any], t: float) -> float:
    if not energy:
        return 0.5
    idx = max(0, min(len(energy) - 1, int(t)))
    return _f(energy[idx], 0.5)


def _music_grid(audio: dict[str, Any]) -> list[float]:
    beats = [float(x) for x in (audio.get("beat_times_sec") or [])]
    if beats:
        return beats
    markers = [float(x) for x in (audio.get("beat_markers_sec") or [])]
    return markers


def _duration_plan(media: list[dict[str, Any]], audio: dict[str, Any]) -> list[float]:
    """Create durations using vision importance + music energy + exact beat grid."""
    energy = list(audio.get("energy_curve") or [])
    bpm = float(audio.get("bpm") or 0.0)
    beat_grid = _music_grid(audio)
    audio_dur = float(audio.get("duration_sec") or 0.0)

    raw: list[float] = []
    for i, item in enumerate(media):
        if item.get("type") != "photo":
            ts, te = item.get("trim_start_sec"), item.get("trim_end_sec")
            raw.append(max(0.5, float(te) - float(ts)) if ts is not None and te is not None else max(0.5, float(item.get("duration_sec") or 0.0)))
            continue
        # Estimate music context from current provisional position.
        provisional = sum(raw)
        raw.append(_raw_photo_duration(item, _energy_at(energy, provisional)))

    if audio_dur > 0:
        overlaps = [round(min(0.65, max(0.0, d * 0.16)), 3) for d in raw[:-1]]
        raw = _fit_total(raw, media, audio_dur, overlaps)

    # Snap photo durations to real beats whenever possible. Rather than forcing
    # every image to the same length, choose a nearby musical endpoint inside a
    # content-dependent window.
    if beat_grid:
        cursor = 0.0
        snapped: list[float] = []
        for i, (item, wanted) in enumerate(zip(media, raw)):
            remaining_slots = len(media) - i - 1
            if item.get("type") != "photo":
                snapped.append(wanted)
                cursor += wanted
                continue
            minimum_end = cursor + PHOTO_MIN_SEC
            maximum_end = cursor + PHOTO_MAX_SEC
            target_end = cursor + wanted
            remaining_min = PHOTO_MIN_SEC if any(m.get("type") == "photo" for m in media[i + 1:]) else 0.5
            end = _nearest_grid_time(target_end, beat_grid, minimum_end, maximum_end, remaining_slots, remaining_min)
            if end is None:
                snapped_duration = wanted
            else:
                snapped_duration = end - cursor
            snapped.append(round(_clamp(snapped_duration, PHOTO_MIN_SEC, PHOTO_MAX_SEC), 3))
            cursor += snapped[-1]

        if audio_dur > 0:
            overlaps = [0.0] * max(0, len(snapped) - 1)
            snapped = _fit_total(snapped, media, audio_dur, overlaps)
        raw = snapped

    if bpm > 0:
        # Keep durations on useful beat multiples when possible.
        beat = 60.0 / bpm
        for i, item in enumerate(media):
            if item.get("type") != "photo":
                continue
            lo = max(1, int(round(PHOTO_MIN_SEC / beat)))
            hi = max(lo, int(round(PHOTO_MAX_SEC / beat)))
            units = int(round(raw[i] / beat))
            units = max(lo, min(hi, units))
            raw[i] = round(units * beat, 3)

    return raw


async def run(project_state: dict) -> dict:
    media = sorted(project_state.get("media", []), key=lambda m: m.get("order_index", 0))
    if not media:
        project_state["edit_decision_list"] = []
        return project_state

    rng = _rng(str(project_state.get("project_id", "")))
    audio = project_state.get("audio") or {}
    durations = _duration_plan(media, audio)

    # Human-readable metadata makes the decision inspectable in the UI/debug logs.
    for i, item in enumerate(media):
        if item.get("type") == "photo":
            item["ai_duration_sec"] = round(durations[i], 3)
            item["ai_edit_score"] = round(_photo_score(item), 3)
            item["music_sync"] = bool(audio.get("beat_times_sec"))

    n = len(media)
    is_photo = [m.get("type") == "photo" for m in media]
    movements = _movement_cycle(sum(is_photo), rng)
    photo_k = 0

    # Hard cuts are intentionally used on strong musical moments; softer moments
    # get short crossfades so the transition itself does not drift off the beat.
    energy = list(audio.get("energy_curve") or [])
    beats = _music_grid(audio)
    bpm = float(audio.get("bpm") or 0.0)

    edl: list[dict[str, Any]] = []
    cursor = 0.0
    for i, item in enumerate(media):
        duration = round(float(durations[i]), 3)
        if i == 0:
            transition_in = 0.0
        else:
            level = _energy_at(energy, cursor)
            beat_distance = min((abs(cursor - b) for b in beats), default=999.0)
            # On/near a beat: cut exactly there. Else use a short crossfade.
            transition_in = 0.0 if beat_distance <= max(0.035, (60.0 / bpm) * 0.06) else round(_clamp(0.75 - 0.25 * level, TRANS_MIN_SEC, TRANS_MAX_SEC), 3)

        kb = None
        if is_photo[i]:
            kb = _ken_burns_params(movements[photo_k], rng)
            photo_k += 1

        start = round(cursor, 3)
        edl.append({
            "media_id": item["id"],
            "start_sec_in_final_video": start,
            "duration_sec": duration,
            "ken_burns": kb,
            "transition_in": transition_in,
            "transition_out": 0.0,
        })
        cursor += duration
        if i < n - 1:
            # Kept in EDL as explicit overlap; next entry's transition_in matches it.
            edl[-1]["transition_out"] = transition_in if transition_in > 0 else 0.0
            cursor -= transition_in

    # The final media should end at the audio end when the soundtrack is available.
    if audio.get("duration_sec") and edl:
        target = float(audio["duration_sec"])
        end = cursor
        delta = target - end
        if abs(delta) > 0.02:
            last_photo = next((j for j in reversed(range(n)) if is_photo[j]), None)
            if last_photo is not None:
                new_d = _clamp(float(edl[last_photo]["duration_sec"]) + delta, PHOTO_MIN_SEC, PHOTO_MAX_SEC)
                actual_change = new_d - float(edl[last_photo]["duration_sec"])
                edl[last_photo]["duration_sec"] = round(new_d, 3)

    project_state["edit_decision_list"] = edl
    return project_state
