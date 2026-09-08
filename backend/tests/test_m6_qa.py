"""Test M6: QA Agent + loop QA -> Edit Director."""
import copy

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.pipeline import state as state_store
from app.pipeline import orchestrator
from app.agents import edit_director, qa, render, timeline_compiler
from app.agents.qa import check_sync


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def _photo(tmp_path, name, size, color, mid, order):
    p = tmp_path / name
    Image.new("RGB", size, color).save(p)
    w, h = size
    orient = "portrait" if h > w else ("square" if h == w else "landscape")
    return {"id": mid, "source": "local", "drive_file_id": None, "path": str(p),
            "type": "photo", "orientation": orient, "width": w, "height": h,
            "duration_sec": 4.0, "order_index": order,
            "fit_mode": "contain" if orient == "portrait" else "cover",
            "background_fill": "blur" if orient == "portrait" else None,
            "trim_start_sec": None, "trim_end_sec": None}


@pytest.mark.asyncio
async def _rendered(tmp_path, with_audio=True):
    st = state_store.new_project_state()
    st["media"] = [_photo(tmp_path, "a.jpg", (320, 240), "red", "a", 0),
                   _photo(tmp_path, "b.jpg", (240, 320), "blue", "b", 1)]
    if with_audio:
        import io
        import wave
        import numpy as np
        from fastapi.testclient import TestClient as TC  # noqa
        sr = 22050
        x = np.zeros(6 * sr, dtype=np.float32)
        for s in range(0, 6 * sr - 64, sr // 2):
            x[s:s + 64] += 0.8 * np.hanning(64)
        wav = tmp_path / "s.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        st["audio"] = {"path": str(wav), "duration_sec": 6.0, "bpm": 120.0,
                       "beat_markers_sec": [0.0, 2.0, 4.0], "energy_curve": [0.5] * 6}
    st = await edit_director.run(st)
    st = await timeline_compiler.run(st)
    st = await render.run(st)
    return st


@pytest.mark.asyncio
async def test_qa_approved(isolated_projects, tmp_path):
    st = await _rendered(tmp_path)
    out = await qa.run(st)
    rep = out["qa_report"]
    assert rep["status"] == "approved"
    assert rep["issues"] == []
    assert {c["name"] for c in rep["checks"]} == {"duration", "av_sync", "verticals", "transitions"}
    assert all(c["passed"] for c in rep["checks"])


@pytest.mark.asyncio
async def test_qa_no_render_noop():
    out = await qa.run(state_store.new_project_state())
    assert out["qa_report"] is None


@pytest.mark.asyncio
async def test_qa_rejects_tampered_duration(isolated_projects, tmp_path):
    st = await _rendered(tmp_path, with_audio=False)
    st["render_manifest"]["total_sec"] += 5.0
    out = await qa.run(st)
    assert out["qa_report"]["status"] == "rejected"
    issue = out["qa_report"]["issues"][0]
    assert issue["check"] == "duration" and issue["route_to"] == "timeline_compiler"


@pytest.mark.asyncio
async def test_qa_rejects_tampered_verticals(isolated_projects, tmp_path):
    st = await _rendered(tmp_path, with_audio=False)
    seg = next(s for s in st["render_manifest"]["segments"] if s["fit"] == "contain")
    seg["fit"] = "cover"
    out = await qa.run(st)
    assert out["qa_report"]["status"] == "rejected"
    assert any(i["check"] == "verticals" for i in out["qa_report"]["issues"])


@pytest.mark.asyncio
async def test_qa_rejects_tampered_transitions(isolated_projects, tmp_path):
    st = await _rendered(tmp_path, with_audio=False)
    st["render_manifest"]["transitions"][0]["duration_sec"] = 0.0
    out = await qa.run(st)
    assert out["qa_report"]["status"] == "rejected"
    issue = next(i for i in out["qa_report"]["issues"] if i["check"] == "transitions")
    assert issue["route_to"] == "timeline_compiler"  # fix: transizioni sono tecniche, non di stile


def test_check_sync_unit():
    base = {"format": {"duration": "10.0"},
            "streams": [{"codec_type": "video", "duration": "10.0", "start_time": "0.0"},
                        {"codec_type": "audio", "duration": "10.1", "start_time": "0.0"}]}
    assert check_sync(base, True)[0] is True
    bad = copy.deepcopy(base)
    bad["streams"][1]["duration"] = "8.0"
    ok, msg = check_sync(bad, True)
    assert ok is False and "desync" in msg
    noaudio = copy.deepcopy(base)
    noaudio["streams"] = [noaudio["streams"][0]]
    assert check_sync(noaudio, True)[0] is False
    assert check_sync(noaudio, False)[0] is True


@pytest.mark.asyncio
async def test_director_honors_qa_feedback_fit_total():
    st = state_store.new_project_state()
    st["media"] = [
        {"id": "p1", "type": "photo", "duration_sec": 4.0, "order_index": 0},
        {"id": "p2", "type": "photo", "duration_sec": 4.0, "order_index": 1},
    ]
    # 11.0s: raggiungibile con 2 foto al tetto di 6.0s meno la dissolvenza
    st["qa_feedback"] = [{"check": "duration", "message": "troppo corto",
                           "type": "fit_total", "total_sec": 11.0}]
    out = await edit_director.run(st)
    edl = out["edit_decision_list"]
    total = edl[-1]["start_sec_in_final_video"] + edl[-1]["duration_sec"]
    assert total == pytest.approx(11.0, abs=0.6)


@pytest.mark.asyncio
async def test_orchestrator_qa_retry_loop(isolated_projects, tmp_path, monkeypatch):
    """Rigetto creativo transitorio -> 1 retry con qa_feedback -> approved."""
    calls = []

    async def fake_qa_run(state):
        calls.append(1)
        if len(calls) == 1:
            state["qa_report"] = {
                "status": "rejected", "checks": [],
                "issues": [{"check": "transitions", "message": "forzato in test",
                            "route_to": "edit_director"}]}
        else:
            state["qa_report"] = {"status": "approved", "checks": [], "issues": []}
        return state

    monkeypatch.setattr("app.pipeline.orchestrator.qa.run", fake_qa_run)
    st = state_store.new_project_state()
    st["media"] = [_photo(tmp_path, "a.jpg", (320, 240), "red", "a", 0)]
    out = await orchestrator.run_pipeline(st)
    assert out["qa_report"]["status"] == "approved"
    assert out["qa_attempts"] == 1
    assert out["qa_feedback"][0]["type"] == "fit_total"
    assert len(calls) == 2
    # retry ripianificato davvero: director+compiler+render rieseguiti
    names = [e["stage"] for e in out["pipeline_log"] if e["status"] == "done"]
    assert names.count("render") == 2 and names.count("qa") == 2


def test_render_endpoint_runs_qa(isolated_projects):
    import io
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), "red").save(buf, format="JPEG")
    buf.seek(0)
    client.post(f"/api/projects/{pid}/media", files=[("files", ("a.jpg", buf, "image/jpeg"))])
    body = client.post(f"/api/projects/{pid}/render").json()
    assert body["qa_report"]["status"] == "approved"
    assert body["render_manifest"]["status"] == "done"
