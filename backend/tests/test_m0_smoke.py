"""Test dello scheletro M0: health endpoint, create/get project, orchestrator passthrough."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline import state as state_store
from app.pipeline.orchestrator import run_pipeline


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    """Reindirizza i progetti in una cartella temporanea per non sporcare data/."""
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def test_health():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "ai-video-maker-backend"
    assert "projects_count" in body


def test_create_then_get_project(isolated_projects):
    client = TestClient(app)
    created = client.post("/api/projects").json()
    assert created["project_id"]
    assert created["media"] == []
    assert created["audio"]["beat_markers_sec"] == []
    assert created["style_profile"] == "album_memory"
    assert created["output_spec"]["resolution"] == "1920x1080"
    assert created["output_spec"]["fps"] == 30
    assert created["output_spec"]["background_fill"] == "blur"

    got = client.get(f"/api/projects/{created['project_id']}")
    assert got.status_code == 200
    assert got.json()["project_id"] == created["project_id"]

    listing = client.get("/api/projects").json()
    assert any(p["project_id"] == created["project_id"] for p in listing)


def test_get_missing_project_returns_404(isolated_projects):
    client = TestClient(app)
    # Usa un ID progetto valido ma inesistente (formato esadecimale 8 caratteri)
    assert client.get("/api/projects/a1b2c3d4").status_code == 404


@pytest.mark.asyncio
async def test_orchestrator_passthrough_and_log(isolated_projects):
    state = state_store.new_project_state()
    state_store.ensure_project_dirs(state["project_id"])
    out = await run_pipeline(state)
    # passthrough: nessun media, nessuna EDL, nessun manifest, nessun errore
    assert out["media"] == []
    assert out["edit_decision_list"] == []
    assert out["render_manifest"] is None
    # qa_report potrebbe non essere presente se non ci sono media da analizzare
    assert out.get("qa_report") is None or out.get("qa_report") == []
    assert out["errors"] == []
    # log integrita': ogni stage ha running + done, con edit/compile/render/qa in coda
    names = [e["stage"] for e in out["pipeline_log"] if e["status"] == "done"]
    assert names == [
        "intake",
        "normalizer",
        "sequence",
        "audio_analysis",
        "edit_director",
        "clip_overrides",
        "timeline_compiler",
        "render",
        "qa",
    ]
