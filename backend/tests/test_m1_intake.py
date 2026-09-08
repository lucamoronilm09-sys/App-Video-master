"""Test M1: Intake Agent (metadata extraction) + upload endpoint."""
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.pipeline import state as state_store
from app.agents import intake
from app.services.media_inspect import inspect_media


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def _make_test_image(tmp_path: Path, name: str, size=(640, 480), color="red") -> Path:
    p = tmp_path / name
    img = Image.new("RGB", size, color)
    img.save(p)
    return p


def _make_test_video(tmp_path: Path, name: str) -> Path:
    """Crea un video sintetico minimo con ffmpeg (serve ffmpeg nel PATH)."""
    p = tmp_path / name
    import subprocess
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "testsrc=duration=2:size=320x240:rate=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)
        ],
        capture_output=True, check=True
    )
    return p


@pytest.mark.asyncio
async def test_inspect_image_metadata(isolated_projects):
    p = _make_test_image(isolated_projects, "photo.jpg", (1920, 1080))
    meta = await inspect_media(p)
    assert meta["width"] == 1920
    assert meta["height"] == 1080
    assert meta["type"] == "photo"
    assert meta["orientation"] == "landscape"
    assert meta["duration_sec"] == 0.0


@pytest.mark.asyncio
async def test_inspect_video_metadata(isolated_projects):
    p = _make_test_video(isolated_projects, "clip.mp4")
    meta = await inspect_media(p)
    assert meta["width"] == 320
    assert meta["height"] == 240
    assert meta["type"] == "video"
    assert meta["orientation"] == "landscape"
    assert meta["duration_sec"] > 0


@pytest.mark.asyncio
async def test_intake_agent_parallel_errors_and_success(isolated_projects):
    # 1 valida, 1 inesistente, 1 corrotto (immagine invalida)
    good = _make_test_image(isolated_projects, "good.jpg", (800, 1200))  # portrait
    bad = isolated_projects / "missing.jpg"
    corrupt = isolated_projects / "corrupt.jpg"
    corrupt.write_bytes(b"not an image")

    project_state = state_store.new_project_state()
    project_state["media_staging"] = [
        {"path": str(good), "source": "local"},
        {"path": str(bad), "source": "local"},
        {"path": str(corrupt), "source": "local"},
    ]
    out = await intake.run(project_state)

    assert len(out["media"]) == 1
    m = out["media"][0]
    assert m["width"] == 800
    assert m["height"] == 1200
    assert m["orientation"] == "portrait"
    assert m["type"] == "photo"
    assert len(out["errors"]) == 2
    assert all(e["stage"] == "intake" for e in out["errors"])


def test_upload_media_endpoint(isolated_projects):
    client = TestClient(app)
    # crea progetto
    proj = client.post("/api/projects").json()
    pid = proj["project_id"]

    # file immagine in memoria
    img_buf = io.BytesIO()
    Image.new("RGB", (400, 600), "blue").save(img_buf, format="JPEG")
    img_buf.seek(0)

    files = [("files", ("test.jpg", img_buf, "image/jpeg"))]
    resp = client.post(f"/api/projects/{pid}/media", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["media"]) == 1
    m = data["media"][0]
    assert m["width"] == 400
    assert m["height"] == 600
    assert m["orientation"] == "portrait"
    assert m["type"] == "photo"


def test_upload_multiple_files(isolated_projects):
    client = TestClient(app)
    proj = client.post("/api/projects").json()
    pid = proj["project_id"]

    files = []
    for i, (w, h) in enumerate([(1920, 1080), (1080, 1920), (800, 800)]):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), f"hsl({i*60},100%,50%)").save(buf, format="JPEG")
        buf.seek(0)
        files.append(("files", (f"img{i}.jpg", buf, "image/jpeg")))

    resp = client.post(f"/api/projects/{pid}/media", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["media"]) == 3
    orients = [m["orientation"] for m in data["media"]]
    assert "landscape" in orients
    assert "portrait" in orients
    assert "square" in orients


def test_upload_video_endpoint(isolated_projects):
    client = TestClient(app)
    proj = client.post("/api/projects").json()
    pid = proj["project_id"]

    import subprocess
    video_path = isolated_projects / "test.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=640x360:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video_path)],
        capture_output=True, check=True
    )
    with video_path.open("rb") as vf:
        resp = client.post(f"/api/projects/{pid}/media",
            files=[("files", ("clip.mp4", vf, "video/mp4"))])
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["media"]) == 1
    m = data["media"][0]
    assert m["type"] == "video"
    assert m["width"] == 640
    assert m["height"] == 360
    assert m["duration_sec"] > 0


def test_upload_fake_jpg_rejected(isolated_projects):
    """Test che un file .jpg con contenuto testuale arbitrario venga rifiutato."""
    client = TestClient(app)
    proj = client.post("/api/projects").json()
    pid = proj["project_id"]

    # Crea un file con estensione .jpg ma contenuto testuale (non immagine reale)
    fake_jpg_content = b"not an image"
    files = [("files", ("fake.jpg", io.BytesIO(fake_jpg_content), "image/jpeg"))]
    resp = client.post(f"/api/projects/{pid}/media", files=files)
    assert resp.status_code == 400
    assert "Contenuto file non corrisponde all'estensione" in resp.json()["detail"]


def test_batch_with_invalid_file_writes_nothing(isolated_projects):
    """Test che un batch con 2 file validi + 1 invalido non scriva nessun file su disco."""
    from pathlib import Path
    
    client = TestClient(app)
    proj = client.post("/api/projects").json()
    pid = proj["project_id"]
    
    media_dir = isolated_projects / pid / "media"
    
    # Crea 2 immagini valide
    img1_buf = io.BytesIO()
    Image.new("RGB", (400, 600), "blue").save(img1_buf, format="JPEG")
    img1_buf.seek(0)
    
    img2_buf = io.BytesIO()
    Image.new("RGB", (800, 800), "green").save(img2_buf, format="JPEG")
    img2_buf.seek(0)
    
    # Crea 1 file invalido (contenuto testuale con estensione .jpg)
    fake_jpg_content = b"this is not a valid image file"
    
    # Invia batch: 2 validi + 1 invalido
    files = [
        ("files", ("valid1.jpg", img1_buf, "image/jpeg")),
        ("files", ("valid2.jpg", img2_buf, "image/jpeg")),
        ("files", ("invalid.jpg", io.BytesIO(fake_jpg_content), "image/jpeg")),
    ]
    
    resp = client.post(f"/api/projects/{pid}/media", files=files)
    
    # Verifica che la risposta sia 4xx
    assert resp.status_code == 400
    assert "Contenuto file non corrisponde all'estensione" in resp.json()["detail"]
    
    # Verifica che NESSUN file sia stato scritto su disco
    # (il batch deve essere atomico: o tutti passano o nessuno viene scritto)
    assert not media_dir.exists() or list(media_dir.iterdir()) == []