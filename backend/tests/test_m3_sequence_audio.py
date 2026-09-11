"""Test M3: visual analysis + audio analysis + upload endpoints."""
import io
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.pipeline import state as state_store
from app.agents import audio_analysis, sequence
from app.services.audio_features import analyze_audio


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setenv("VISION_PROVIDER", "disabled")
    return tmp_path


def _click_track(path, bpm=120.0, seconds=8.0, sr=22050):
    n = int(seconds * sr)
    x = np.zeros(n, dtype=np.float32)
    period = int(sr * 60.0 / bpm)
    click = (np.hanning(64) * np.sin(2 * np.pi * 2000 * np.arange(64) / sr)).astype(np.float32)
    k = 0
    for start in range(0, n - 64, period):
        amp = 1.0 if k % 4 == 0 else 0.5
        x[start:start + 64] += amp * click
        k += 1
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def _silent_wav(path, seconds=3.0, sr=22050):
    pcm = np.zeros(int(seconds * sr), dtype=np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


@pytest.mark.asyncio
async def test_sequence_photo_analysis_does_not_assign_duration(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "disabled")
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (640, 480), "red").save(photo)
    media = [{"id": "photo0", "type": "photo", "path": str(photo), "duration_sec": 0.0, "order_index": 0}]
    out = await sequence.run({"media": media})
    item = out["media"][0]
    assert item["duration_sec"] is None
    assert "vision_analysis" in item
    assert item["vision_analysis"]["ai_used"] is False
    assert item["vision_analysis"]["visual_interest"] >= 0.0


@pytest.mark.asyncio
async def test_sequence_never_reorders():
    media = [
        {"id": "b", "type": "photo", "duration_sec": 0.0, "order_index": 1},
        {"id": "a", "type": "photo", "duration_sec": 0.0, "order_index": 0},
    ]
    out = await sequence.run({"media": media})
    assert [m["id"] for m in out["media"]] == ["b", "a"]


@pytest.mark.asyncio
async def test_sequence_video_trim():
    media = [
        {"id": "long", "type": "video", "duration_sec": 12.0, "order_index": 0},
        {"id": "short", "type": "video", "duration_sec": 5.0, "order_index": 1},
        {"id": "exact", "type": "video", "duration_sec": 8.0, "order_index": 2},
    ]
    out = await sequence.run({"media": media})
    by_id = {m["id"]: m for m in out["media"]}
    assert by_id["long"]["duration_sec"] == 12.0
    assert by_id["long"]["trim_start_sec"] == pytest.approx(2.0)
    assert by_id["long"]["trim_end_sec"] == pytest.approx(10.0)
    assert by_id["short"]["trim_start_sec"] is None
    assert by_id["short"]["trim_end_sec"] is None
    assert by_id["exact"]["trim_start_sec"] is None


def test_analyze_click_track_bpm(tmp_path):
    p = _click_track(tmp_path / "clicks.wav", bpm=120.0, seconds=8.0)
    res = analyze_audio(p)
    assert res["duration_sec"] == pytest.approx(8.0, abs=0.1)
    assert res["bpm"] == pytest.approx(120.0, abs=3.0)
    assert len(res["beat_times_sec"]) >= 12
    assert len(res["downbeat_times_sec"]) >= 2
    gaps = [b - a for a, b in zip(res["downbeat_times_sec"], res["downbeat_times_sec"][1:])]
    assert all(g == pytest.approx(2.0, abs=0.15) for g in gaps)
    assert res["beat_markers_sec"] == res["downbeat_times_sec"]
    assert all(0.0 <= m <= res["duration_sec"] for m in res["beat_times_sec"])
    assert len(res["energy_curve"]) == pytest.approx(res["duration_sec"], abs=1.0)
    assert all(0.0 <= v <= 1.0 for v in res["energy_curve"])
    assert max(res["energy_curve"]) == pytest.approx(1.0)


def test_analyze_silence(tmp_path):
    p = _silent_wav(tmp_path / "sil.wav")
    res = analyze_audio(p)
    assert res["bpm"] == 0.0
    assert res["beat_times_sec"] == []
    assert res["downbeat_times_sec"] == []
    assert res["beat_markers_sec"] == []
    assert set(res["energy_curve"]) == {0.0}


@pytest.mark.asyncio
async def test_audio_agent_no_path_passthrough():
    out = await audio_analysis.run(state_store.new_project_state())
    assert out["audio"]["bpm"] == 0.0
    assert out["errors"] == []


@pytest.mark.asyncio
async def test_audio_agent_missing_file_error():
    state = state_store.new_project_state()
    state["audio"]["path"] = "/nonexistent/track.mp3"
    out = await audio_analysis.run(state)
    assert len(out["errors"]) == 1
    assert out["errors"][0]["stage"] == "audio_analysis"


def _upload_photo(client, pid, name="p.jpg", size=(640, 480)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format="JPEG")
    buf.seek(0)
    resp = client.post(f"/api/projects/{pid}/media",
                       files=[("files", (name, buf, "image/jpeg"))])
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_upload_assigns_photo_duration(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    data = _upload_photo(client, pid)
    assert 0.0 <= data["media"][0].get("importance_score", 0.5) <= 1.0
    # Dopo Sequence, le foto hanno duration_sec=None (Edit Director la deciderà)
    # ma hanno provisional_duration_sec per l'UI
    assert data["media"][0]["duration_sec"] is None
    assert data["media"][0].get("provisional_duration_sec") is not None


def test_upload_audio_endpoint(isolated_projects, tmp_path):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    _click_track(tmp_path / "song.wav", bpm=120.0, seconds=8.0)
    with (tmp_path / "song.wav").open("rb") as f:
        resp = client.post(f"/api/projects/{pid}/audio",
                           files=[("file", ("song.wav", f, "audio/wav"))])
    assert resp.status_code == 200, resp.text
    audio = resp.json()["audio"]
    assert audio["path"] and audio["path"].endswith(".wav")
    assert audio["duration_sec"] == pytest.approx(8.0, abs=0.2)
    assert audio["bpm"] == pytest.approx(120.0, abs=3.0)
    assert len(audio["beat_times_sec"]) >= 12
    assert len(audio["downbeat_times_sec"]) >= 2


def test_upload_audio_rejects_bad_format(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    resp = client.post(f"/api/projects/{pid}/audio",
                       files=[("file", ("notes.txt", io.BytesIO(b"ciao"), "text/plain"))])
    assert resp.status_code == 400
    assert client.post("/api/projects/inesistente/audio",
                       files=[("file", ("s.wav", io.BytesIO(b"x"), "audio/wav"))]).status_code == 404


def test_upload_audio_replaces_previous(isolated_projects, tmp_path):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    _silent_wav(tmp_path / "a.wav", seconds=2.0)
    _silent_wav(tmp_path / "b.wav", seconds=3.0)
    with (tmp_path / "a.wav").open("rb") as f:
        first = client.post(f"/api/projects/{pid}/audio",
                            files=[("file", ("a.wav", f, "audio/wav"))]).json()["audio"]
    with (tmp_path / "b.wav").open("rb") as f:
        second = client.post(f"/api/projects/{pid}/audio",
                             files=[("file", ("b.wav", f, "audio/wav"))]).json()["audio"]
    assert first["path"] != second["path"]
    assert second["duration_sec"] == pytest.approx(3.0, abs=0.2)
