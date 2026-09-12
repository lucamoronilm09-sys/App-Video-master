"""Agente 5: Render.

Render FFmpeg con fallback segmentato. Valida ogni output e l'export finale,
usa le durate del manifest come fonte di verità e, in caso di errore del render
monolitico, tenta automaticamente il percorso segmentato prima di fallire.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from app.jobs import progress as prog

RENDER_TIMEOUT_SEC = 1800
WINDOWS_CMDLINE_SAFE_LIMIT = 24000


def _read_fraction(progress_file: Path, total_sec: float) -> float | None:
    try: text = progress_file.read_text(errors="ignore")
    except OSError: return None
    mark = text.rfind("out_time_ms=")
    if mark < 0 or total_sec <= 0: return None
    try: micros = float(text[mark + len("out_time_ms="):].split()[0])
    except (ValueError, IndexError): return None
    return min(0.99, micros / 1_000_000 / total_sec)


def _run_ffmpeg(args: list[str], total_sec: float = 0.0, job_id: str | None = None) -> subprocess.CompletedProcess:
    if job_id and total_sec > 0: return _run_ffmpeg_progress(args, total_sec, job_id)
    return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=RENDER_TIMEOUT_SEC)


def _run_ffmpeg_progress(args: list[str], total_sec: float, job_id: str) -> subprocess.CompletedProcess:
    tmpdir = Path(tempfile.gettempdir()); uniq = f"{job_id}_{int(time.time() * 1000)}"; pf = tmpdir / f"render_{uniq}.progress"; ef = tmpdir / f"render_{uniq}.stderr"
    pargs = args[:-1] + ["-progress", str(pf), "-nostats", args[-1]]; start = time.time()
    with open(ef, "w", encoding="utf-8", errors="ignore") as errfh:
        proc = subprocess.Popen(pargs, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errfh)
        while proc.poll() is None:
            if time.time() - start > RENDER_TIMEOUT_SEC:
                proc.kill(); proc.wait(); raise subprocess.TimeoutExpired(pargs, RENDER_TIMEOUT_SEC)
            frac = _read_fraction(pf, total_sec)
            if frac is not None: prog.set(job_id, frac, "rendering ffmpeg")
            time.sleep(0.5)
    try: tail = ef.read_text(encoding="utf-8", errors="ignore")
    finally:
        for f in (pf, ef):
            try: f.unlink(missing_ok=True)
            except OSError: pass
    return subprocess.CompletedProcess(pargs, proc.returncode, "", tail)


def _cmdline_length(args: list[str]) -> int: return len(" ".join(str(x) for x in args))

def _input_paths_from_args(args: list[str]) -> list[str]:
    paths: list[str] = []; i = 0
    while i < len(args) - 1:
        if args[i] == "-i": paths.append(str(args[i + 1])); i += 2
        else: i += 1
    return paths


def _extract_segment_filter(script_path: Path, input_index: int) -> str:
    text = script_path.read_text(encoding="utf-8", errors="ignore")
    lines = [line.strip() for line in text.split(";") if line.strip()]
    labels = {f"pbg{input_index}", f"pfg{input_index}", f"bg{input_index}", f"fg{input_index}", f"vibg{input_index}", f"vifg{input_index}", f"v{input_index}"}
    selected: list[str] = []; label_re = re.compile(r"\[([^\]]+)\]")
    for line in lines:
        if "xfade=" in line or "concat=n=" in line or "format=yuv420p[vout]" in line: continue
        if any(label in labels for label in label_re.findall(line)):
            if re.search(rf"\[{input_index}:v\]", line) or any(f"[{label}]" in line for label in labels): selected.append(line)
    if not selected: raise RuntimeError(f"Impossibile estrarre il filtro della clip {input_index}")
    graph = ";\n".join(selected).replace(f"[{input_index}:v]", "[0:v]").replace(f"[v{input_index}]", "[vout]")
    return graph


def _run_checked(args: list[str], description: str) -> None:
    proc = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=RENDER_TIMEOUT_SEC)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip(); raise RuntimeError(f"{description}: ffmpeg exit={proc.returncode}: {detail}")


def _segment_input_args(kind: str, path: str, fps: int, duration: float = 0.0) -> list[str]:
    if kind == "photo": return ["-loop", "1", "-framerate", str(fps), "-i", path, "-t", str(duration)]
    return ["-i", path]


def _encode_segment(segment: dict[str, Any], input_path: str, script_path: Path, fps: int, vcodec: str, crf: int, out_path: Path) -> None:
    index = int(segment["input_index"]); graph = _extract_segment_filter(script_path, index); duration = float(segment.get("duration_sec", 0.0))
    args = ["ffmpeg", "-y", "-sws_flags", "lanczos+accurate_rnd+full_chroma_int"] + _segment_input_args(str(segment["kind"]), input_path, fps, duration)
    args += ["-filter_complex", graph, "-map", "[vout]", "-c:v", vcodec, "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(fps), "-fps_mode", "cfr", "-video_track_timescale", "90000", "-an", "-t", str(duration), "-movflags", "+faststart", str(out_path)]
    _run_checked(args, f"render segmento {index + 1}")


def _merge_two_video_segments(left: Path, right: Path, duration_left: float, duration_right: float, transition: float, fps: int, vcodec: str, crf: int, out_path: Path) -> float:
    if transition > 0:
        offset = max(0.0, duration_left - transition); graph = f"[0:v][1:v]xfade=transition=fade:duration={transition:.3f}:offset={offset:.3f}[vout]"; new_duration = round(duration_left + duration_right - transition, 3)
    else:
        graph = "[0:v][1:v]concat=n=2:v=1:a=0[vout]"; new_duration = round(duration_left + duration_right, 3)
    args = ["ffmpeg", "-y", "-i", str(left), "-i", str(right), "-filter_complex", graph, "-map", "[vout]", "-c:v", vcodec, "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(fps), "-fps_mode", "cfr", "-video_track_timescale", "90000", "-an", "-t", str(new_duration), "-movflags", "+faststart", str(out_path)]
    _run_checked(args, "unione segmenti"); return new_duration


def _probe_duration(path: Path, fallback: float | None = None) -> float:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=duration", "-of", "csv=p=0", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    values: list[float] = []
    if proc.returncode == 0:
        for token in re.split(r"[\r\n,]+", proc.stdout or ""):
            try: value = float(token.strip())
            except ValueError: continue
            if value > 0: values.append(value)
    if values: return max(values)
    if fallback is not None and fallback > 0: return round(float(fallback), 3)
    detail = (proc.stderr or "").strip()
    if proc.returncode != 0: raise RuntimeError(f"ffprobe fallito su {path}: {detail}")
    raise RuntimeError(f"durata non leggibile per {path}")


def _validate_video(path: Path, expected_duration: float | None = None) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size < 1024: raise RuntimeError(f"output video mancante o vuoto: {path}")
    proc = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height,duration", "-show_entries", "format=duration", "-of", "json", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0: raise RuntimeError(f"ffprobe validazione fallito su {path}: {(proc.stderr or '').strip()}")
    try: data = __import__("json").loads(proc.stdout)
    except Exception as exc: raise RuntimeError(f"metadata video illeggibili: {path}") from exc
    streams = data.get("streams") or []
    if not streams: raise RuntimeError(f"nessuna traccia video nell'output: {path}")
    stream = streams[0]; duration = float(stream.get("duration") or (data.get("format") or {}).get("duration") or 0.0)
    if duration <= 0: raise RuntimeError(f"durata output non valida: {path}")
    if expected_duration and abs(duration - expected_duration) > max(0.35, 3.0 / 30): raise RuntimeError(f"durata output incoerente: {duration:.3f}s attesi {expected_duration:.3f}s")
    return {"codec": stream.get("codec_name"), "width": stream.get("width"), "height": stream.get("height"), "duration": round(duration, 3), "size_bytes": path.stat().st_size}


def _decode_probe(path: Path) -> None:
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "null", "-"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0: raise RuntimeError(f"output non decodificabile: {(proc.stderr or proc.stdout or '').strip()}")


def _render_segmented(manifest: dict[str, Any], job_id: str | None) -> Path:
    output = Path(manifest["output"]["path"]); fps = int(manifest.get("fps", 30)); vcodec = "libx264" if manifest.get("vcodec", "h264") == "h264" else "libx265"; crf = 18 if vcodec == "libx264" else 20
    segments = list(manifest.get("segments") or []); transitions = list(manifest.get("transitions") or []); script_path = Path(manifest.get("filter_complex_script", ""))
    if not segments or not script_path.is_file(): raise RuntimeError("Manifest non sufficiente per il render segmentato")
    input_paths = _input_paths_from_args(list(manifest.get("args") or []))
    if len(input_paths) < len(segments): raise RuntimeError("Numero input FFmpeg insufficiente per il render segmentato")
    work = output.parent / f".render_parts_{job_id or int(time.time())}"; work.mkdir(parents=True, exist_ok=True)
    
    # Logger dedicato per il render segmentato
    render_logger = logging.getLogger(f"pipeline.render.segmented.{job_id or 'unknown'}")
    render_logger.info("Avvio render segmentato in %s", work)
    
    try:
        rendered: list[Path] = []; durations: list[float] = []; total = float(manifest.get("total_sec") or 1.0); completed = 0.0
        for i, segment in enumerate(segments):
            part = work / f"seg_{i:04d}.mp4"; expected = float(segment.get("duration_sec") or 0.0)
            _encode_segment(segment, input_paths[int(segment["input_index"])], script_path, fps, vcodec, crf, part)
            _validate_video(part, expected); rendered.append(part)
            dur = _probe_duration(part, fallback=expected)
            if expected > 0 and abs(dur - expected) > max(0.08, 2.0 / fps): dur = round(expected, 3)
            durations.append(dur); completed += dur
            if job_id: prog.set(job_id, min(0.55, 0.05 + 0.50 * completed / max(total, 0.01)), f"clip {i + 1}/{len(segments)}")
        current = rendered[0]; current_duration = durations[0]
        for i in range(1, len(rendered)):
            merged = work / f"merge_{i:04d}.mp4"; trans = float((transitions[i - 1] if i - 1 < len(transitions) else {}).get("duration_sec", 0.0) or 0.0)
            current_duration = _merge_two_video_segments(current, rendered[i], current_duration, durations[i], trans, fps, vcodec, crf, merged); _validate_video(merged, current_duration); current = merged
            if job_id: prog.set(job_id, min(0.85, 0.55 + 0.30 * i / max(1, len(rendered) - 1)), f"unione clip {i + 1}/{len(rendered)}")
        audio = manifest.get("audio") or {}; tracks = list(audio.get("tracks") or [])
        if tracks:
            audio_mix = work / "audio.m4a"; audio_args = ["ffmpeg", "-y"]; labels: list[str] = []
            for idx, track in enumerate(tracks):
                path = track.get("path")
                if not path: raise RuntimeError("Traccia audio senza path")
                audio_args += ["-i", str(path)]; labels.append(f"[{idx}:a]")
            target_total = float(manifest.get("total_sec") or current_duration)
            if len(labels) == 1:
                graph = f"{labels[0]}aformat=sample_rates=44100:channel_layouts=stereo,aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS,aloop=loop=-1:size=2147483647,atrim=duration={target_total:.3f},afade=t=in:d=0.5,afade=t=out:st={max(0.0, target_total - 1.0):.3f}:d=1[aout]"
            else:
                graph = "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[a];[a]aformat=sample_rates=44100:channel_layouts=stereo,aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS,aloop=loop=-1:size=2147483647,atrim=duration={target_total:.3f},afade=t=in:d=0.5,afade=t=out:st={max(0.0, target_total - 1.0):.3f}:d=1[aout]"
            _run_checked(audio_args + ["-filter_complex", graph, "-map", "[aout]", "-c:a", "aac", "-b:a", "160k", "-t", str(target_total), str(audio_mix)], "preparazione audio")
            temp_output = work / "final.mp4"; mux_args = ["ffmpeg", "-y", "-i", str(current), "-i", str(audio_mix), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", str(target_total), "-movflags", "+faststart", str(temp_output)]
            _run_checked(mux_args, "mux video/audio"); current = temp_output
        else:
            final_noaudio = work / "final.mp4"; shutil.copy2(current, final_noaudio); current = final_noaudio
        _validate_video(current, float(manifest.get("total_sec") or current_duration)); _decode_probe(current)
        output.parent.mkdir(parents=True, exist_ok=True); os.replace(current, output)
        if job_id: prog.set(job_id, 0.99, "render completato")
        render_logger.info("Render segmentato completato con successo: %s", output)
        return output
    except Exception as exc:
        render_logger.error("Render segmentato fallito: %s", exc, exc_info=True)
        raise
    finally:
        # Cleanup directory di lavoro con logging appropriato
        if work.exists():
            try:
                removed_count = sum(1 for _ in work.rglob("*"))
                shutil.rmtree(work)
                render_logger.info("Cleanup directory render %s (%d file rimossi)", work, removed_count)
            except Exception as cleanup_exc:
                render_logger.warning("Errore durante cleanup directory render %s: %s", work, cleanup_exc)


async def run(project_state: dict) -> dict:
    manifest: dict[str, Any] | None = project_state.get("render_manifest")
    if not manifest: return project_state
    args = manifest.get("args")
    if not args: raise RuntimeError("render_manifest senza 'args': rieseguire il Timeline Compiler")
    out_path = Path(manifest.get("output", {}).get("path", ""))
    if not out_path.name: raise RuntimeError("render_manifest senza output.path")
    out_path.parent.mkdir(parents=True, exist_ok=True); total_sec = float(manifest.get("total_sec") or 0.0); job_id = project_state.get("_job_id")
    primary_error: Exception | None = None
    try:
        if os.name == "nt" and _cmdline_length(list(args)) >= WINDOWS_CMDLINE_SAFE_LIMIT:
            await asyncio.to_thread(_render_segmented, manifest, job_id); proc = subprocess.CompletedProcess(list(args), 0, "", "")
        else:
            proc = await asyncio.to_thread(_run_ffmpeg, list(args), total_sec, job_id)
            if proc.returncode != 0 and manifest.get("segments") and manifest.get("filter_complex_script"):
                primary_error = RuntimeError(f"render monolitico exit={proc.returncode}: {(proc.stderr or '').strip()[-1800:]}")
                await asyncio.to_thread(_render_segmented, manifest, job_id); proc = subprocess.CompletedProcess(list(args), 0, "", "")
    except subprocess.TimeoutExpired as exc:
        msg = f"ffmpeg timeout dopo {RENDER_TIMEOUT_SEC}s"; project_state.setdefault("errors", []).append({"stage": "render", "message": msg}); raise RuntimeError(msg) from exc
    except Exception as exc:
        if primary_error is not None: raise RuntimeError(f"Render principale fallito e fallback segmentato fallito: {exc}") from exc
        raise
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip(); msg = f"ffmpeg exit={proc.returncode}: {tail}"; project_state.setdefault("errors", []).append({"stage": "render", "message": msg}); raise RuntimeError(msg)
    try: validation = _validate_video(out_path, total_sec); _decode_probe(out_path)
    except Exception as exc:
        project_state.setdefault("errors", []).append({"stage": "render", "message": str(exc)}); raise
    
    # Aggiorna il manifest con i dati post-render
    manifest["status"] = "done"
    manifest["output"]["size_bytes"] = out_path.stat().st_size
    manifest["output"]["rendered_at"] = time.time()
    manifest["output"]["duration_sec"] = validation["duration"]
    manifest["validation"] = validation
    
    return project_state
