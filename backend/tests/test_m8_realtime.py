"""Test M8: eventi realtime (SSE) + gestione errori."""
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline import state as state_store
from app.api.routes import progress_payload, watch_project


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def test_progress_payload_unit():
    st = state_store.new_project_state()
    st["errors"] = [{"stage": "intake", "message": "x"}]
    st["pipeline_log"] = [{"stage": "render", "status": "done", "ts": 1.0}]
    st["render_manifest"] = {"status": "done"}
    st["qa_report"] = {"status": "approved"}
    p = progress_payload(st)
    assert p["errors_count"] == 1
    assert p["pipeline_log"][-1]["stage"] == "render"
    assert p["has_render"] is True and p["qa_status"] == "approved"
    assert p["has_edit"] is False and p["has_audio"] is False


def test_events_404(isolated_projects):
    client = TestClient(app)
    assert client.get("/api/projects/inesistente/events").status_code == 404


@pytest.mark.asyncio
async def test_watch_project_emits_on_change(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    gen = watch_project(pid, poll_sec=0.01, heartbeat_every=1000)
    first = await gen.__anext__()
    assert first.startswith("data:")
    data = json.loads(first[len("data:"):])
    assert data["errors_count"] == 0 and "updated_at" in data

    # modifica -> nuovo evento con payload aggiornato
    st = state_store.load_state(pid)
    st["errors"] = [{"stage": "intake", "message": "x"}]
    state_store.save_state(st)
    second = None
    for _ in range(500):
        evt = await gen.__anext__()
        if evt.startswith("data:"):
            second = evt
            break
    await gen.aclose()
    assert second is not None and second != first
    assert json.loads(second[len("data:"):])["errors_count"] == 1


def test_clear_errors(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    
    # Simula un errore non bloccante manualmente (es. warning intake)
    st = state_store.load_state(pid)
    st["errors"] = [{"stage": "intake", "message": "File parziale o corrotto"}]
    state_store.save_state(st)
    
    # Verifica che l'errore sia presente
    r = client.get(f"/api/projects/{pid}")
    assert len(r.json()["errors"]) == 1
    
    # Clear errors endpoint
    cleared = client.post(f"/api/projects/{pid}/errors/clear")
    assert cleared.status_code == 200
    assert cleared.json()["errors"] == []
    assert client.get(f"/api/projects/{pid}").json()["errors"] == []
    assert client.post("/api/projects/inesistente/errors/clear").status_code == 404
