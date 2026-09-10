"""Feature audio con numpy + ffmpeg (niente stack librosa/scipy).

Produce una griglia musicale utile al montaggio:
- duration_sec,
- energy_curve (RMS per secondo),
- bpm,
- beat_times_sec (ogni beat),
- downbeat_times_sec (prima battuta, 4/4 euristico),
- beat_markers_sec (alias storico: downbeat/bar markers).

L'analisi è deterministica a parità di file.
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
BEATS_PER_BAR = 4

AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac", ".opus", ".aac", ".wma"}


def decode_mono(path: Path, sr: int = SAMPLE_RATE) -> np.ndarray:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr),
         "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise ValueError(f"Audio non decodificabile: {path.name}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def energy_curve(samples: np.ndarray, sr: int = SAMPLE_RATE) -> list[float]:
    if samples.size == 0:
        return []
    n_full = samples.size // sr
    curve = [0.0] * (n_full + (1 if samples.size % sr else 0))
    for i in range(n_full):
        w = samples[i * sr:(i + 1) * sr]
        curve[i] = float(np.sqrt(np.mean(w * w)))
    if samples.size % sr:
        w = samples[n_full * sr:]
        curve[n_full] = float(np.sqrt(np.mean(w * w)))
    peak = max(curve) if curve else 0.0
    if peak <= 1e-9:
        return [0.0] * len(curve)
    return [round(v / peak, 3) for v in curve]


def onset_envelope(samples: np.ndarray) -> np.ndarray:
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
    oe = onsets - np.mean(onsets)
    if np.max(np.abs(oe)) <= 1e-9 or oe.size < 8:
        return 0.0
    corr = np.correlate(oe, oe, mode="full")[oe.size - 1:]
    lag_min = max(2, int(round(60.0 * SAMPLE_RATE / (HOP * MAX_BPM))))
    lag_max = min(int(round(60.0 * SAMPLE_RATE / (HOP * MIN_BPM))), corr.size - 1)
    if lag_max <= lag_min:
        return 0.0
    seg = corr[lag_min:lag_max + 1]
    peak = float(np.max(seg))
    if peak <= 1e-9:
        return 0.0
    best_i = int(np.argmax(seg))
    for i in range(1, len(seg) - 1):
        if seg[i] >= 0.85 * peak and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]:
            best_i = i
            break
    lag = float(best_i + lag_min)
    if 0 < best_i < len(seg) - 1:
        y0, y1, y2 = float(seg[best_i - 1]), float(seg[best_i]), float(seg[best_i + 1])
        denom = y0 - 2 * y1 + y2
        if denom != 0:
            lag += float(np.clip(0.5 * (y0 - y2) / denom, -0.5, 0.5))
    return round(float(60.0 * SAMPLE_RATE / (HOP * lag)), 1)


def _anchor_from_onsets(onsets: np.ndarray, max_seconds: float = 4.0) -> float:
    frame_sec = HOP / SAMPLE_RATE
    warm = min(len(onsets), max(1, int(max_seconds / frame_sec)))
    if warm <= 0:
        return 0.0
    return round(int(np.argmax(onsets[:warm])) * frame_sec, 3)


def beat_grid(onsets: np.ndarray, bpm: float, duration_sec: float) -> tuple[list[float], list[float]]:
    """Return (all beats, downbeats) using the strongest early onset as anchor."""
    if bpm <= 0 or duration_sec <= 0:
        return [], []
    beat = 60.0 / bpm
    anchor = _anchor_from_onsets(onsets)
    beats: list[float] = []
    t = anchor
    while t < duration_sec - 1e-6 and len(beats) < 20000:
        if t >= 0:
            beats.append(round(t, 3))
        t += beat
    downbeats = beats[::BEATS_PER_BAR]
    return beats, downbeats


def analyze_audio(path: Path) -> dict[str, Any]:
    samples = decode_mono(path)
    duration_sec = round(float(samples.size) / SAMPLE_RATE, 2)
    if float(np.max(np.abs(samples))) <= 1e-9:
        zeros = [0.0] * max(1, int(np.ceil(duration_sec)))
        return {
            "duration_sec": duration_sec,
            "bpm": 0.0,
            "beat_times_sec": [],
            "downbeat_times_sec": [],
            "beat_markers_sec": [],
            "energy_curve": zeros,
        }
    energy = energy_curve(samples)
    onsets = onset_envelope(samples)
    bpm = estimate_bpm(onsets)
    beats, downbeats = beat_grid(onsets, bpm, duration_sec)
    return {
        "duration_sec": duration_sec,
        "bpm": bpm,
        "beat_times_sec": beats,
        "downbeat_times_sec": downbeats,
        "beat_markers_sec": downbeats,
        "energy_curve": energy,
    }
