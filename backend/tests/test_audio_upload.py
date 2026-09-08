"""Regressione upload audio: la validazione magic-bytes deve accettare i file
reali (MP3 con tag ID3, FLAC, WMA/ASF, AAC, ...) e rifiutare solo spazzatura."""
import io
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.api.routes import _validate_audio_magic
from app.main import app
from app.pipeline import state as state_store


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def test_magic_mp3_id3_and_sync_variants():
    # MP3 reali: quasi tutti iniziano con ID3v2 (era rifiutato con 400)
    assert _validate_audio_magic(b"ID3\x04\x00" + b"\x00" * 20, ".mp3")
    # frame sync MPEG1-Layer3, MPEG2, MPEG2.5, AAC-ADTS
    for second in (0xFB, 0xF3, 0xF2, 0xF9, 0xF1, 0xE0):
        assert _validate_audio_magic(bytes([0xFF, second]) + b"\x00" * 20, ".mp3")
    # tag spazzatura in testa + sync entro 8KB
    assert _validate_audio_magic(b"APETAG" + b"\x00" * 100 + b"\xff\xfb" + b"\x00" * 20, ".mp3")
    # ma spazzatura pura resta rifiutata, e un MP3 non passa per .wav
    assert not _validate_audio_magic(b"ID3\x04\x00" + b"\x00" * 20, ".wav")
    assert not _validate_audio_magic(b"\x00" * 64, ".mp3")


def test_magic_other_formats():
    assert _validate_audio_magic(b"fLaC\x00\x00\x00" + b"\x00" * 20, ".flac")
    assert _validate_audio_magic(bytes([0x30, 0x26, 0xB2, 0x75]) + b"\x00" * 20, ".wma")
    assert _validate_audio_magic(b"RIFF" + b"\x00" * 8 + b"WAVE" + b"\x00" * 8, ".wav")
    assert _validate_audio_magic(b"OggS\x00\x02" + b"\x00" * 20, ".ogg")
    assert _validate_audio_magic(b"OggS\x00\x02" + b"\x00" * 20, ".opus")
    assert _validate_audio_magic(b"\x00\x00\x00\x1cftypM4A " + b"\x00" * 20, ".m4a")
    assert _validate_audio_magic(b"ADIF" + b"\x00" * 20, ".aac")
    assert _validate_audio_magic(bytes([0xFF, 0xF1, 0x50, 0x80]) + b"\x00" * 20, ".aac")
    assert not _validate_audio_magic(b"", ".mp3")
    assert not _validate_audio_magic(b"short", ".mp3")
    assert not _validate_audio_magic(b"\x00" * 64, ".xyz")


def _tone(out, *args):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1", *args, str(out)],
                   capture_output=True, check=True)
    return out.read_bytes()


def test_upload_real_mp3_with_id3_and_flac(isolated_projects, tmp_path):
    """File veri da ffmpeg: MP3 (con header ID3) e FLAC devono dare 200 + analisi."""
    mp3 = _tone(tmp_path / "a.mp3", "-c:a", "libmp3lame")
    flac = _tone(tmp_path / "a.flac", "-c:a", "flac")
    assert mp3.startswith(b"ID3")  # il caso che falliva
    assert flac.startswith(b"fLaC")
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    for name, data in (("a.mp3", mp3), ("a.flac", flac)):
        r = client.post(f"/api/projects/{pid}/audio",
                        files={"file": (name, io.BytesIO(data), "audio/mpeg")})
        assert r.status_code == 200, (name, r.text)
        assert r.json()["audio"]["duration_sec"] > 0


def test_upload_garbage_still_rejected(isolated_projects):
    client = TestClient(app)
    pid = client.post("/api/projects").json()["project_id"]
    r = client.post(f"/api/projects/{pid}/audio",
                    files={"file": ("a.mp3", io.BytesIO(b"\x00" * 1024), "audio/mpeg")})
    assert r.status_code == 400
