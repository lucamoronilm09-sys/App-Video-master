"""Test M4: Edit Director + Timeline Compiler + smoke render ffmpeg reale."""
import copy
import io
import json
import subprocess
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.pipeline import state as state_store
from app.agents import edit_director, timeline_compiler


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def _photo(mid, order, dur=4.0, portrait=False):
    return {"id": mid, "source": "local", "drive_file_id": None, "path": f"/tmp/{mid}.jpg",
            "type": "photo", "orientation": "portrait" if portrait else "landscape",
            "width": 1080 if portrait else 1920, "height": 1920 if portrait else 1080,
            "duration_sec": dur, "order_index": order,
            "fit_mode": "contain" if portrait else "cover",
            "background_fill": "blur" if portrait else None,
            "trim_start_sec": None, "trim_end_sec": None}


def _video(mid, order, dur=10.0):
    return {"id": mid, "source": "local", "drive_file_id": None, "path": f"/tmp/{mid}.mp4",
            "type": "video", "orientation": "landscape", "width": 1920, "height": 1080,
            "duration_sec": dur, "order_index": order, "fit_mode": "cover",
            "background_fill": None,
            "trim_start_sec": 1.0 if dur > 8 else None,
            "trim_end_sec": 9.0 if dur > 8 else None}


def _state(media, audio_dur=0.0, markers=()):
    st = state_store.new_project_state()
    st["media"] = media
    st["audio"] = {"path": None, "duration_sec": audio_dur, "bpm": 120.0,
                   "beat_markers_sec": list(markers), "energy_curve": []}
    return st


# --- Edit Director ---

@pytest.mark.asyncio
async def test_director_edl_structure():
    media = [_photo("p1", 0), _photo("p2", 1, portrait=True), _video("v1", 2), _photo("p3", 3)]
    markers = [float(x) for x in range(0, 30, 2)]
    out = await edit_director.run(_state(media, audio_dur=0.0, markers=markers))
    edl = out["edit_decision_list"]
    assert len(edl) == 4
    assert [e["media_id"] for e in edl] == ["p1", "p2", "v1", "p3"]
    # starts cumulativi con overlap crossfade
    for prev, cur in zip(edl, edl[1:]):
        assert cur["start_sec_in_final_video"] == pytest.approx(
            prev["start_sec_in_final_video"] + prev["duration_sec"] - prev["transition_out"], abs=0.02)
        assert cur["transition_in"] == prev["transition_out"]
        assert 0.6 <= prev["transition_out"] <= 1.0
    assert edl[0]["transition_in"] == 0.0 and edl[-1]["transition_out"] == 0.0
    # ken burns solo foto, mai consecutivi uguali, entro vincoli
    kbs = [e["ken_burns"] for e in edl]
    assert kbs[2] is None and all(k is not None for k in (kbs[0], kbs[1], kbs[3]))
    moves = [k["movement"] for k in kbs if k]
    assert all(a != b for a, b in zip(moves, moves[1:]))
    for k in (k for k in kbs if k):
        assert 1.0 <= k["zoom_from"] <= 1.15 and 1.0 <= k["zoom_to"] <= 1.15
    # video intoccabile (trim 1..9 -> 8s)
    assert edl[2]["duration_sec"] == pytest.approx(8.0)


@pytest.mark.asyncio
async def test_director_deterministic():
    media = [_photo(f"p{i}", i) for i in range(6)]
    base = _state(media, markers=[2.0, 4.0, 6.0])
    out1 = await edit_director.run(copy.deepcopy(base))
    out2 = await edit_director.run(copy.deepcopy(base))
    assert out1["edit_decision_list"] == out2["edit_decision_list"]


@pytest.mark.asyncio
async def test_director_fits_audio_duration():
    media = [_photo("p1", 0, dur=4.0), _photo("p2", 1, dur=4.0)]
    out = await edit_director.run(_state(media, audio_dur=9.0, markers=[]))
    edl = out["edit_decision_list"]
    total = edl[-1]["start_sec_in_final_video"] + edl[-1]["duration_sec"]
    assert total == pytest.approx(9.0, abs=0.6)
    assert all(2.5 <= e["duration_sec"] <= 6.0 for e in edl)


@pytest.mark.asyncio
async def test_director_empty_media():
    out = await edit_director.run(_state([]))
    assert out["edit_decision_list"] == []


# --- Timeline Compiler ---

def _real_files_state(tmp_path, with_audio=True):
    """Stato con file reali su disco (foto piccole + click track)."""
    land = tmp_path / "land.jpg"
    Image.new("RGB", (320, 240), "red").save(land)
    port = tmp_path / "port.jpg"
    Image.new("RGB", (240, 320), "blue").save(port)
    st = state_store.new_project_state()
    st["media"] = [
        {"id": "a", "source": "local", "drive_file_id": None, "path": str(land),
         "type": "photo", "orientation": "landscape", "width": 320, "height": 240,
         "duration_sec": 4.0, "order_index": 0, "fit_mode": "cover",
         "background_fill": None, "trim_start_sec": None, "trim_end_sec": None},
        {"id": "b", "source": "local", "drive_file_id": None, "path": str(port),
         "type": "photo", "orientation": "portrait", "width": 240, "height": 320,
         "duration_sec": 4.0, "order_index": 1, "fit_mode": "contain",
         "background_fill": "blur", "trim_start_sec": None, "trim_end_sec": None},
    ]
    if with_audio:
        wav = tmp_path / "song.wav"
        sr = 22050
        n = 6 * sr
        x = np.zeros(n, dtype=np.float32)
        period = sr // 2  # 120 bpm
        for start in range(0, n - 64, period):
            x[start:start + 64] += 0.8 * np.hanning(64)
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        st["audio"] = {"path": str(wav), "duration_sec": 6.0, "bpm": 120.0,
                       "beat_markers_sec": [0.0, 2.0, 4.0], "energy_curve": [0.5] * 6}
    return st


