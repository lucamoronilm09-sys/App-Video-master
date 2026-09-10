"""Agente 4: Timeline Compiler.

Compila l'edit_decision_list in un manifest FFmpeg realmente eseguibile.
I video non portano mai l'audio originale: l'unico audio del render è quello
aggiunto esplicitamente come traccia musicale del progetto.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.pipeline import state as state_store

TRANS_MANUAL_MAX_SEC = 1.5
ZOOM_MAX = 1.15
PAN_MAX_FRAC = 0.12
MANIFEST_VERSION = 6
VCODEC_MAP = {"h264": "libx264", "h265": "libx265"}
CRF_MAP = {"h264": 18, "h265": 20}
ENCODE_PRESET = "medium"
SWS_FLAGS = "lanczos+accurate_rnd+full_chroma_int"
PHOTO_UNSHARP = "unsharp=5:5:0.35:5:5:0.0"


def _even(value: int) -> int: return value if value % 2 == 0 else value + 1

def _quantize(sec: float, fps: int) -> float: return round(round(sec * fps) / fps, 3)

def _resolution(spec: dict[str, Any]) -> tuple[int, int]:
    try:
        w, h = str(spec.get("resolution", "1920x1080")).split("x", 1); w, h = int(w), int(h)
        if w <= 0 or h <= 0: raise ValueError
        return w, h
    except Exception as exc: raise ValueError(f"output_spec.resolution non valida: {spec.get('resolution')}") from exc


def _validate_kb(kb: Any, is_photo: bool) -> None:
    if not is_photo:
        if kb is not None: raise ValueError("ken_burns assegnato a un video (vietato: RF9)")
        return
    if not isinstance(kb, dict): raise ValueError("ken_burns mancante per una foto")
    required = ("zoom_from", "zoom_to", "pan_x_from", "pan_x_to", "pan_y_from", "pan_y_to")
    if any(k not in kb for k in required): raise ValueError(f"ken_burns incompleto: manca {next(k for k in required if k not in kb)}")
    zf, zt = float(kb["zoom_from"]), float(kb["zoom_to"])
    if not (1.0 <= zf <= ZOOM_MAX and 1.0 <= zt <= ZOOM_MAX): raise ValueError(f"zoom fuori vincolo [1.0, {ZOOM_MAX}]: {zf}->{zt}")
    for axis in ("pan_x", "pan_y"):
        a, b = float(kb[f"{axis}_from"]), float(kb[f"{axis}_to"])
        if not (0.0 <= a <= 1.0 and 0.0 <= b <= 1.0): raise ValueError(f"{axis} fuori [0, 1]: {a}->{b}")
    shift = (1.0 - 1.0 / max(zf, zt)) * max(abs(float(kb["pan_x_to"]) - float(kb["pan_x_from"])), abs(float(kb["pan_y_to"]) - float(kb["pan_y_from"])))
    if shift > PAN_MAX_FRAC + 1e-9: raise ValueError(f"pan oltre il 12% del frame: {shift:.3f}")


def _zoompan(kb: dict[str, Any], frames: int, w: int, h: int, fps: int) -> str:
    zf, zt = float(kb["zoom_from"]), float(kb["zoom_to"]); z = f"{zf}" if frames <= 1 or zf == zt else f"{zf}+({zt}-{zf})*on/{frames - 1}"
    def axis(name: str) -> str:
        a, b = float(kb[f"{name}_from"]), float(kb[f"{name}_to"])
        if a == b: return f"(iw-iw/zoom)*{a}"
        if frames <= 1: return f"(iw-iw/zoom)*{b}"
        return f"(iw-iw/zoom)*({a}+({b}-{a})*on/{frames - 1})"
    return f"zoompan=z='{z}':x='{axis('pan_x')}':y='{axis('pan_y')}':d={frames}:s={w}x{h}:fps={fps}"

def _tail(fps: int) -> str: return f"fps={fps},format=yuv420p,setsar=1,settb=AVTB"


async def run(project_state: dict) -> dict:
    edl = list(project_state.get("edit_decision_list") or [])
    if not edl: project_state["render_manifest"] = None; project_state["edl"] = None; return project_state
    state_store.ensure_project_dirs(project_state["project_id"]); media_by_id = {m["id"]: m for m in project_state.get("media", [])}; spec = project_state.get("output_spec") or {}
    w, h = _resolution(spec); fps = int(spec.get("fps", 30)); vcodec = spec.get("vcodec", "h264")
    if vcodec not in VCODEC_MAP: raise ValueError(f"vcodec non supportato: {vcodec} (h264|h265)")
    for entry in edl:
        mid = entry.get("media_id")
        if mid not in media_by_id: raise ValueError(f"EDL fa riferimento a media inesistente: {mid}")
        for key in ("start_sec_in_final_video", "duration_sec", "transition_in", "transition_out"):
            if key not in entry: raise ValueError(f"voce EDL {mid} incompleta: manca {key}")
        if float(entry["duration_sec"]) <= 0: raise ValueError(f"durata non positiva per {mid}")
        for key in ("transition_in", "transition_out"):
            t = float(entry[key])
            if not 0.0 <= t <= TRANS_MANUAL_MAX_SEC: raise ValueError(f"transizione fuori [0.0, {TRANS_MANUAL_MAX_SEC}]s per {mid}: {t}")
        _validate_kb(entry.get("ken_burns"), media_by_id[mid].get("type") == "photo")
    if float(edl[0]["transition_in"]) != 0.0 or float(edl[-1]["transition_out"]) != 0.0: raise ValueError("prima clip con transition_in o ultima con transition_out (devono essere 0)")
    for a, b in zip(edl, edl[1:]):
        if abs(float(a["transition_out"]) - float(b["transition_in"])) > 1e-6: raise ValueError(f"transizione incoerente tra {a['media_id']} e {b['media_id']}")
        d = float(b["transition_in"])
        if d >= min(float(a["duration_sec"]), float(b["duration_sec"])) - 0.05 and d > 0: raise ValueError(f"crossfade {d}s piu' lungo delle clip adiacenti")

    inputs: list[dict[str, Any]] = []; filters: list[str] = []; segments: list[dict[str, Any]] = []; durations: list[float] = []
    for i, entry in enumerate(edl):
        media = media_by_id[entry["media_id"]]; path = Path(media["path"])
        if not path.is_file(): raise ValueError(f"file media mancante su disco: {path}")
        kind = media.get("type")
        if kind not in ("photo", "video"): raise ValueError(f"tipo media non supportato: {kind}")
        duration = float(entry["duration_sec"]); frames = max(1, round(duration * fps)); actual_duration = round(frames / fps, 3); durations.append(actual_duration)
        # Nessun mapping audio: l'audio originale dei video è sempre escluso.
        inputs.append({"index": i, "path": str(path), "kind": kind})
        if kind == "photo":
            m_w = max(1, int(media.get("width") or w)); m_h = max(1, int(media.get("height") or h)); portrait = (media.get("orientation") == "portrait") or m_h > m_w
            if portrait:
                fw2 = _even(round(2 * h * m_w / m_h)); fw1 = _even(round(h * m_w / m_h))
                filters.append(f"[{i}:v]trim=end_frame=1,setpts=PTS-STARTPTS,split=2[pbg{i}][pfg{i}]")
                filters.append(f"[pbg{i}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=40,eq=brightness=-0.25,tpad=start_mode=clone:start_duration={duration},setpts=N/{fps}/TB,fps={fps}[bg{i}]")
                filters.append(f"[pfg{i}]scale={fw2}:{2*h},{_zoompan(entry['ken_burns'], frames, fw2, 2*h, fps)},scale={fw1}:{h},{PHOTO_UNSHARP},setpts=PTS-STARTPTS[fg{i}]")
                filters.append(f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,{_tail(fps)}[v{i}]"); fit = "contain"
            else:
                filters.append(f"[{i}:v]trim=end_frame=1,setpts=PTS-STARTPTS,scale={2*w}:{2*h}:force_original_aspect_ratio=increase,crop={2*w}:{2*h},{_zoompan(entry['ken_burns'], frames, 2*w, 2*h, fps)},scale={w}:{h},{PHOTO_UNSHARP},tpad=start_mode=clone:start_duration={duration},setpts=PTS-STARTPTS,{_tail(fps)}[v{i}]"); fit = "cover"
            segments.append({"media_id": entry["media_id"], "input_index": i, "kind": kind, "fit": fit, "label": f"v{i}", "filter": filters[-1], "duration_sec": actual_duration})
        else:
            ts, te = media.get("trim_start_sec"), media.get("trim_end_sec"); trim = f"trim=start={float(ts)}:end={float(te)},setpts=PTS-STARTPTS," if ts is not None and te is not None else ""
            portrait = (media.get("orientation") == "portrait") or int(media.get("height") or 0) > int(media.get("width") or 0); exact = f"fps={fps},trim=end_frame={frames},setpts=PTS-STARTPTS"
            if portrait:
                filters.append(f"[{i}:v]{trim}split=2[vibg{i}][vifg{i}]"); filters.append(f"[vibg{i}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=40,eq=brightness=-0.25,fps={fps}[bg{i}]"); filters.append(f"[vifg{i}]scale=-2:{h},{exact}[fg{i}]"); filters.append(f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,{_tail(fps)}[v{i}]"); fit = "contain"
            else:
                filters.append(f"[{i}:v]{trim}scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},{exact},{_tail(fps)}[v{i}]"); fit = "cover"
            segments.append({"media_id": entry["media_id"], "input_index": i, "kind": kind, "fit": fit, "label": f"v{i}", "filter": filters[-1], "duration_sec": actual_duration})

    transitions: list[dict[str, Any]] = []; current = "v0"; acc = durations[0]
    for i in range(1, len(edl)):
        d = _quantize(float(edl[i]["transition_in"]), fps)
        if d <= 0:
            out = f"cut{i}"; filters.append(f"[{current}][v{i}]concat=n=2:v=1:a=0[{out}]"); transitions.append({"index": i, "from_segment": i-1, "to_segment": i, "duration_sec": 0.0, "offset_sec": round(acc, 3), "cut": True}); current = out; acc += durations[i]
        else:
            offset = _quantize(acc - d, fps); out = f"xf{i}"; filters.append(f"[{current}][v{i}]xfade=transition=fade:duration={d}:offset={offset}[{out}]"); transitions.append({"index": i, "from_segment": i-1, "to_segment": i, "duration_sec": d, "offset_sec": offset, "cut": False}); current = out; acc = round(acc + durations[i] - d, 3)
    total = round(acc, 3); filters.append(f"[{current}]format=yuv420p[vout]")
    creative = round(sum(durations) - sum(float(e["transition_in"]) for e in edl[1:]), 3)
    if abs(total - creative) > max(0.05, len(edl) * 0.05): raise ValueError(f"totale manifest ({total}s) incoerente con EDL ({creative}s)")

    tracks = list(project_state.get("audio_tracks") or [])
    if not tracks:
        legacy = project_state.get("audio") or {}
        if legacy.get("path"): tracks = [legacy]
    audio_block = None
    if tracks:
        labels: list[str] = []
        for ti, track in enumerate(tracks):
            audio_path = track.get("path")
            if not audio_path or not Path(audio_path).is_file(): raise ValueError(f"file audio mancante su disco: {audio_path}")
            idx = len(inputs); inputs.append({"index": idx, "path": str(audio_path), "kind": "audio", "audio_track": ti}); lab = f"aud{ti}"
            filters.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS[{lab}]"); labels.append(f"[{lab}]")
        if len(labels) == 1: source = labels[0]
        else: filters.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[playlist]"); source = "[playlist]"
        fade_out_start = max(0.0, total - 1.0); filters.append(f"{source}aloop=loop=-1:size=2147483647,atrim=duration={total},asetpts=PTS-STARTPTS,afade=t=in:d=0.5,afade=t=out:st={fade_out_start:.3f}:d=1[aout]")
        audio_block = {"tracks": [{"path": t.get("path"), "name": t.get("name"), "duration_sec": t.get("duration_sec", 0)} for t in tracks]}

    script = ";\n".join(filters); script_path = state_store.output_dir(project_state["project_id"]) / "filter_complex.txt"; script_path.write_text(script, encoding="utf-8")
    out_path = str(state_store.output_dir(project_state["project_id"]) / "final.mp4"); args: list[str] = ["ffmpeg", "-y", "-sws_flags", SWS_FLAGS]
    for inp in inputs:
        if inp["kind"] == "audio": args += ["-i", inp["path"]]
        elif inp["kind"] == "photo": args += ["-i", inp["path"], "-t", str(durations[inp["index"]])]
        else: args += ["-i", inp["path"]]
    args += ["-filter_complex", script, "-map", "[vout]"]
    if audio_block: args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"]
    else: args += ["-an"]
    args += ["-c:v", VCODEC_MAP[vcodec], "-preset", ENCODE_PRESET, "-crf", str(CRF_MAP[vcodec]), "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", "-r", str(fps), "-movflags", "+faststart", out_path]
    project_state["render_manifest"] = {"version": MANIFEST_VERSION, "args": args, "output": {"path": out_path, "size_bytes": 0}, "total_sec": total, "fps": fps, "resolution": f"{w}x{h}", "vcodec": vcodec, "segments": segments, "transitions": transitions, "audio": audio_block, "filter_complex_script": str(script_path), "status": "ready", "source_video_audio": "muted"}
    project_state["edl"] = edl
    return project_state
