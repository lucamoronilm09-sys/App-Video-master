"""Test coda job: submit 202, worker, progress, 409, recovery."""
import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.jobs import manager as jobs
from app.pipeline import state as state_store


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    return tmp_path


def _upload_photo(client, pid, name="p.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), "red").save(buf, format="JPEG")
    buf.seek(0)
    r = client.post(f"/api/projects/{pid}/media",
                    files=[("files", (name, buf, "image/jpeg"))])
    assert r.status_code == 200, r.text


def _wait_job(client, jid, timeout=120):
    deadline = time.time() + timeout
    while True:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed"):
            return j
        assert time.time() < deadline, f"job {jid} mai completato: {j}"
        time.sleep(1)


def test_render_job_background(isolated):
    with TestClient(app) as client:
        pid = client.post("/api/projects").json()["project_id"]
        _upload_photo(client, pid)
        r = client.post(f"/api/projects/{pid}/render", params={"background": "true"})
        assert r.status_code == 202, r.text
        job = r.json()["job"]
        assert job["status"] in ("queued", "running")
        # doppio submit mentre attivo -> 409
        assert client.post(f"/api/projects/{pid}/render",
                           params={"background": "true"}).status_code == 409
        final = _wait_job(client, job["job_id"])
        assert final["status"] == "done", final.get("error")
        assert final["progress"]["fraction"] == 1.0
        assert final["result"]["qa_status"] == "approved"
        body = client.get(f"/api/projects/{pid}").json()
        assert body["render_manifest"]["status"] == "done"
        assert body["qa_report"]["status"] == "approved"
        assert "_job_id" not in body
        assert client.get("/api/jobs/inesistente").status_code == 404


def test_drive_import_job_background(isolated, monkeypatch):
    from app.services import drive_client as dc

    tree = {
        "root": {"id": "root", "name": "root",
                 "mimeType": "application/vnd.google-apps.folder", "children": ["f1"]},
        "f1": {"id": "f1", "name": "a.jpg", "mimeType": "image/jpeg"},
    }

    class Req:
        def __init__(self, p): self._p = p
        def execute(self): return self._p

    class Files:
        def list(self, **kw): return Req({"files": [dict(id="f1", name="a.jpg",
                                                          mimeType="image/jpeg")]})
        def get(self, fileId, fields=None): return Req(dict(tree[fileId], **{}))
        def get_media(self, fileId): return object()

    class Svc:
        def files(self): return Files()

    monkeypatch.setattr(dc, "get_drive_service", lambda: Svc())
    monkeypatch.setattr(dc, "load_credentials", lambda: object())

    def fake_dl(request, dest):
        Image.new("RGB", (200, 150), "blue").save(dest)
        return dest.stat().st_size
    monkeypatch.setattr(dc, "_execute_download", fake_dl)

    with TestClient(app) as client:
        pid = client.post("/api/projects").json()["project_id"]
        r = client.post(f"/api/projects/{pid}/drive/import",
                        params={"background": "true"}, json={"file_ids": ["f1"]})
        assert r.status_code == 202, r.text
        final = _wait_job(client, r.json()["job"]["job_id"])
        assert final["status"] == "done", final.get("error")
        body = client.get(f"/api/projects/{pid}").json()
        assert len(body["media"]) == 1
        assert body["media"][0]["source"] == "google_drive"


def test_recover_and_submit_validation(isolated):
    with pytest.raises(ValueError):
        jobs.submit("p", "nope")
    j = jobs.submit("p1", "render")
    assert j["status"] == "queued"
    with pytest.raises(jobs.JobExistsError):
        jobs.submit("p1", "render")  # stesso kind attivo
    jobs.submit("p1", "drive_import")  # altro kind ok
    stored = jobs.get(j["job_id"])
    stored["status"] = "running"
    jobs._write(stored)
    assert jobs.recover() == 1
    assert jobs.get(j["job_id"])["status"] == "queued"
    assert jobs.get("zzz") is None
