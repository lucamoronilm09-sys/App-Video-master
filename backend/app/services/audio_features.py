"""Feature audio con numpy + ffmpeg (niente stack librosa/scipy).

Decodifica in PCM mono via ffmpeg e calcola:
- duration_sec (dalla lunghezza decodificata),
- energy_curve: RMS per finestre di 1s, normalizzata 0..1,
- bpm: autocorrelazione dell'onset envelope (spectral flux) in 60..180 BPM,
- beat_markers_sec: griglia di markers strutturali (uno per battuta 4/4,
  quindi "beat principali/forti, non ogni singolo beat") ancorata al primo
  onset forte, come guida morbida per l'Edit Director (M4).

Deterministico a parita' di file (idempotenza, architettura sez. 3).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np

SAMPLE_RATE = 22050
HOP = 512
FRAME = 2048
MIN_BPM = 60.0
MAX_BPM = 180.0
BEATS_PER_MARKER = 4  # una battuta 4/4: solo beat strutturali, non ogni beat

AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac", ".opus", ".aac", ".wma"}


def decode_mono(path: Path, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Decodifica l'audio in float32 mono via ffmpeg (pipe raw). Solleva se illeggibile."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-ac", "1", "-ar", str(sr), "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise ValueError(f"Audio non decodificabile: {path.name}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def energy_curve(samples: np.ndarray, sr: int = SAMPLE_RATE) -> list[float]:
    """RMS per secondo, normalizzato 0..1 (3 decimali)."""
    if samples.size == 0:
        return []
    n_win = sr  # 1 secondo
    n_full = samples.size // n_win
    curve = [0.0] * (n_full + (1 if samples.size % n_win else 0))
    for i in range(n_full):
        w = samples[i * n_win:(i + 1) * n_win]
        curve[i] = float(np.sqrt(np.mean(w * w)))
    if samples.size % n_win:
        w = samples[n_full * n_win:]
        curve[n_full] = float(np.sqrt(np.mean(w * w)))
    peak = max(curve) if curve else 0.0
    if peak <= 1e-9:
        return [0.0] * len(curve)
    return [round(v / peak, 3) for v in curve]


def onset_envelope(samples: np.ndarray) -> np.ndarray:
    """Spectral flux su frame Hann 2048/hop 512 (log-magnitudo)."""
    if samples.size < FRAME:
        return np.zeros(1, dtype=np.float64)
    window = np.hanning(FRAME)
    n_frames = 1 + (samples.size - FRAME) // HOP
    prev = None
    flux = np.zeros(n_frames, dtype=np.float64)
    for i in range(n_frames):
        frame = samples[i * HOP:i * HOP + FRAME] * window
        mag = np.abs(np.fft.rfft(frame))
        lm = np.log1p(100.0 * mag)
        if prev is not None:
            flux[i] = float(np.sum(np.maximum(0.0, lm - prev)))
        prev = lm
    return flux


def estimate_bpm(onsets: np.ndarray) -> float:
    """BPM via autocorrelazione dell'onset envelope (range 60..180). 0.0 se non stimabile.

    Euristica anti-ottava: tra i picchi entro l'85% del massimo globale si sceglie
    il lag piu' piccolo (il tactus piu' veloce e forte), poi raffinamento parabolico.
    """
    oe = onsets - np.mean(onsets)
    if np.max(np.abs(oe)) <= 1e-9 or oe.size < 8:
        return 0.0
    corr = np.correlate(oe, oe, mode="full")[oe.size - 1:]
    lag_min = max(2, int(round(60.0 * SAMPLE_RATE / (HOP * MAX_BPM))))
    lag_max = int(round(60.0 * SAMPLE_RATE / (HOP * MIN_BPM)))
    if lag_max >= corr.size:
        lag_max = corr.size - 1
    if lag_max <= lag_min:
        return 0.0
    seg = corr[lag_min:lag_max + 1]
    peak = float(np.max(seg))
    if peak <= 1e-9:
        return 0.0
    # picchi locali >= 85% del max; il piu' piccolo vince (anti ottava-down)
    best_i = int(np.argmax(seg))
    for i in range(1, len(seg) - 1):
        if seg[i] >= 0.85 * peak and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]:
            best_i = i
            break
    # interpolazione parabolica per precisione sub-lag
    lag = float(best_i + lag_min)
    i = best_i
    if 0 < i < len(seg) - 1:
        y0, y1, y2 = float(seg[i - 1]), float(seg[i]), float(seg[i + 1])
        denom = (y0 - 2 * y1 + y2)
        if denom != 0:
            lag += float(np.clip(0.5 * (y0 - y2) / denom, -0.5, 0.5))
    bpm = 60.0 * SAMPLE_RATE / (HOP * lag)
    return round(float(bpm), 1)


def beat_markers(onsets: np.ndarray, bpm: float, duration_sec: float) -> list[float]:
    """Un marker per battuta 4/4 ancorato al primo onset forte (max nei primi 4s)."""
    if bpm <= 0 or duration_sec <= 0:
        return []
    frame_sec = HOP / SAMPLE_RATE
    warm = min(len(onsets), int(4.0 / frame_sec))
    anchor_idx = int(np.argmax(onsets[:warm])) if warm > 0 else 0
    anchor = round(anchor_idx * frame_sec, 2)
    bar = BEATS_PER_MARKER * 60.0 / bpm
    markers: list[float] = []
    t = anchor
    while t < duration_sec - 1e-6 and len(markers) < 5000:
        markers.append(round(t, 2))
        t = round(t + bar, 2)
    return markers or [anchor]


def analyze_audio(path: Path) -> dict[str, Any]:
    """Analisi completa: dict {duration_sec, bpm, beat_markers_sec, energy_curve}."""
    samples = decode_mono(path)
    duration_sec = round(float(samples.size) / SAMPLE_RATE, 2)
    if float(np.max(np.abs(samples))) <= 1e-9:
        return {"duration_sec": duration_sec, "bpm": 0.0,
                "beat_markers_sec": [], "energy_curve": [0.0] * max(1, int(duration_sec))}
    energy = energy_curve(samples)
    onsets = onset_envelope(samples)
    bpm = estimate_bpm(onsets)
    markers = beat_markers(onsets, bpm, duration_sec)
    return {"duration_sec": duration_sec, "bpm": bpm,
            "beat_markers_sec": markers, "energy_curve": energy}
