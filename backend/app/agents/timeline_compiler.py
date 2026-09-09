"""Agente 4: Timeline Compiler (architettura sez. 5) — puramente tecnico.

Traduce la edit_decision_list in un render_manifest eseguibile (filtergraph
FFmpeg reale + argv pronto): foto via zoompan (Ken Burns), video con trim,
verticali in contain centrato su sfondo blur scurito (mai croppati),
orizzontali in cover, transizioni xfade, traccia audio utente a misura.
Non prende decisioni di stile: valida solo i vincoli (zoom <= 1.15,
pan <= 12%, dissolvenze entro 1.5s, coerenza durate) e solleva ValueError preciso
in caso di EDL incoerente (la correzione spetta agli agenti a monte).
Le scelte manuali dell'utente (clip_overrides, inclusi stacchi a 0.0s) sono
sempre ammesse entro i limiti tecnici: il vincolo "solo crossfade 0.6-1.0s"
vale per ciò che genera il regista, non per l'utente.
Tutti i segmenti e gli offset xfade sono snappati alla griglia dei frame:
istanti non allineati costringono xfade a duplicare frame (scatti visibili
proprio sulle transizioni). EDL vuota -> no-op.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.pipeline import state as state_store

TRANS_MANUAL_MAX_SEC = 1.5  # oltre: solo su scelta esplicita futura, mai dal regista
ZOOM_MAX = 1.15
PAN_MAX_FRAC = 0.12
MANIFEST_VERSION = 2
VCODEC_MAP = {"h264": "libx264", "h265": "libx265"}
# Qualita' foto: lo scaler di default (bicubic) ammorbidisce i dettagli dopo i
# 3 passaggi (upscale 2x -> zoompan -> downscale). Lanczos preserva la nitidezza
# (verificato: +~90% varianza del Laplaciano sul frame centrale a parita' di foto).
SCALE_FLAGS = "flags=lanczos"
# Recupero di micro-dettaglio dopo il downscale finale (solo foto, solo luma:
# i video restano intoccati per non amplificare rumore/compressione sorgente).
UNSHARP_PHOTO = "unsharp=5:5:0.35:5:5:0.0"
# CRF per codec (scale diverse: a parita' di numero, x265 e' piu' conservativo).
# H.264 20 -> 18: le foto ad alta frequenza ne beneficiano molto, il peso resta
# moderato (~+60% su slideshow 1080p, pochi Mbps in assoluto). H.265 resta a 20.
CRF_MAP = {"h264": 18, "h265": 20}
ENCODE_PRESET = "medium"
# Scaler di alta qualita' anche per le conversioni implicite (es. blend xfade).
SWS_FLAGS = "lanczos+accurate_rnd+full_chroma_int"


def _even(x: int) -> int:
    return x if x % 2 == 0 else x + 1


def _quantize_to_frames(sec: float, fps: int) -> float:
    """Snappa i secondi alla griglia dei frame di output."""
    return round(round(sec * fps) / fps, 3)


def _parse_resolution(spec: dict) -> tuple[int, int]:
    try:
        w, h = spec.get("resolution", "1920x1080").split("x")
        return int(w), int(h)
    except Exception as exc:
        raise ValueError(f"output_spec.resolution non valida: {spec.get('resolution')}") from exc


def _validate_ken_burns(kb: dict[str, Any], is_photo: bool) -> None:
    if not is_photo:
        if kb is not None:
            raise ValueError("ken_burns assegnato a un video (vietato: RF9)")
        return
    if not isinstance(kb, dict):
        raise ValueError("ken_burns mancante per una foto")
    for key in ("zoom_from", "zoom_to", "pan_x_from", "pan_x_to", "pan_y_from", "pan_y_to"):
        if key not in kb:
            raise ValueError(f"ken_burns incompleto: manca {key}")
    zf, zt = float(kb["zoom_from"]), float(kb["zoom_to"])
    if not (1.0 <= zf <= ZOOM_MAX and 1.0 <= zt <= ZOOM_MAX):
        raise ValueError(f"zoom fuori vincolo [1.0, {ZOOM_MAX}]: {zf}->{zt}")
    for ax in ("pan_x", "pan_y"):
        f, t = float(kb[f"{ax}_from"]), float(kb[f"{ax}_to"])
        if not (0.0 <= f <= 1.0 and 0.0 <= t <= 1.0):
            raise ValueError(f"{ax} fuori [0, 1]: {f}->{t}")
    shift = (1.0 - 1.0 / max(zf, zt)) * max(
        abs(float(kb["pan_x_to"]) - float(kb["pan_x_from"])),
        abs(float(kb["pan_y_to"]) - float(kb["pan_y_from"])),
    )
    if shift > PAN_MAX_FRAC + 1e-9:
        raise ValueError(f"pan oltre il 12% del frame: {shift:.3f}")


def _ramp(zf: float, zt: float, frames: int) -> str:
    if frames <= 1 or zf == zt:
        return f"{zf}"
    return f"{zf}+({zt}-{zf})*on/{frames - 1}"


def _axis_expr(f: float, t: float, frames: int) -> str:
    if f == 0.5 and t == 0.5:
        return "iw/2-(iw/zoom/2)"
    if f == t:
        return f"(iw-iw/zoom)*{f}"
    span = f"(iw-iw/zoom)*({f}+({t}-{f})*on/{frames - 1})" if frames > 1 else f"(iw-iw/zoom)*{t}"
    return span


def _zoompan(kb: dict[str, Any], frames: int, out_w: int, out_h: int, fps: int) -> str:
    zf, zt = float(kb["zoom_from"]), float(kb["zoom_to"])
    z = _ramp(zf, zt, frames)
    x = _axis_expr(float(kb["pan_x_from"]), float(kb["pan_x_to"]), frames)
    y = _axis_expr(float(kb["pan_y_from"]), float(kb["pan_y_to"]), frames)
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={out_w}x{out_h}:fps={fps}"


def _tail(fps: int) -> str:
    return f"fps={fps},format=yuv420p,setsar=1,settb=AVTB"


async def run(project_state: dict) -> dict:
    edl: list[dict[str, Any]] = project_state.get("edit_decision_list", [])
    if not edl:
        return project_state  # niente da compilare
    state_store.ensure_project_dirs(project_state["project_id"])

    media_by_id = {m["id"]: m for m in project_state.get("media", [])}
    W, H = _parse_resolution(project_state.get("output_spec", {}))
    fps = int(project_state.get("output_spec", {}).get("fps", 30))
    vcodec = project_state.get("output_spec", {}).get("vcodec", "h264")
    if vcodec not in VCODEC_MAP:
        raise ValueError(f"vcodec non supportato: {vcodec} (h264|h265)")
    venc = VCODEC_MAP[vcodec]
    W2, H2 = 2 * W, 2 * H

    # --- validazione EDL ---
    for e in edl:
        mid = e.get("media_id")
        if mid not in media_by_id:
            raise ValueError(f"EDL fa riferimento a media inesistente: {mid}")
        for key in ("start_sec_in_final_video", "duration_sec", "transition_in", "transition_out"):
            if key not in e:
                raise ValueError(f"voce EDL {mid} incompleta: manca {key}")
        if float(e["duration_sec"]) <= 0:
            raise ValueError(f"durata non positiva per {mid}")
        for tk in ("transition_in", "transition_out"):
            t = float(e[tk])
            if t < 0.0 or t > TRANS_MANUAL_MAX_SEC:
                raise ValueError(f"transizione fuori [0.0, {TRANS_MANUAL_MAX_SEC}]s per {mid}: {t}")
        _validate_ken_burns(e.get("ken_burns"), media_by_id[mid].get("type") == "photo")
    if float(edl[0]["transition_in"]) != 0.0 or float(edl[-1]["transition_out"]) != 0.0:
        raise ValueError("prima clip con transition_in o ultima con transition_out (devono essere 0)")
    for a, b in zip(edl, edl[1:]):
        if float(a["transition_out"]) != float(b["transition_in"]):
            raise ValueError(f"transizione incoerente tra {a['media_id']} e {b['media_id']}")
        d = float(a["transition_out"])
        if d >= min(float(a["duration_sec"]), float(b["duration_sec"])) - 0.05:
            raise ValueError(f"crossfade {d}s piu' lungo delle clip adiacenti")

    # --- segmenti ---
    filters: list[str] = []
    inputs: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    seg_durs: list[float] = []

    def _emit(s: str, seg_acc: list[str]) -> None:
        filters.append(s)
        seg_acc.append(s)

    # --- segmenti ---
    filters: list[str] = []
    inputs: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    seg_durs: list[float] = []

    def _emit(s: str, seg_acc: list[str]) -> None:
        filters.append(s)
        seg_acc.append(s)

    # edge case: EDL con 1 sola clip -> nessuna transizione, duration deve essere > 0
    if len(edl) == 1:
        e = edl[0]
        m = media_by_id[e["media_id"]]
        path = m["path"]
        if not Path(path).is_file():
            raise ValueError(f"file media mancante su disco: {path}")
        # warning se solo video senza audio utente
        audio_path_check = (project_state.get("audio") or {}).get("path")
        if m["type"] == "video" and not audio_path_check:
            project_state.setdefault("warnings", []).append(
                {"stage": "compile", "message": f"singola clip video {m['id']} senza traccia audio: sara' muta"}
            )

    for i, e in enumerate(edl):
        m = media_by_id[e["media_id"]]
        path = m["path"]
        if not Path(path).is_file():
            raise ValueError(f"file media mancante su disco: {path}")
        kind = m["type"]
        D = float(e["duration_sec"])
        orient = m.get("orientation") or ("portrait" if m.get("height", 0) > m.get("width", 0) else "landscape")
        portrait = orient == "portrait"
        inputs.append({"index": i, "path": path, "kind": kind})
        seg_acc: list[str] = []

        if kind == "photo":
            frames = max(2, round(D * fps))
            seg_durs.append(round(frames / fps, 3))
            if portrait:
                # fg in supersampling 2x per un Ken Burns fluido, poi ridotto
                # a H prima dell'overlay: senza il downscale il livello 2x
                # veniva mostrato ritagliato (crop dei verticali) invece che
                # in contain. Dimensioni sempre pari (yuv420).
                fw = _even(round(H2 * m["width"] / m["height"]))
                fw1 = _even(round(H * m["width"] / m["height"]))
                _emit(f"[{i}:v]split=2[ibg{i}][ifg{i}]", seg_acc)
                _emit(
                    f"[ibg{i}]scale={W}:{H}:force_original_aspect_ratio=increase:{SCALE_FLAGS},"
                    f"crop={W}:{H},gblur=sigma=40,eq=brightness=-0.25,setsar=1,"
                    f"loop=loop=-1:size=1,trim=end_frame={frames},"
                    # il loop eredita i timestamp del demuxer (25fps): rigenerali
                    # esatti a fps costanti, altrimenti l'overlay si allunga
                    f"setpts=N/{fps}/TB,fps={fps}[vbg{i}]",
                    seg_acc,
                )
                _emit(
                    f"[ifg{i}]scale={fw}:{H2}:{SCALE_FLAGS},{_zoompan(e['ken_burns'], frames, fw, H2, fps)},"
                    f"scale={fw1}:{H}:{SCALE_FLAGS},{UNSHARP_PHOTO},setpts=PTS-STARTPTS[vfg{i}]",
                    seg_acc,
                )
                _emit(
                    f"[vbg{i}][vfg{i}]overlay=(W-w)/2:(H-h)/2:format=yuv420:eof_action=pass,"
                    f"{_tail(fps)}[v{i}]",
                    seg_acc,
                )
            else:
                # setpts=PTS-STARTPTS: lo zoompan su still emette timestamp che
                # partono gia' da 0, ma il reset esplicito evita che il filtro
                # fps a valle duplichi/salti un frame per deriva di arrotondamento
                # (micro-scatto a inizio/fine foto). Stessa ragione del ramo portrait.
                _emit(
                    f"[{i}:v]scale={W2}:{H2}:force_original_aspect_ratio=increase:{SCALE_FLAGS},"
                    f"crop={W2}:{H2},{_zoompan(e['ken_burns'], frames, W2, H2, fps)},"
                    f"scale={W}:{H}:{SCALE_FLAGS},{UNSHARP_PHOTO},setpts=PTS-STARTPTS,{_tail(fps)}[v{i}]",
                    seg_acc,
                )
        else:  # video: trim (se previsto), cover/contain, MAI zoompan
            ts, te = m.get("trim_start_sec"), m.get("trim_end_sec")
            if ts is not None and te is not None:
                if abs((float(te) - float(ts)) - D) > 0.05:
                    raise ValueError(f"durata EDL incoerente col trim per {m['id']}")
                trim = f"trim=start={float(ts)}:end={float(te)},setpts=PTS-STARTPTS,"
            else:
                trim = ""
            # Frame-exact: la conversione fps (es. 25->30) può produrre un frame
            # in più o in meno rispetto a D; il clamp fissa esattamente N frame
            # così gli offset xfade cadono sulla griglia (niente scatti).
            frames_v = max(1, round(D * fps))
            seg_durs.append(round(frames_v / fps, 3))
            exact = f"fps={fps},trim=end_frame={frames_v},setpts=PTS-STARTPTS"
            if portrait:
                _emit(f"[{i}:v]{trim}split=2[vibg{i}][vifg{i}]", seg_acc)
                _emit(
                    f"[vibg{i}]scale={W}:{H}:force_original_aspect_ratio=increase:{SCALE_FLAGS},"
                    f"crop={W}:{H},gblur=sigma=40,eq=brightness=-0.25,fps={fps}[vbg{i}]",
                    seg_acc,
                )
                _emit(f"[vifg{i}]scale=-2:{H}:{SCALE_FLAGS},{exact}[vfg{i}]", seg_acc)
                _emit(
                    f"[vbg{i}][vfg{i}]overlay=(W-w)/2:(H-h)/2:format=yuv420:eof_action=pass,"
                    f"{_tail(fps)}[v{i}]",
                    seg_acc,
                )
            else:
                _emit(
                    f"[{i}:v]{trim}scale={W}:{H}:force_original_aspect_ratio=increase:{SCALE_FLAGS},"
                    f"crop={W}:{H},{exact},{_tail(fps)}[v{i}]",
                    seg_acc,
                )
        segments.append({"media_id": e["media_id"], "input_index": i, "kind": kind,
                         "fit": "contain" if portrait else "cover",
                         "filter": " | ".join(seg_acc),
                         "label": f"v{i}", "duration_sec": round(seg_durs[-1], 3)})

    # --- transizioni xfade (snappate ai frame; 0.0s = stacco voluto dall'utente) ---
    transitions: list[dict[str, Any]] = []
    prev_label = "v0"
    acc = seg_durs[0]
    trans_sum = 0.0
    for k in range(1, len(edl)):
        d = _quantize_to_frames(float(edl[k]["transition_in"]), fps)
        if d <= 0.0:
            # stacco secco: niente xfade, i segmenti si susseguono via concat
            # (un ramo scollegato farebbe fallire il filtergraph)
            filters.append(f"[{prev_label}][v{k}]concat=n=2:v=1:a=0[c{k}]")
            transitions.append({"index": k, "from_segment": k - 1, "to_segment": k,
                                "duration_sec": 0.0, "offset_sec": round(acc - trans_sum, 3),
                                "cut": True})
            prev_label = f"c{k}"
            acc += seg_durs[k]
            continue
        offset = _quantize_to_frames(acc - d - trans_sum, fps)
        filters.append(
            f"[{prev_label}][v{k}]xfade=transition=fade:duration={d}:offset={offset}[x{k}]"
        )
        transitions.append({"index": k, "from_segment": k - 1, "to_segment": k,
                            "duration_sec": d, "offset_sec": offset, "cut": False})
        prev_label = f"x{k}"
        acc += seg_durs[k]
        trans_sum += d
    total = round(acc - trans_sum, 3)
    # edge case: durata totale <= 0 (transizioni troppo grandi o durate nulle)
    if total <= 0:
        raise ValueError(f"durata totale del video <= 0s: verificare durate clip e transizioni")
    filters.append(f"[{prev_label}]format=yuv420p[vout]")

    # coerenza col totale creativo (± mezzo frame di quantizzazione per clip)
    creative = round(sum(float(e["duration_sec"]) for e in edl) - sum(float(e["transition_out"]) for e in edl[:-1]), 3)
    if abs(total - creative) > len(edl) * (0.5 / fps) + 0.02:
        raise ValueError(f"totale manifest ({total}s) incoerente con EDL ({creative}s)")

    # --- playlist audio: più tracce in sequenza; se termina prima del video,
    # la playlist viene ripetuta per evitare silenzio ---
    tracks = list(project_state.get("audio_tracks") or [])
    if not tracks:
        legacy = (project_state.get("audio") or {}).get("path")
        if legacy:
            tracks = [project_state.get("audio") or {}]
    audio_block = None
    if tracks:
        audio_labels = []
        for ti, track in enumerate(tracks):
            audio_path = track.get("path")
            if not audio_path:
                continue
            if not Path(audio_path).is_file():
                raise ValueError(f"file audio mancante su disco: {audio_path}")
            a_idx = len(inputs)
            inputs.append({"index": a_idx, "path": audio_path, "kind": "audio", "audio_track": ti})
            lab = f"aud{ti}"
            filters.append(
                f"[{a_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
                f"aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS[{lab}]"
            )
            audio_labels.append(f"[{lab}]")
        if not audio_labels:
            raise ValueError("audio_tracks presenti ma nessun file audio valido")
        if len(audio_labels) == 1:
            playlist = audio_labels[0]
        else:
            playlist = "".join(audio_labels) + f"concat=n={len(audio_labels)}:v=0:a=1[a_playlist];"
            filters.append(playlist)
            playlist = "[a_playlist]"
        # Loop della playlist per coprire tutta la durata del video.
        looped = "[a_loop]"
        filters.append(
            f"{playlist}aloop=loop=-1:size=2147483647,atrim=duration={total},"
            f"afade=t=in:d=0.5,afade=t=out:st={round(max(0.0, total - 1.0), 3)}:d=1{looped}"
        )
        audio_block = {"tracks": [{"path": t.get("path"), "name": t.get("name"), "duration_sec": t.get("duration_sec", 0)} for t in tracks]}
    else:
        # edge case: tutti video senza audio utente -> warning (sara' muto)
        all_videos = all(media_by_id[e["media_id"]]["type"] == "video" for e in edl)
        if all_videos:
            project_state.setdefault("warnings", []).append(
                {"stage": "compile", "message": "tutti video senza audio utente: il video sara' muto"}
            )
        # edge case: tutte foto senza audio -> warning (sara' muto)
        all_photos = all(media_by_id[e["media_id"]]["type"] == "photo" for e in edl)
        if all_photos:
            project_state.setdefault("warnings", []).append(
                {"stage": "compile", "message": "tutte foto senza audio utente: il video sara' muto"}
            )

    script = ";\n".join(filters)
    out_path = str(state_store.output_dir(project_state["project_id"]) / "final.mp4")
    crf = CRF_MAP[vcodec]
    args: list[str] = ["ffmpeg", "-y", "-sws_flags", SWS_FLAGS]
    for inp in inputs:
        args += ["-i", inp["path"]]
    args += ["-filter_complex", script, "-map", "[vout]"]
    if audio_block:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"]
    # Metadati colore BT.709 espliciti: le foto JPEG sono full-range e lo scaler
    # deve mappare su gamma/livelli HD coerenti, altrimenti i colori risultano
    # slavati rispetto all'originale.
    args += ["-c:v", venc, "-preset", ENCODE_PRESET, "-crf", str(crf),
             "-pix_fmt", "yuv420p",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
             "-color_range", "tv",
             "-r", str(fps), "-movflags", "+faststart", out_path]

    project_state["render_manifest"] = {
        "version": MANIFEST_VERSION,
        "output": {"path": out_path, "resolution": f"{W}x{H}", "fps": fps,
                   "vcodec": vcodec,
                   "preset": ENCODE_PRESET, "crf": crf,
                   "audio_codec": "aac" if audio_block else None},
        "inputs": inputs,
        "segments": segments,
        "transitions": transitions,
        "filter_complex": script,
        "args": args,
        "total_sec": total,
        "audio": audio_block,
    }
    return project_state
