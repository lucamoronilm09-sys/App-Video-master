"""Agente 5: Render (architettura sez. 5).

Esegue il render_manifest invocando FFmpeg con i parametri forniti, SENZA
reinterpretarli o modificarli. Output mp4 H.264 (H.265 solo su richiesta
esplicita, non implementata in M5), risoluzione/fps da output_spec via manifest.
Manifest assente (es. progetto vuoto) -> no-op.
Fallimento -> errore tecnico esatto in errors[] + eccezione (il flusso
downstream si interrompe; la correzione spetta agli agenti a monte).
"""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from app.jobs import progress as prog

# Limite di sicurezza per render impazziti (progetti normali: pochi minuti).
RENDER_TIMEOUT_SEC = 1800


def _read_fraction(progress_file: Path, total_sec: float) -> float | None:
    try:
        text = progress_file.read_text(errors="ignore")
    except OSError:
        return None
    mark = text.rfind("out_time_ms=")
    if mark < 0 or total_sec <= 0:
        return None
    try:
        micros = float(text[mark + len("out_time_ms="):].split()[0])
    except (ValueError, IndexError):
        return None
    return min(0.99, micros / 1_000_000 / total_sec)


def _run_ffmpeg(args: list[str], total_sec: float = 0.0,
                job_id: str | None = None) -> subprocess.CompletedProcess:
    """Esegue ffmpeg. Mai pipe senza drenaggio (hang su Windows): o run() con
    communicate, o stderr su file. Con job_id, progress reale via -progress."""
    if job_id and total_sec > 0:
        return _run_ffmpeg_progress(args, total_sec, job_id)
    return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=RENDER_TIMEOUT_SEC)


def _run_ffmpeg_progress(args: list[str], total_sec: float,
                         job_id: str) -> subprocess.CompletedProcess:
    tmpdir = Path(tempfile.gettempdir())
    uniq = f"{job_id}_{int(time.time() * 1000)}"
    pf = tmpdir / f"render_{uniq}.progress"
    ef = tmpdir / f"render_{uniq}.stderr"
    pargs = args[:-1] + ["-progress", str(pf), "-nostats", args[-1]]
    start = time.time()
    with open(ef, "w", encoding="utf-8", errors="ignore") as errfh:
        proc = subprocess.Popen(pargs, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=errfh)
        while proc.poll() is None:
            if time.time() - start > RENDER_TIMEOUT_SEC:
                proc.kill()
                proc.wait()  # attendi cleanup per evitare zombie
                raise subprocess.TimeoutExpired(pargs, RENDER_TIMEOUT_SEC)
            frac = _read_fraction(pf, total_sec)
            if frac is not None:
                prog.set(job_id, frac, "rendering ffmpeg")
            time.sleep(0.5)
    try:
        # leggi tutto lo stderr (no truncation per non perdere errori critici)
        tail = ef.read_text(encoding="utf-8", errors="ignore")
    finally:
        for f in (pf, ef):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
    return subprocess.CompletedProcess(pargs, proc.returncode, "", tail)


async def run(project_state: dict) -> dict:
    manifest: dict[str, Any] | None = project_state.get("render_manifest")
    if not manifest:
        return project_state  # niente da renderizzare

    args = manifest.get("args")
    if not args:
        raise RuntimeError("render_manifest senza 'args': rieseguire il Timeline Compiler")
    out_path = Path(manifest.get("output", {}).get("path", ""))
    if not out_path.name:
        raise RuntimeError("render_manifest senza output.path")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    total_sec = float(manifest.get("total_sec") or 0.0)
    job_id = project_state.get("_job_id")
    try:
        proc = await asyncio.to_thread(_run_ffmpeg, list(args), total_sec, job_id)
    except subprocess.TimeoutExpired as exc:
        msg = f"ffmpeg timeout dopo {RENDER_TIMEOUT_SEC}s: {' '.join(list(args)[:4])}..."
        project_state.setdefault("errors", []).append({"stage": "render", "message": msg})
        raise RuntimeError(msg) from exc

    if proc.returncode != 0:
        # stderr gia' completo (no truncation in _run_ffmpeg_progress)
        tail = (proc.stderr or "").strip()
        msg = f"ffmpeg exit={proc.returncode}: {tail}"
        project_state.setdefault("errors", []).append({"stage": "render", "message": msg})
        raise RuntimeError(msg)

    if not out_path.is_file() or out_path.stat().st_size == 0:
        msg = f"ffmpeg ok ma output mancante/vuoto: {out_path}"
        project_state.setdefault("errors", []).append({"stage": "render", "message": msg})
        raise RuntimeError(msg)

    manifest["status"] = "done"
    manifest["output"]["size_bytes"] = out_path.stat().st_size
    manifest["output"]["rendered_at"] = time.time()
    return project_state
