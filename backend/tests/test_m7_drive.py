"""Test M7: Google Drive (OAuth offline + browse/import con service finto, no rete)."""
import io
import subprocess
import types

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.pipeline import state as state_store
from app.agents import drive_import
from app.services import drive_client as dc

JPG = "image/jpeg"
PNG = "image/png"
MP4 = "video/mp4"
FOLDER = "application/vnd.google-apps.folder"


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def drive_paths(tmp_path, monkeypatch):
    """Isola credenziali/token/state OAuth in tmp (mai quelli veri in data/)."""
    d = tmp_path / "driveauth"
    d.mkdir()
    monkeypatch.setattr(dc, "CREDS_PATH", d / "google_credentials.json")
    monkeypatch.setattr(dc, "TOKEN_PATH", d / "drive_token.json")
    monkeypatch.setattr(dc, "OAUTH_STATE_PATH", d / "drive_oauth_state.json")
    return d


class _Req:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class FakeFiles:
    def __init__(self, tree):
        self.tree = tree  # id -> {id,name,mimeType,children?}

    def list(self, q, fields, orderBy, pageSize, pageToken=None):
        import re
        if "sharedWithMe=true" in q:
            # Query per "Condivisi con me": ritorna un set diverso di file
            kids = [dict(id=c, name=self.tree[c]["name"], mimeType=self.tree[c]["mimeType"])
                    for c in self.tree.get("shared", [])]
            return _Req({"files": kids})
        fid = re.search(r"'([^']+)' in parents", q).group(1)
        kids = [dict(id=c, name=self.tree[c]["name"], mimeType=self.tree[c]["mimeType"])
                for c in self.tree[fid].get("children", [])]
        return _Req({"files": kids})

    def get(self, fileId, fields=None):
        m = self.tree[fileId]
        return _Req({"id": m["id"], "name": m["name"], "mimeType": m["mimeType"]})

    def get_media(self, fileId):
        return types.SimpleNamespace(file_id=fileId)


class FakeService:
    def __init__(self, tree):
        self._files = FakeFiles(tree)

    def files(self):
        return self._files

    def about(self):
        return _Req({"user": {"emailAddress": "utente@example.com"}})


def _tree():
    return {
        "root": {"id": "root", "name": "root", "mimeType": FOLDER,
                 "children": ["f1", "v1", "t1", "A"]},
        "f1": {"id": "f1", "name": "foto1.jpg", "mimeType": JPG},
        "v1": {"id": "v1", "name": "video1.mp4", "mimeType": MP4},
        "t1": {"id": "t1", "name": "note.txt", "mimeType": "text/plain"},
        "A": {"id": "A", "name": "Vacanze", "mimeType": FOLDER, "children": ["m1", "doc", "B"]},
        "m1": {"id": "m1", "name": "mare.jpg", "mimeType": JPG},
        "doc": {"id": "doc", "name": "doc.pdf", "mimeType": "application/pdf"},
        "B": {"id": "B", "name": "sotto", "mimeType": FOLDER, "children": ["m2"]},
        "m2": {"id": "m2", "name": "montagna.png", "mimeType": PNG},
        # File condivisi con l'utente (diversi da "Il mio Drive")
        "shared": ["sf1", "sv1", "sA"],
        "sf1": {"id": "sf1", "name": "condiviso_foto.jpg", "mimeType": JPG},
        "sv1": {"id": "sv1", "name": "condiviso_video.mp4", "mimeType": MP4},
        "sA": {"id": "sA", "name": "CartellaCondivisa", "mimeType": FOLDER, "children": ["sm1"]},
        "sm1": {"id": "sm1", "name": "nella_cartella_condivisa.png", "mimeType": PNG},
    }


def _fake_download_factory(kinds):
    """Scrive byte reali (JPEG per foto, mp4 vero via ffmpeg per video)."""
    def _fake(request, dest):
        kind = kinds[request.file_id]
        if kind == "video":
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                            "-i", "testsrc=duration=1:size=320x240:rate=10",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)],
                           capture_output=True, check=True)
        else:
            Image.new("RGB", (400, 300), "teal").save(dest)
        return dest.stat().st_size
    return _fake


# --- OAuth offline ---

def test_credentials_and_status(drive_paths):
    client = TestClient(app)
    assert client.get("/api/drive/status").json() == {
        "configured": False, "connected": False, "email": None}
    resp = client.post("/api/drive/credentials",
                       json={"client_id": "id123", "client_secret": "shh"})
    assert resp.status_code == 200
    assert resp.json() == {"configured": True}  # secret mai riecheggiato
    assert client.get("/api/drive/status").json()["configured"] is True
    assert client.post("/api/drive/credentials",
                       json={"client_id": "", "client_secret": "x"}).status_code == 400


def test_auth_url_offline(drive_paths):
    client = TestClient(app)
    assert client.get("/api/drive/auth-url").status_code == 400  # non configurato
    dc.save_client_config("myid", "mysecret")
    url = client.get("/api/drive/auth-url").json()["url"]
    assert "accounts.google.com" in url and "myid" in url and "drive.readonly" in url


def test_callback_rejects_bad_state(drive_paths):
    client = TestClient(app)
    r = client.get("/api/drive/callback", params={"code": "x", "state": "wrong"})
    assert r.status_code == 400 and "state" in r.text.lower()


