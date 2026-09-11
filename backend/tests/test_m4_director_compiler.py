"""Test M4: AI-aware Edit Director + Timeline Compiler + real FFmpeg smoke."""
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

MOVEMENTS = ("pan_left", "pan_right", "zoom_in_slow", "zoom_out_slow", "pan_and_zoom_diag")


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setenv("VISION_PROVIDER", "disabled")
    return tmp_path


def _vision(importance=0.6, emotion=0.5, people=1, pacing="normal"):
    return {"ai_used": True, "importance": importance, "emotional_intensity": emotion, "subject_clarity": 0.9,
            "visual_interest": 0.8, "people_count": people, "is_group_photo": people >= 2,
            "is_portrait": False, "is_landscape": True, "is_action": False, "is_closeup": False,
            "scene_type": "memory", "recommended_pacing": pacing}


def _photo(mid, order, dur=4.0, portrait=False, vision=None):
    return {"id": mid, "source": "local", "drive_file_id": None, "path": f"/tmp/{mid}.jpg",
            "type": "photo", "orientation": "portrait" if portrait else "landscape",
            "width": 1080 if portrait else 1920, "height": 1920 if portrait else 1080,
            "duration_sec": dur, "order_index": order, "fit_mode": "contain" if portrait else "cover",
            "background_fill": "blur" if portrait else None, "trim_start_sec": None, "trim_end_sec": None,
            "vision_analysis": vision or _vision()}


def _video(mid, order, dur=10.0):
    return {"id": mid, "source": "local", "drive_file_id": None, "path": f"/tmp/{mid}.mp4", "type": "video",
            "orientation": "landscape", "width": 1920, "height": 1080, "duration_sec": dur, "order_index": order,
            "fit_mode": "cover", "background_fill": None, "trim_start_sec": 1.0 if dur > 8 else None,
            "trim_end_sec": 9.0 if dur > 8 else None}


def _state(media, audio_dur=0.0, markers=(), beats=()):
    st = state_store.new_project_state()
    st["media"] = media
    st["audio"] = {"path": None, "duration_sec": audio_dur, "bpm": 120.0,
                   "beat_times_sec": list(beats), "downbeat_times_sec": list(markers),
                   "beat_markers_sec": list(markers), "energy_curve": [0.5] * max(1, int(audio_dur or 1))}
    return st


@pytest.mark.asyncio
async def test_director_uses_photo_profile():
    low = _photo("low", 0, vision=_vision(importance=0.2, emotion=0.1, people=0, pacing="fast"))
    high = _photo("high", 1, vision=_vision(importance=0.95, emotion=0.95, people=5, pacing="hold"))
    out = await edit_director.run(_state([low, high]))
    d = {e["media_id"]: e["duration_sec"] for e in out["edit_decision_list"]}
    assert d["high"] > d["low"]
    assert all(2.0 <= x <= 7.0 for x in d.values())


@pytest.mark.asyncio
async def test_director_edl_structure():
    media = [_photo("p1", 0), _photo("p2", 1, portrait=True), _video("v1", 2), _photo("p3", 3)]
    beats = [x * 0.5 for x in range(20)]
    out = await edit_director.run(_state(media, audio_dur=8.0, markers=[0, 2, 4, 6], beats=beats))
    edl = out["edit_decision_list"]
    assert len(edl) == 4
    assert [e["media_id"] for e in edl] == ["p1", "p2", "v1", "p3"]
    
    # Verifica coerenza timeline con transizioni:
    # start[i] = start[i-1] + duration[i-1] - transition_out[i-1]
    for prev, cur in zip(edl, edl[1:]):
        expected_start = prev["start_sec_in_final_video"] + prev["duration_sec"] - prev["transition_out"]
        assert cur["start_sec_in_final_video"] == pytest.approx(expected_start, abs=0.02)
        # Coerenza transizioni: transition_out della precedente == transition_in della corrente
        assert cur["transition_in"] == pytest.approx(prev["transition_out"], abs=0.01)
    
    # Ultima clip deve avere transition_out = 0
    assert edl[-1]["transition_out"] == 0.0
    # Prima clip deve avere transition_in = 0
    assert edl[0]["transition_in"] == 0.0
    
    assert edl[2]["duration_sec"] == pytest.approx(8.0)


@pytest.mark.asyncio
async def test_director_deterministic():
    media = [_photo(f"p{i}", i) for i in range(6)]
    base = _state(media, beats=[x * 0.5 for x in range(20)])
    out1 = await edit_director.run(copy.deepcopy(base))
    out2 = await edit_director.run(copy.deepcopy(base))
    assert out1["edit_decision_list"] == out2["edit_decision_list"]


