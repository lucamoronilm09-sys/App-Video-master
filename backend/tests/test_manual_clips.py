"""Test modifiche manuali per-clip + transizioni frame-exact (no scatti)."""
import copy
import io
import json
import subprocess

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.pipeline import state as state_store
from app.agents import clip_overrides, edit_director, timeline_compiler


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


def _state(media):
    st = state_store.new_project_state()
    st["media"] = media
    return st


async def _directed(media):
    return await edit_director.run(_state(media))


# --- agent clip_overrides ---

async def test_overrides_noop_without_overrides():
    st = await _directed([_photo("p1", 0), _photo("p2", 1)])
    before = copy.deepcopy(st["edit_decision_list"])
    out = await clip_overrides.run(st)
    assert out["edit_decision_list"] == before


async def test_override_photo_duration_and_transition():
    st = await _directed([_photo("p1", 0), _photo("p2", 1), _photo("p3", 2)])
    st["clip_overrides"] = {"p1": {"duration_sec": 6.0, "transition_out": 1.2}}
    out = await clip_overrides.run(st)
    edl = out["edit_decision_list"]
    assert edl[0]["duration_sec"] == 6.0
    assert edl[0]["transition_out"] == 1.2 and edl[1]["transition_in"] == 1.2
    # start ricalcolati con overlap
    assert edl[1]["start_sec_in_final_video"] == pytest.approx(6.0 - 1.2, abs=0.01)
    assert edl[2]["start_sec_in_final_video"] == pytest.approx(
        edl[1]["start_sec_in_final_video"] + edl[1]["duration_sec"] - edl[1]["transition_out"],
        abs=0.01)


async def test_override_video_duration_recenters_trim():
    st = await _directed([_video("v1", 0, dur=10.0), _photo("p1", 1)])
    st["clip_overrides"] = {"v1": {"duration_sec": 4.0}}
    out = await clip_overrides.run(st)
    m = next(m for m in out["media"] if m["id"] == "v1")
    assert (m["trim_start_sec"], m["trim_end_sec"]) == (3.0, 7.0)
    assert out["edit_decision_list"][0]["duration_sec"] == 4.0


async def test_override_rejects_out_of_range():
    st = await _directed([_photo("p1", 0), _photo("p2", 1)])
    st["clip_overrides"] = {"p1": {"duration_sec": 99.0}}
    with pytest.raises(ValueError, match="durata foto"):
        await clip_overrides.run(st)
    st["clip_overrides"] = {"p2": {"transition_out": 0.5}}
    with pytest.raises(ValueError, match="ultima clip"):
        await clip_overrides.run(st)


async def test_override_ken_burns_movement_deterministic():
    st = await _directed([_photo("p1", 0), _photo("p2", 1)])
    st["clip_overrides"] = {"p1": {"ken_burns": "zoom_in_slow"}}
    out1 = await clip_overrides.run(copy.deepcopy(st))
    out2 = await clip_overrides.run(copy.deepcopy(st))
    kb1 = out1["edit_decision_list"][0]["ken_burns"]
    assert kb1["movement"] == "zoom_in_slow"
    assert kb1 == out2["edit_decision_list"][0]["ken_burns"]
    st["clip_overrides"] = {"p1": {"ken_burns": "static"}}
    kb = (await clip_overrides.run(st))["edit_decision_list"][0]["ken_burns"]
    assert kb["zoom_from"] == kb["zoom_to"] == 1.0


# --- endpoint PATCH/DELETE ---

def _project_with_edl(client, pid):
    for name, color in (("a.jpg", "red"), ("b.jpg", "blue")):
        buf = io.BytesIO()
        Image.new("RGB", (320, 240), color).save(buf, format="JPEG")
        buf.seek(0)
        assert client.post(f"/api/projects/{pid}/media",
                           files=[("files", (name, buf, "image/jpeg"))]).status_code == 200
    r = client.post(f"/api/projects/{pid}/edit")
    assert r.status_code == 200, r.text
    return r.json()