def test_status_connected_with_fake_service(drive_paths, monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(dc, "get_drive_service", lambda: FakeService(_tree()))
    monkeypatch.setattr(dc, "get_account_email", lambda s: "utente@example.com")
    dc.save_client_config("id", "secret")
    assert client.get("/api/drive/status").json() == {
        "configured": True, "connected": True, "email": "utente@example.com"}


# --- browse ---

def test_drive_files_listing(isolated_projects, drive_paths, monkeypatch):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    monkeypatch.setattr(dc, "get_drive_service", lambda: FakeService(_tree()))
    body = client.get(f"/api/projects/{pid}/drive/files").json()
    assert body["current"]["name"] == "Il mio Drive"
    by_name = {e["name"]: e for e in body["entries"]}
    assert by_name["Vacanze"]["is_folder"] is True
    assert by_name["foto1.jpg"]["is_folder"] is False
    sub = client.get(f"/api/projects/{pid}/drive/files", params={"folder_id": "A"}).json()
    assert sub["current"]["name"] == "Vacanze"
    assert {e["name"] for e in sub["entries"]} == {"mare.jpg", "doc.pdf", "sotto"}


def test_drive_files_shared_with_me(isolated_projects, drive_paths, monkeypatch):
    """Verifica che GET /drive/files?shared=true restituisca i file condivisi."""
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    monkeypatch.setattr(dc, "get_drive_service", lambda: FakeService(_tree()))
    
    # Richiesta per "Condivisi con me"
    shared_body = client.get(f"/api/projects/{pid}/drive/files", params={"shared": "true"}).json()
    assert shared_body["current"]["id"] == "shared"
    assert shared_body["current"]["name"] == "Condivisi con me"
    shared_names = {e["name"] for e in shared_body["entries"]}
    assert shared_names == {"condiviso_foto.jpg", "condiviso_video.mp4", "CartellaCondivisa"}
    
    # Verifica che sia diverso da "Il mio Drive"
    normal_body = client.get(f"/api/projects/{pid}/drive/files").json()
    normal_names = {e["name"] for e in normal_body["entries"]}
    assert shared_names != normal_names  # I set devono essere diversi
    
    # Navigare dentro una cartella condivisa usa list_children normale
    cartella_sub = client.get(f"/api/projects/{pid}/drive/files", params={"folder_id": "sA"}).json()
    assert cartella_sub["current"]["name"] == "CartellaCondivisa"
    assert {e["name"] for e in cartella_sub["entries"]} == {"nella_cartella_condivisa.png"}


def test_expand_selection_unit():
    media, skipped = dc.expand_selection(FakeService(_tree()), ["v1", "t1"], ["A"])
    assert {m["id"] for m in media} == {"v1", "m1", "m2"}
    assert any(s.get("id") == "t1" for s in skipped)  # txt esplicito scartato
    assert any(s.get("id") == "doc" for s in skipped)  # pdf nella cartella scartato


# --- import ---

@pytest.mark.asyncio
async def test_drive_import_agent_passthrough():
    out = await drive_import.run(state_store.new_project_state())
    assert out["media"] == []


def test_drive_import_endpoint(isolated_projects, drive_paths, monkeypatch):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    monkeypatch.setattr(dc, "get_drive_service", lambda: FakeService(_tree()))
    monkeypatch.setattr(dc, "_execute_download",
                        _fake_download_factory({"v1": "video", "m1": "img", "m2": "img"}))
    monkeypatch.setattr(dc, "load_credentials", lambda: object())  # connesso
    resp = client.post(f"/api/projects/{pid}/drive/import",
                       json={"file_ids": ["v1"], "folder_ids": ["A"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["media"]) == 3
    for m in body["media"]:
        assert m["source"] == "google_drive" and m["drive_file_id"] in {"v1", "m1", "m2"}
        assert m["width"] > 0 and "foto1" not in m["path"]
    assert sorted(m["order_index"] for m in body["media"]) == [0, 1, 2]
    kinds = {m["drive_file_id"]: m["type"] for m in body["media"]}
    assert kinds == {"v1": "video", "m1": "photo", "m2": "photo"}
    # pdf scartato senza bloccare, nome originale preservato su disco
    assert any("doc.pdf" in e["message"] for e in body["errors"])
    assert any("mare.jpg" in m["path"] for m in body["media"])


def test_drive_import_validations(isolated_projects, drive_paths, monkeypatch):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    # senza connessione -> 401
    r = client.post(f"/api/projects/{pid}/drive/import", json={"folder_ids": ["A"]})
    assert r.status_code == 401
    # selezione vuota -> 400
    monkeypatch.setattr(dc, "load_credentials", lambda: object())
    r = client.post(f"/api/projects/{pid}/drive/import", json={})
    assert r.status_code == 400
    assert client.post("/api/projects/inesistente/drive/import",
                       json={"folder_ids": ["A"]}).status_code == 404


def test_drive_import_from_shared_with_me(isolated_projects, drive_paths, monkeypatch):
    """Verifica che l'import funzioni anche per file ottenuti da 'Condivisi con me'."""
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    monkeypatch.setattr(dc, "get_drive_service", lambda: FakeService(_tree()))
    monkeypatch.setattr(dc, "_execute_download",
                        _fake_download_factory({"sf1": "img", "sv1": "video", "sm1": "img"}))
    monkeypatch.setattr(dc, "load_credentials", lambda: object())  # connesso
    
    # Importa un file condiviso (sf1) e una cartella condivisa (sA)
    resp = client.post(f"/api/projects/{pid}/drive/import",
                       json={"file_ids": ["sf1"], "folder_ids": ["sA"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Dovrebbe importare sf1 + sm1 (dentro sA)
    assert len(body["media"]) == 2
    drive_ids = {m["drive_file_id"] for m in body["media"]}
    assert drive_ids == {"sf1", "sm1"}
    for m in body["media"]:
        assert m["source"] == "google_drive"
        assert m["width"] > 0
