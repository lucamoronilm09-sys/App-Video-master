from fastapi.testclient import TestClient

from app.main import app
from app.pipeline import state as state_store
from app.services import drive_client as dc


class Req:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class Files:
    def list(self, **kwargs):
        q = kwargs["q"]
        if "sharedWithMe=true" in q:
            return Req({
                "files": [
                    {"id": "shared-file", "name": "foto condivisa.jpg", "mimeType": "image/jpeg"},
                    {"id": "shared-folder", "name": "Cartella condivisa", "mimeType": "application/vnd.google-apps.folder"},
                ]
            })
        raise AssertionError(f"unexpected query: {q}")

    def get(self, fileId, fields=None):
        if fileId == "shared-folder":
            return Req({
                "id": fileId,
                "name": "Cartella condivisa",
                "mimeType": "application/vnd.google-apps.folder",
            })
        return Req({"id": fileId, "name": "foto.jpg", "mimeType": "image/jpeg"})


class Service:
    def files(self):
        return Files()


def test_shared_alias_works_without_frontend_shared_query(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(dc, "get_drive_service", lambda: Service())
    monkeypatch.setattr(dc, "load_credentials", lambda: object())

    with TestClient(app) as client:
        pid = client.post("/api/projects").json()["project_id"]
        response = client.get(f"/api/projects/{pid}/drive/files", params={"folder_id": "shared"})

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["current"] == {"id": "shared", "name": "Condivisi con me"}
    assert {entry["id"] for entry in data["entries"]} == {"shared-file", "shared-folder"}


def test_progress_endpoint_returns_jobs_and_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)

    with TestClient(app) as client:
        pid = client.post("/api/projects").json()["project_id"]
        response = client.get(f"/api/projects/{pid}/progress")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["media_count"] == 0
    assert data["has_render"] is False
    assert isinstance(data["jobs"], list)
