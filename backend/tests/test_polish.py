"""Test polish: thumbnail, EXIF, HEIC, codec H.265."""
import io
import subprocess

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.pipeline import state as state_store


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def _upload(client, pid, name, content: bytes, mime: str):
    resp = client.post(f"/api/projects/{pid}/media",
                       files=[("files", (name, io.BytesIO(content), mime))])
    assert resp.status_code == 200, resp.text
    return resp.json()


def _jpeg_bytes(size=(640, 480), exif_orientation=None) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, "orange")
    if exif_orientation:
        ex = Image.Exif()
        ex[274] = exif_orientation
        img.save(buf, format="JPEG", exif=ex)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def test_thumb_photo_and_cache(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    data = _upload(client, pid, "p.jpg", _jpeg_bytes((640, 480)), "image/jpeg")
    mid = data["media"][0]["id"]
    r1 = client.get(f"/api/projects/{pid}/media/{mid}/thumb")
    assert r1.status_code == 200 and r1.headers["content-type"] == "image/jpeg"
    thumb = Image.open(io.BytesIO(r1.content))
    assert thumb.width <= 320 and thumb.height <= 320 * 4
    r2 = client.get(f"/api/projects/{pid}/media/{mid}/thumb")
    assert r2.content == r1.content  # cache
    assert client.get(f"/api/projects/{pid}/media/zzz/thumb").status_code == 404


def test_thumb_video(isolated_projects, tmp_path):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    vp = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=10",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vp)],
                   capture_output=True, check=True)
    data = _upload(client, pid, "c.mp4", vp.read_bytes(), "video/mp4")
    mid = data["media"][0]["id"]
    r = client.get(f"/api/projects/{pid}/media/{mid}/thumb")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(r.content)).width <= 320


def test_exif_orientation_respected(isolated_projects):
    """Foto telefono 640x480 con EXIF 6 -> ritratto 480x640, non landscape."""
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    data = _upload(client, pid, "tel.jpg", _jpeg_bytes((640, 480), exif_orientation=6),
                   "image/jpeg")
    m = data["media"][0]
    assert (m["width"], m["height"]) == (480, 640)
    assert m["orientation"] == "portrait" and m["fit_mode"] == "contain"


def test_heic_upload(isolated_projects):
    pytest.importorskip("pillow_heif")
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "purple").save(buf, format="HEIF")
    data = _upload(client, pid, "a.heic", buf.getvalue(), "image/heic")
    assert data["media"][0]["type"] == "photo"
    assert (data["media"][0]["width"], data["media"][0]["height"]) == (400, 300)


def test_vcodec_setting_and_manifest(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    assert client.patch(f"/api/projects/{pid}/settings",
                        json={"vcodec": "h265"}).json()["output_spec"]["vcodec"] == "h265"
    assert client.patch(f"/api/projects/{pid}/settings",
                        json={"vcodec": "av1"}).status_code == 422
    _upload(client, pid, "p.jpg", _jpeg_bytes(), "image/jpeg")
    body = client.post(f"/api/projects/{pid}/edit").json()
    assert body["render_manifest"]["output"]["vcodec"] == "h265"
    assert "libx265" in body["render_manifest"]["args"]
