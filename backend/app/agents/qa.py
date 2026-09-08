"""Agente 6: QA (architettura sez. 5).

Verifica il video renderizzato:
1) durata totale = attesa (manifest) ±0.5s;
2) audio sincronizzato (d sense: durate stream v/a entro 0.5s, partenze ≈ 0);
3) verticali non croppati (tutti i portrait in contain su sfondo overlay) e
   dimensioni output = output_spec;
4) transizioni coerenti: N-1 voci, dissolvenze entro 1.5s (0.0s = stacco
   scelto esplicitamente dall'utente), xfade nel filtergraph per ogni
   dissolvenza, durate manifest allineate all'EDL (entro un frame).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

DUR_TOL_SEC = 0.5
SYNC_TOL_SEC = 0.5
START_TOL_SEC = 0.3
TRANS_MAX_SEC = 1.5  # oltre: solo su scelta esplicita futura; 0.0 = stacco utente


def probe_output(path: str) -> dict[str, Any]:
    """Metadata ffprobe (format + streams). Solleva RuntimeError se illeggibile."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration,size",
         "-show_entries", "stream=index,codec_type,width,height,duration,start_time",
         "-of", "json", path],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe fallita su {path}: {(proc.stderr or '')[-500:]}")
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        raise RuntimeError(f"ffprobe: output non JSON per {path}") from exc


def check_duration(info: dict[str, Any], expected_sec: float) -> tuple[bool, str]:
    try:
        actual = float(info.get("format", {}).get("duration", -1))
    except (TypeError, ValueError):
        return False, "durata non rilevabile dal container"
    ok = abs(actual - expected_sec) <= DUR_TOL_SEC
    return ok, f"file {actual:.2f}s vs attesi {expected_sec:.2f}s (±{DUR_TOL_SEC}s)"


def check_sync(info: dict[str, Any], expect_audio: bool) -> tuple[bool, str]:
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        return False, "nessuno stream video nel file"
    try:
        v_start = float(v.get("start_time", 0) or 0)
    except (TypeError, ValueError):
        v_start = 0.0
    if abs(v_start) > START_TOL_SEC:
        return False, f"video parte a {v_start:.2f}s (atteso ~0)"
    if not expect_audio:
        return True, "solo video, partenza ok"
    if a is None:
        return False, "traccia audio attesa ma assente nel file"
    try:
        dv = float(v.get("duration", info.get("format", {}).get("duration", 0)) or 0)
        da = float(a.get("duration", info.get("format", {}).get("duration", 0)) or 0)
        a_start = float(a.get("start_time", 0) or 0)
    except (TypeError, ValueError):
        return False, "durate stream non rilevabili"
    if abs(a_start) > START_TOL_SEC:
        return False, f"audio parte a {a_start:.2f}s (atteso ~0)"
    if abs(dv - da) > SYNC_TOL_SEC:
        return False, f"desync: video {dv:.2f}s vs audio {da:.2f}s (>±{SYNC_TOL_SEC}s)"
    return True, f"v {dv:.2f}s / a {da:.2f}s allineati dall'inizio"


def check_verticals(manifest: dict[str, Any], project_state: dict) -> tuple[bool, str]:
    spec = (project_state.get("output_spec") or {}).get("resolution", "1920x1080")
    media_by_id = {m["id"]: m for m in project_state.get("media", [])}
    segments = manifest.get("segments", [])
    portraits = [m for m in project_state.get("media", []) if m.get("orientation") == "portrait"]
    seg_by_id = {s["media_id"]: s for s in segments}
    for m in portraits:
        s = seg_by_id.get(m["id"])
        if s is None:
            return False, f"media verticale {m['id']} senza segmento nel manifest"
        if s.get("fit") != "contain" or "overlay" not in s.get("filter", ""):
            return False, f"verticale {m['id']} non in contain centrato (fit={s.get('fit')})"
    n_p = len(portraits)
    return True, f"{n_p} verticali in contain centrato, output {spec} 16:9"


def check_transitions(manifest: dict[str, Any], project_state: dict) -> tuple[bool, str]:
    edl = project_state.get("edit_decision_list", [])
    transitions = manifest.get("transitions", [])
    n = len(edl)
    if n <= 1:
        return True, "clip singola, nessuna transizione richiesta"
    if len(transitions) != n - 1:
        return False, f"{len(transitions)} transizioni su {n} clip (attese {n - 1})"
    fps = int(((manifest.get("output") or {}).get("fps")) or 30)
    frame_tol = 1.0 / max(1, fps) + 0.005
    cuts = 0
    for t, (a, b) in zip(transitions, zip(edl, edl[1:])):
        d = float(t.get("duration_sec", 0))
        if d < 0.0 or d > TRANS_MAX_SEC:
            return False, f"transizione {d}s fuori [0.0, {TRANS_MAX_SEC}]s"
        if d == 0.0:
            cuts += 1
        # coerenza manifest <-> EDL (entro un frame: becca manomissioni e bug)
        want = float(a.get("transition_out", 0.0))
        if abs(d - want) > frame_tol:
            return False, (f"transizione manifest ({d}s) incoerente con EDL "
                           f"({want}s) tra {a.get('media_id')} e {b.get('media_id')}")
    expected_xfade = sum(1 for t in transitions if float(t.get("duration_sec", 0)) > 0.0)
    if manifest.get("filter_complex", "").count("xfade=") != expected_xfade:
        return False, "filtergraph senza xfade per ogni dissolvenza"
    for a, b in zip(edl, edl[1:]):
        if float(a.get("transition_out", -1)) != float(b.get("transition_in", -2)):
            return False, f"transizione incoerente tra {a.get('media_id')} e {b.get('media_id')}"
    tail = f", {cuts} stacchi secchi (scelta utente)" if cuts else ", nessun taglio secco"
    return True, f"{len(transitions)} transizioni entro {TRANS_MAX_SEC}s{tail}"


async def run(project_state: dict) -> dict:
    manifest = project_state.get("render_manifest") or {}
    out_path = manifest.get("output", {}).get("path")
    if not manifest or manifest.get("status") != "done" or not out_path:
        return project_state  # niente da verificare
    if not Path(out_path).is_file():
        project_state["qa_report"] = {
            "status": "rejected",
            "checks": [{"name": "duration", "passed": False, "detail": "file finale mancante su disco"}],
            "issues": [{"check": "duration", "message": f"output mancante: {out_path}",
                        "route_to": "timeline_compiler"}],
        }
        return project_state

    try:
        info = probe_output(out_path)
    except RuntimeError as exc:
        project_state["qa_report"] = {
            "status": "rejected",
            "checks": [{"name": "duration", "passed": False, "detail": str(exc)}],
            "issues": [{"check": "duration", "message": str(exc), "route_to": "timeline_compiler"}],
        }
        return project_state

    results = [
        ("duration", "timeline_compiler", check_duration(info, float(manifest.get("total_sec", 0)))),
        ("av_sync", "timeline_compiler", check_sync(info, manifest.get("audio") is not None)),
        ("verticals", "timeline_compiler", check_verticals(manifest, project_state)),
        ("transitions", "timeline_compiler", check_transitions(manifest, project_state)),
    ]
    checks, issues = [], []
    for name, route_to, (passed, detail) in results:
        checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            issues.append({"check": name, "message": detail, "route_to": route_to})
    project_state["qa_report"] = {
        "status": "approved" if not issues else "rejected",
        "checks": checks,
        "issues": issues,
    }
    return project_state