def test_patch_clip_endpoint(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    body = _project_with_edl(client, pid)
    first_id = body["edit_decision_list"][0]["media_id"]
    r = client.patch(f"/api/projects/{pid}/edit/clips/{first_id}",
                     json={"duration_sec": 6.0, "transition_out": 1.2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["clip_overrides"][first_id]["duration_sec"] == 6.0
    edl0 = body["edit_decision_list"][0]
    assert edl0["duration_sec"] == 6.0 and edl0["transition_out"] == 1.2
    assert body["edit_decision_list"][1]["transition_in"] == 1.2
    assert body["render_manifest"]["total_sec"] > 0  # ricompilato
    assert body["qa_report"] is None  # invalidato
    # validazioni
    assert client.patch(f"/api/projects/{pid}/edit/clips/{first_id}",
                        json={"duration_sec": 99}).status_code == 400
    assert client.patch(f"/api/projects/{pid}/edit/clips/inesistente",
                        json={"duration_sec": 5}).status_code == 404
    assert client.patch(f"/api/projects/{pid}/edit/clips/{first_id}",
                        json={}).status_code == 400
    # reset: torna al piano del regista
    r = client.delete(f"/api/projects/{pid}/edit/clips/{first_id}")
    assert r.status_code == 200, r.text
    assert first_id not in r.json()["clip_overrides"]


def test_patch_without_edl_rejected(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), "red").save(buf, format="JPEG")
    buf.seek(0)
    client.post(f"/api/projects/{pid}/media", files=[("files", ("a.jpg", buf, "image/jpeg"))])
    assert client.patch(f"/api/projects/{pid}/edit/clips/x",
                        json={"duration_sec": 5}).status_code in (400, 404)


def test_regenerate_keeps_manual_locks(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    _project_with_edl(client, pid)
    state = client.get(f"/api/projects/{pid}").json()
    first_id = state["edit_decision_list"][0]["media_id"]
    client.patch(f"/api/projects/{pid}/edit/clips/{first_id}", json={"duration_sec": 7.0})
    body = client.post(f"/api/projects/{pid}/edit").json()
    assert body["edit_decision_list"][0]["duration_sec"] == 7.0


# --- frame-exact / no scatti ---

def _real_state(tmp_path):
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
    return st


async def test_manifest_frame_exact(isolated_projects, tmp_path):
    """Segmenti e offset xfade sulla griglia dei frame (niente freeze)."""
    st = _real_state(tmp_path)
    st = await edit_director.run(st)
    st = await clip_overrides.run(st)
    st = await timeline_compiler.run(st)
    mf = st["render_manifest"]
    fps = mf["output"]["fps"]
    for s in mf["segments"]:
        assert abs(s["duration_sec"] * fps - round(s["duration_sec"] * fps)) < 0.02
    for t in mf["transitions"]:
        assert abs(t["duration_sec"] * fps - round(t["duration_sec"] * fps)) < 0.02
        assert abs(t["offset_sec"] * fps - round(t["offset_sec"] * fps)) < 0.05


async def test_cut_transition_compiles_and_qa_approves(isolated_projects, tmp_path):
    """Stacco manuale a 0.0s: compila senza xfade e il QA lo approva."""
    from app.agents import qa, render
    st = _real_state(tmp_path)
    st = await edit_director.run(st)
    st["clip_overrides"] = {"a": {"transition_out": 0.0}}
    st = await clip_overrides.run(st)
    st = await timeline_compiler.run(st)
    mf = st["render_manifest"]
    assert mf["transitions"][0]["duration_sec"] == 0.0
    assert mf["filter_complex"].count("xfade=") == 0
    st = await render.run(st)
    out = await qa.run(st)
    assert out["qa_report"]["status"] == "approved", out["qa_report"]


async def test_qa_rejects_incoherent_manual_transition(isolated_projects, tmp_path):
    """Manifest manomesso (0.0 vs EDL 0.8): rigettato per incoerenza."""
    from app.agents import qa, render
    st = _real_state(tmp_path)
    st = await edit_director.run(st)
    st = await timeline_compiler.run(st)
    st = await render.run(st)
    st["render_manifest"]["transitions"][0]["duration_sec"] = 0.0
    out = await qa.run(st)
    assert out["qa_report"]["status"] == "rejected"
    assert any(i["check"] == "transitions" for i in out["qa_report"]["issues"])


async def test_portrait_fg_contain_not_cropped(isolated_projects, tmp_path):
    """Il primo piano verticale deve stare in altezza H (contain), non 2x croppato."""
    st = _real_state(tmp_path)
    st = await edit_director.run(st)
    st = await timeline_compiler.run(st)
    seg_b = next(s for s in st["render_manifest"]["segments"] if s["media_id"] == "b")
    import re
    scales = re.findall(r"scale=(\d+):(\d+)", seg_b["filter"])
    # ultimo scale del ramo fg: altezza esattamente H=1080
    assert scales[-1][1] == "1080", seg_b["filter"]
    assert int(scales[-1][0]) % 2 == 0


async def test_smoke_render_manual_plan(isolated_projects, tmp_path):
    """Render reale con durata manuale + dissolvenza lunga: mp4 valido."""
    st = _real_state(tmp_path)
    st = await edit_director.run(st)
    st["clip_overrides"] = {"a": {"duration_sec": 5.0, "transition_out": 1.2}}
    st = await clip_overrides.run(st)
    st = await timeline_compiler.run(st)
    mf = st["render_manifest"]
    proc = subprocess.run(mf["args"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-3000:]
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", mf["output"]["path"]], capture_output=True, text=True)
    assert float(json.loads(probe.stdout)["format"]["duration"]) == pytest.approx(
        mf["total_sec"], abs=0.6)