@pytest.mark.asyncio
async def test_compiler_manifest(isolated_projects, tmp_path):
    st = _real_files_state(tmp_path)
    st = await edit_director.run(st)
    st = await timeline_compiler.run(st)
    mf = st["render_manifest"]
    assert mf["version"] == timeline_compiler.MANIFEST_VERSION
    assert len(mf["inputs"]) == 3  # 2 foto + audio
    assert len(mf["segments"]) == 2 and len(mf["transitions"]) == 1
    fc = mf["filter_complex"]
    assert "zoompan" in fc and "xfade" in fc and "overlay" in fc and "gblur" in fc
    assert mf["audio"] is not None and mf["output"]["audio_codec"] == "aac"
    # coerenza totale = somma - overlap
    expect = sum(s["duration_sec"] for s in mf["segments"]) - sum(t["duration_sec"] for t in mf["transitions"])
    assert mf["total_sec"] == pytest.approx(expect, abs=0.05)
    assert mf["args"][0] == "ffmpeg" and mf["args"][-1] == mf["output"]["path"]
    # total adattato all'audio da 6s
    assert mf["total_sec"] == pytest.approx(6.0, abs=0.6)


@pytest.mark.asyncio
async def test_compiler_empty_edl_noop(isolated_projects):
    st = state_store.new_project_state()
    out = await timeline_compiler.run(st)
    assert out["render_manifest"] is None


@pytest.mark.asyncio
async def test_compiler_rejects_bad_edl(isolated_projects, tmp_path):
    st = _real_files_state(tmp_path, with_audio=False)
    good = {"media_id": "a", "start_sec_in_final_video": 0.0, "duration_sec": 4.0,
            "ken_burns": {"movement": "zoom_in_slow", "zoom_from": 1.0, "zoom_to": 1.1,
                          "pan_x_from": 0.5, "pan_x_to": 0.5, "pan_y_from": 0.5, "pan_y_to": 0.5},
            "transition_in": 0.0, "transition_out": 0.8}
    good2 = dict(good, media_id="b", start_sec_in_final_video=3.2, transition_in=0.8,
                 transition_out=0.0)

    st["edit_decision_list"] = [copy.deepcopy(good) | {"media_id": "zzz"}]
    with pytest.raises(ValueError, match="inesistente"):
        await timeline_compiler.run(st)

    st["edit_decision_list"] = [copy.deepcopy(good), copy.deepcopy(good2)]
    st["edit_decision_list"][0]["transition_out"] = 5.0
    with pytest.raises(ValueError, match="transizione"):
        await timeline_compiler.run(st)

    st["edit_decision_list"] = [copy.deepcopy(good), copy.deepcopy(good2)]
    st["edit_decision_list"][0]["ken_burns"]["zoom_to"] = 2.0
    with pytest.raises(ValueError, match="zoom"):
        await timeline_compiler.run(st)


@pytest.mark.asyncio
async def test_smoke_render_real_ffmpeg(isolated_projects, tmp_path):
    """De-risk M5: il manifest gira davvero in ffmpeg e produce un mp4 valido."""
    st = _real_files_state(tmp_path)
    st = await edit_director.run(st)
    st = await timeline_compiler.run(st)
    mf = st["render_manifest"]
    proc = subprocess.run(mf["args"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = mf["output"]["path"]
    assert tmp_path in __import__("pathlib").Path(out).parents
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
         "-of", "json", out], capture_output=True, text=True)
    info = json.loads(probe.stdout)["format"]
    assert float(info["duration"]) == pytest.approx(mf["total_sec"], abs=0.6)
    assert int(info["size"]) > 10_000


# --- Endpoint /edit ---

def test_edit_endpoint(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), "red").save(buf, format="JPEG")
    buf.seek(0)
    assert client.post(f"/api/projects/{pid}/media",
                       files=[("files", ("a.jpg", buf, "image/jpeg"))]).status_code == 200
    resp = client.post(f"/api/projects/{pid}/edit")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["edit_decision_list"]) == 1
    assert body["edit_decision_list"][0]["ken_burns"]["movement"] in (
        "pan_left", "pan_right", "zoom_in_slow", "zoom_out_slow", "pan_and_zoom_diag")
    assert body["render_manifest"]["total_sec"] > 0
    stages = [e["stage"] for e in body["pipeline_log"] if e["status"] == "done"]
    assert stages[-4:] == ["sequence", "edit_director", "clip_overrides", "timeline_compiler"]
    assert client.post("/api/projects/inesistente/edit").status_code == 404
