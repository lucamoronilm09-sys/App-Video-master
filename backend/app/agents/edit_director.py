"""Agente 3: Edit Director (architettura sez. 5) — il "regista".

Stile "album/ricordo": pacato, mai frenetico.
- Foto: movimento Ken Burns a rotazione (mai due uguali consecutivi),
  DOLCE (zoom <= 1.15x, pan <= 12% del frame).
- Video: nessun Ken Burns (gia' in movimento), durate intoccabili (no speed-change).
- Transizioni: solo crossfade 0.6-1.0s, con durata guidata dall'energia del
  brano (morbide sui passaggi calmi, più brevi sull'energia) e mai due valori
  identici consecutivi, per un ritmo meno meccanico.
- Beat markers / energy: guida MORBIDA — micro-ritocchi alle foto (<=0.4s,
  entro [2.5, 6.0]s) per avvicinare gli inizi clip ai beat, mai stretch bruschi.
- Se c'e' audio: la durata totale viene adattata a quella dell'audio
  distribuendo la differenza sulle foto (mai tagliare l'audio a meta' frase).

Output: edit_decision_list [{media_id, start_sec_in_final_video, duration_sec,
ken_burns|None, transition_in, transition_out}]. Deterministico per project_id
(idempotenza): stesso ordine + stessa musica = stesso montaggio.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

TRANS_MIN_SEC = 0.6
TRANS_MAX_SEC = 1.0
ZOOM_MAX = 1.15
PAN_MAX_FRAC = 0.12
# Limiti per l'aggiustamento delle durate foto durante il fit-audio e beat-sync:
# la durata finale di ogni foto resta sempre in [2.5, 6.0]s (scelta utente).
PHOTO_ADJUSTED_MIN_SEC = 2.5
PHOTO_ADJUSTED_MAX_SEC = 6.0
PHOTO_DEFAULT_SEC = 4.5
BEAT_TOL_SEC = 0.8
NUDGE_MAX_SEC = 0.4

MOVEMENTS = ("pan_left", "pan_right", "zoom_in_slow", "zoom_out_slow", "pan_and_zoom_diag")


def _rng(project_id: str) -> random.Random:
    return random.Random(hashlib.sha256(project_id.encode("utf-8")).digest())


def _effective_duration(item: dict[str, Any]) -> float:
    if item.get("type") == "photo":
        dur = float(item.get("duration_sec") or 0.0)
        return dur if dur > 0 else PHOTO_DEFAULT_SEC
    ts, te = item.get("trim_start_sec"), item.get("trim_end_sec")
    if ts is not None and te is not None:
        return max(0.5, float(te) - float(ts))
    return max(0.5, float(item.get("duration_sec") or 0.0))


def _ken_burns_params(movement: str, rng: random.Random) -> dict[str, Any]:
    if movement == "zoom_in_slow":
        zt = round(rng.uniform(1.08, ZOOM_MAX), 3)
        return {"movement": movement, "zoom_from": 1.0, "zoom_to": zt,
                "pan_x_from": 0.5, "pan_x_to": 0.5, "pan_y_from": 0.5, "pan_y_to": 0.5}
    if movement == "zoom_out_slow":
        zf = round(rng.uniform(1.08, ZOOM_MAX), 3)
        return {"movement": movement, "zoom_from": zf, "zoom_to": 1.0,
                "pan_x_from": 0.5, "pan_x_to": 0.5, "pan_y_from": 0.5, "pan_y_to": 0.5}
    if movement in ("pan_left", "pan_right"):
        x = (1.0, 0.0) if movement == "pan_left" else (0.0, 1.0)
        return {"movement": movement, "zoom_from": 1.1, "zoom_to": 1.1,
                "pan_x_from": x[0], "pan_x_to": x[1], "pan_y_from": 0.5, "pan_y_to": 0.5}
    # pan_and_zoom_diag
    xa = (0.0, 1.0) if rng.random() < 0.5 else (1.0, 0.0)
    ya = (0.0, 1.0) if rng.random() < 0.5 else (1.0, 0.0)
    return {"movement": movement, "zoom_from": 1.0, "zoom_to": 1.12,
            "pan_x_from": xa[0], "pan_x_to": xa[1],
            "pan_y_from": ya[0], "pan_y_to": ya[1]}


def _movement_cycle(n_photos: int, rng: random.Random) -> list[str]:
    """Rotazione senza mai due movimenti uguali consecutivi (nemmeno a cavallo dei cicli)."""
    out: list[str] = []
    while len(out) < n_photos:
        cyc = rng.sample(list(MOVEMENTS), len(MOVEMENTS))
        if out and cyc[0] == out[-1]:
            cyc[0], cyc[1] = cyc[1], cyc[0]
        out.extend(cyc)
    return out[:n_photos]


def _nearest_marker(markers: list[float], t: float, tol: float) -> float | None:
    best: float | None = None
    for m in markers:
        d = m - t
        if abs(d) <= tol and (best is None or abs(d) < abs(best - t)):
            best = m
    return best


def _distribute_diff(durations: list[float], photo_idx: list[int], diff: float) -> list[float]:
    """Distribuisce diff sulle foto entro [PHOTO_ADJUSTED_MIN_SEC, PHOTO_ADJUSTED_MAX_SEC] (dalle ultime)."""
    if not photo_idx or diff == 0:
        return durations
    share = diff / len(photo_idx)
    out = list(durations)
    for i in reversed(photo_idx):
        out[i] = round(max(PHOTO_ADJUSTED_MIN_SEC, min(PHOTO_ADJUSTED_MAX_SEC, out[i] + share)), 2)
    return out


def _timeline_total(durations: list[float], gaps: list[float]) -> float:
    total = durations[0] if durations else 0.0
    for i in range(1, len(durations)):
        total += durations[i] - (gaps[i - 1] if i - 1 < len(gaps) else 0.0)
    return round(total, 2)


async def run(project_state: dict) -> dict:
    media = sorted(project_state.get("media", []), key=lambda m: m.get("order_index", 0))
    if not media:
        project_state["edit_decision_list"] = []
        return project_state

    rng = _rng(str(project_state.get("project_id", "")))
    n = len(media)
    is_photo = [m.get("type") == "photo" for m in media]
    durations = [_effective_duration(m) for m in media]
    gaps = [round(rng.uniform(TRANS_MIN_SEC, TRANS_MAX_SEC), 2) for _ in range(n - 1)]

    def starts_for(durs: list[float]) -> list[float]:
        starts = [0.0]
        for i in range(1, n):
            starts.append(round(starts[i - 1] + durs[i - 1] - gaps[i - 1], 2))
        return starts

    # Dissolvenze meno meccaniche: la durata segue l'energia del brano
    # (calma -> dissolvenza più lunga e morbida, energia -> più breve) ed
    # evita due valori identici consecutivi. Resta in [0.6, 1.0]s e
    # deterministica (stesso progetto = stesso montaggio).
    energy = list((project_state.get("audio") or {}).get("energy_curve", []) or [])
    if energy:
        provisional = starts_for(durations)
        tuned: list[float] = []
        for i in range(n - 1):
            idx = min(len(energy) - 1, max(0, int(provisional[i + 1])))
            try:
                level = max(0.0, min(1.0, float(energy[idx])))
            except (TypeError, ValueError):
                level = 0.5
            g = round(max(TRANS_MIN_SEC, min(TRANS_MAX_SEC,
                                            gaps[i] * (1.10 - 0.20 * level))), 2)
            tuned.append(g)
        for i in range(1, len(tuned)):
            if tuned[i] == tuned[i - 1]:
                step = 0.05 if tuned[i] < TRANS_MAX_SEC else -0.05
                cand = round(tuned[i] + step, 2)
                if TRANS_MIN_SEC <= cand <= TRANS_MAX_SEC:
                    tuned[i] = cand
        gaps = tuned

    # Guida morbida: avvicina gli inizi clip ai beat ritoccando la foto precedente.
    markers = sorted(float(x) for x in (project_state.get("audio") or {}).get("beat_markers_sec", []))
    if markers:
        starts = starts_for(durations)
        for i in range(1, n):
            target = _nearest_marker(markers, starts[i], BEAT_TOL_SEC)
            if target is None or not is_photo[i - 1]:
                continue
            shift = max(-NUDGE_MAX_SEC, min(NUDGE_MAX_SEC, target - starts[i]))
            new_dur = durations[i - 1] + shift
            if PHOTO_ADJUSTED_MIN_SEC <= new_dur <= PHOTO_ADJUSTED_MAX_SEC:
                durations[i - 1] = round(new_dur, 2)
                starts = starts_for(durations)

    # Adatta il totale alla durata audio distribuendo la differenza sulle foto.
    audio_dur = float((project_state.get("audio") or {}).get("duration_sec") or 0.0)
    photo_idx = [i for i, p in enumerate(is_photo) if p]
    if audio_dur > 0 and photo_idx:
        total = _timeline_total(durations, gaps)
        durations = _distribute_diff(durations, photo_idx, audio_dur - total)

    # Loop QA -> Edit Director (M6): il QA puo' chiedere di riadattare il
    # totale (es. dopo un rigetto su durata); il feedback vince sull'audio-fit.
    for hint in project_state.get("qa_feedback", []) or []:
        if hint.get("type") == "fit_total" and hint.get("total_sec"):
            total = _timeline_total(durations, gaps)
            durations = _distribute_diff(durations, photo_idx, float(hint["total_sec"]) - total)

    starts = starts_for(durations)
    movements = _movement_cycle(sum(is_photo), rng)
    photo_k = 0
    edl: list[dict[str, Any]] = []
    for i, m in enumerate(media):
        kb = None
        if is_photo[i]:
            kb = _ken_burns_params(movements[photo_k], rng)
            photo_k += 1
        edl.append({
            "media_id": m["id"],
            "start_sec_in_final_video": starts[i],
            "duration_sec": round(durations[i], 2),
            "ken_burns": kb,
            "transition_in": 0.0 if i == 0 else gaps[i - 1],
            "transition_out": 0.0 if i == n - 1 else gaps[i],
        })
    project_state["edit_decision_list"] = edl
    return project_state