@pytest.mark.asyncio
async def test_director_fits_audio_duration_and_beat_grid():
    media = [_photo("p1", 0, dur=4.0), _photo("p2", 1, dur=4.0)]
    beats = [x * 0.5 for x in range(20)]
    out = await edit_director.run(_state(media, audio_dur=9.0, beats=beats))
    edl = out["edit_decision_list"]
    total = edl[-1]["start_sec_in_final_video"] + edl[-1]["duration_sec"]
    assert total == pytest.approx(9.0, abs=0.05)
    assert all(2.0 <= e["duration_sec"] <= 7.0 for e in edl)
    assert any(edl[1]["start_sec_in_final_video"] == pytest.approx(b, abs=0.01) for b in beats)
    assert all(e["duration_reason"] == "vision+music" for e in edl)


@pytest.mark.asyncio
async def test_director_empty_media():
    assert (await edit_director.run(_state([])))["edit_decision_list"] == []


def _real_files_state(tmp_path, with_audio=True):
    land = tmp_path / "land.jpg"; Image.new("RGB", (320, 240), "red").save(land)
    port = tmp_path / "port.jpg"; Image.new("RGB", (240, 320), "blue").save(port)
    st = state_store.new_project_state()
    st["media"] = [
        {"id": "a", "source": "local", "drive_file_id": None, "path": str(land), "type": "photo", "orientation": "landscape", "width": 320, "height": 240, "duration_sec": 4.0, "order_index": 0, "fit_mode": "cover", "background_fill": None, "trim_start_sec": None, "trim_end_sec": None, "vision_analysis": _vision(0.7, 0.6, 1)},
        {"id": "b", "source": "local", "drive_file_id": None, "path": str(port), "type": "photo", "orientation": "portrait", "width": 240, "height": 320, "duration_sec": 4.0, "order_index": 1, "fit_mode": "contain", "background_fill": "blur", "trim_start_sec": None, "trim_end_sec": None, "vision_analysis": _vision(0.8, 0.7, 2)},
    ]
    if with_audio:
        wav = tmp_path / "song.wav"; sr = 22050; n = 6 * sr
        x = np.zeros(n, dtype=np.float32); period = sr // 2
        for start in range(0, n - 64, period): x[start:start + 64] += 0.8 * np.hanning(64)
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        st["audio"] = {"path": str(wav), "duration_sec": 6.0, "bpm": 120.0,
                       "beat_times_sec": [x * 0.5 for x in range(12)], "beat_markers_sec": [0.0, 2.0, 4.0], "energy_curve": [0.5] * 6}
    return st


@pytest.mark.asyncio
async def test_compiler_manifest(isolated_projects, tmp_path):
    st = await edit_director.run(_real_files_state(tmp_path))
    st = await timeline_compiler.run(st)
    mf = st["render_manifest"]
    assert mf["version"] == timeline_compiler.MANIFEST_VERSION
    assert len(mf["inputs"]) == 3 and len(mf["segments"]) == 2 and len(mf["transitions"]) == 1
    assert "zoompan" in mf["filter_complex"] and "gblur" in mf["filter_complex"]
    assert mf["audio"] is not None and mf["output"]["audio_codec"] == "aac"
    expect = sum(s["duration_sec"] for s in mf["segments"])
    assert mf["total_sec"] == pytest.approx(expect, abs=0.05)
    assert mf["total_sec"] == pytest.approx(6.0, abs=0.2)


@pytest.mark.asyncio
async def test_compiler_empty_edl_noop(isolated_projects):
    assert (await timeline_compiler.run(state_store.new_project_state()))["render_manifest"] is None


@pytest.mark.asyncio
async def test_smoke_render_real_ffmpeg(isolated_projects, tmp_path):
    st = await edit_director.run(_real_files_state(tmp_path))
    st = await timeline_compiler.run(st)
    mf = st["render_manifest"]
    proc = subprocess.run(mf["args"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = mf["output"]["path"]
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "json", out], capture_output=True, text=True)
    info = json.loads(probe.stdout)["format"]
    assert float(info["duration"]) == pytest.approx(mf["total_sec"], abs=0.6)
    assert int(info["size"]) > 10_000


def test_edit_endpoint(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    buf = io.BytesIO(); Image.new("RGB", (320, 240), "red").save(buf, format="JPEG"); buf.seek(0)
    assert client.post(f"/api/projects/{pid}/media", files=[("files", ("a.jpg", buf, "image/jpeg"))]).status_code == 200
    resp = client.post(f"/api/projects/{pid}/edit")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["edit_decision_list"]) == 1
    assert body["edit_decision_list"][0]["ken_burns"]["movement"] in MOVEMENTS
    assert body["render_manifest"]["total_sec"] > 0
