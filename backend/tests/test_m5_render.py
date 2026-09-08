"""Test M5: Render Agent + esportazione mp4 end-to-end + download."""
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
from app.agents import edit_director, render, timeline_compiler


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def _probe_duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())


def _upload_photo(client, pid, name="p.jpg", size=(320, 240), color="red"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    buf.seek(0)
    resp = client.post(f"/api/projects/{pid}/media",
                       files=[("files", (name, buf, "image/jpeg"))])
    assert resp.status_code == 200, resp.text
    return resp.json()


def _upload_clicks(client, pid, seconds=6.0):
    sr = 22050
    n = int(seconds * sr)
    x = np.zeros(n, dtype=np.float32)
    for start in range(0, n - 64, sr // 2):
        x[start:start + 64] += 0.8 * np.hanning(64)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    buf.seek(0)
    resp = client.post(f"/api/projects/{pid}/audio",
                       files=[("file", ("song.wav", buf, "audio/wav"))])
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_render_no_manifest_noop():
    st = state_store.new_project_state()
    out = await render.run(st)
    assert out["render_manifest"] is None
    assert out["errors"] == []


@pytest.mark.asyncio
async def test_render_failure_records_exact_error(isolated_projects, tmp_path):
    st = state_store.new_project_state()
    out_path = tmp_path / "x" / "final.mp4"
    st["render_manifest"] = {
        "version": 1,
        "args": ["ffmpeg", "-y", "-i", str(tmp_path / "missing.mp4"),
                 "-c:v", "libx264", str(out_path)],
        "output": {"path": str(out_path)},
        "inputs": [], "segments": [], "transitions": [],
        "filter_complex": "", "total_sec": 0, "audio": None,
    }
    with pytest.raises(RuntimeError):
        await render.run(st)
    assert len(st["errors"]) == 1
    assert st["errors"][0]["stage"] == "render"
    assert "ffmpeg exit=" in st["errors"][0]["message"]


def test_render_endpoint_end_to_end(isolated_projects):
    """Prima esportazione mp4 end-to-end: upload -> /render -> /download."""
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    _upload_photo(client, pid, "a.jpg", (320, 240), "red")
    _upload_photo(client, pid, "b.jpg", (240, 320), "blue")
    _upload_clicks(client, pid, seconds=6.0)

    resp = client.post(f"/api/projects/{pid}/render")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    mf = body["render_manifest"]
    assert mf["status"] == "done"
    assert mf["output"]["size_bytes"] > 10_000
    stages = [e["stage"] for e in body["pipeline_log"] if e["status"] == "done"]
    assert stages[-6:] == ["sequence", "edit_director", "clip_overrides",
                          "timeline_compiler", "render", "qa"]
    assert body["qa_report"]["status"] == "approved"

    dl = client.get(f"/api/projects/{pid}/download")
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "video/mp4"
    assert len(dl.content) > 10_000

    # durata reale coerente col manifest (tolleranza semantica container PTS)
    tmp_out = isolated_projects / "check.mp4"
    tmp_out.write_bytes(dl.content)
    assert _probe_duration(str(tmp_out)) == pytest.approx(mf["total_sec"], abs=0.6)


def test_render_validates_and_download_404(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    assert client.post(f"/api/projects/{pid}/render").status_code == 400  # nessun media
    assert client.get(f"/api/projects/{pid}/download").status_code == 404  # mai renderizzato
    _upload_photo(client, pid)
    # senza render, download ancora 404
    assert client.get(f"/api/projects/{pid}/download").status_code == 404
    assert client.post("/api/projects/inesistente/render").status_code == 404


def test_has_render_flag_in_list_projects(isolated_projects):
    """Verifica che has_render=True dopo render completato e False prima."""
    client = TestClient(app)
    
    # Progetto appena creato: ha_render=False
    pid = client.post("/api/projects").json()["project_id"]
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json()
    proj_entry = next((p for p in projects if p["project_id"] == pid), None)
    assert proj_entry is not None
    assert proj_entry["has_render"] is False
    
    # Upload foto e audio, poi render
    _upload_photo(client, pid, "a.jpg", (320, 240), "red")
    _upload_clicks(client, pid, seconds=6.0)
    
    resp = client.post(f"/api/projects/{pid}/render")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["render_manifest"]["status"] == "done"
    
    # Dopo render completato: has_render=True
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json()
    proj_entry = next((p for p in projects if p["project_id"] == pid), None)
    assert proj_entry is not None
    assert proj_entry["has_render"] is True
