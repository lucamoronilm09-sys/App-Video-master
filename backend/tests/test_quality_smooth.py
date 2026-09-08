"""Test fix qualita' foto + fluidita' (post-M8).

- Foto: scaler lanczos, micro-dettaglio (unsharp solo foto), CRF 18 su H.264,
  metadati colore BT.709, timestamp resettati (niente frame duplicati/saltati).
- Video: lanczos senza unsharp (non amplifica rumore/compressione sorgente).
- Intake: fps nativo rilevato (source_fps) per consigliare output senza scatti.
- Smoke render reale con la nuova pipeline.
"""
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.agents import edit_director, intake, timeline_compiler
from app.pipeline import state as state_store
from app.services.media_inspect import _parse_fps, inspect_media


def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def _mk_photo(path: Path, size=(320, 240), color="red") -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def _mk_video(path: Path, fps: int = 25, duration: int = 2) -> Path:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=320x240:rate={fps}:duration={duration}",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", str(path)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return path


def _photo_media(mid, path, order, portrait=False):
    return {"id": mid, "source": "local", "drive_file_id": None, "path": str(path),
            "type": "photo", "orientation": "portrait" if portrait else "landscape",
            "width": 240 if portrait else 320, "height": 320 if portrait else 240,
            "duration_sec": 4.0, "order_index": order,
            "fit_mode": "contain" if portrait else "cover",
            "background_fill": "blur" if portrait else None,
            "trim_start_sec": None, "trim_end_sec": None}


def _video_media(mid, path, order, duration=2.0):
    return {"id": mid, "source": "local", "drive_file_id": None, "path": str(path),
            "type": "video", "orientation": "landscape", "width": 320, "height": 240,
            "duration_sec": duration, "order_index": order, "fit_mode": "cover",
            "background_fill": None, "trim_start_sec": None, "trim_end_sec": None}


async def _compiled_photos(tmp_path, vcodec="h264"):
    land = _mk_photo(tmp_path / "land.jpg")
    port = _mk_photo(tmp_path / "port.jpg", size=(240, 320), color="blue")
    st = state_store.new_project_state()
    st["media"] = [_photo_media("a", land, 0), _photo_media("b", port, 1, portrait=True)]
    st["output_spec"]["vcodec"] = vcodec
    st = await edit_director.run(st)
    return await timeline_compiler.run(st)


async def test_photo_segments_use_lanczos_and_unsharp(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    st = await _compiled_photos(tmp_path)
    fc = st["render_manifest"]["filter_complex"]
    # scaler di qualita' su ogni ridimensionamento (prima bicubic di default)
    assert fc.count("flags=lanczos") >= 4
    # recupero dettaglio solo sulle foto
    assert "unsharp=5:5:0.35" in fc
    for seg in st["render_manifest"]["segments"]:
        assert seg["kind"] == "photo"
        assert "setpts=PTS-STARTPTS" in seg["filter"]


async def test_video_segments_lanczos_without_unsharp(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    clip = _mk_video(tmp_path / "src.mp4")
    st = state_store.new_project_state()
    st["media"] = [_video_media("v", clip, 0)]
    st["edit_decision_list"] = [
        {"media_id": "v", "start_sec_in_final_video": 0.0, "duration_sec": 2.0,
         "ken_burns": None, "transition_in": 0.0, "transition_out": 0.0}]
    st = await timeline_compiler.run(st)
    fc = st["render_manifest"]["filter_complex"]
    assert "flags=lanczos" in fc
    assert "unsharp" not in fc  # i video restano intoccati


async def test_crf_per_codec_and_global_flags(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    st = await _compiled_photos(tmp_path, vcodec="h264")
    args = st["render_manifest"]["args"]
    assert "libx264" in args
    assert args[args.index("-crf") + 1] == "18"
    assert st["render_manifest"]["output"]["crf"] == 18
    assert st["render_manifest"]["output"]["preset"] == "medium"
    assert "-sws_flags" in args
    assert args[args.index("-colorspace") + 1] == "bt709"

    st265 = await _compiled_photos(tmp_path, vcodec="h265")
    args265 = st265["render_manifest"]["args"]
    assert "libx265" in args265  # scala CRF diversa: resta a 20
    assert args265[args265.index("-crf") + 1] == "20"


def test_parse_fps():
    assert _parse_fps("25/1") == 25.0
    assert _parse_fps("30000/1001") == 29.97
    assert _parse_fps("60000/1001") == 59.94
    assert _parse_fps("30") == 30.0
    assert _parse_fps("0/0") is None
    assert _parse_fps("") is None
    assert _parse_fps(None) is None
    assert _parse_fps("abc") is None
    assert _parse_fps("600/1") is None  # fuori intervallo sensato


async def test_source_fps_detected_on_import(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    clip = _mk_video(tmp_path / "src25.mp4", fps=25)
    photo = _mk_photo(tmp_path / "foto.jpg")
    assert (await inspect_media(clip))["source_fps"] == 25.0
    assert (await inspect_media(photo))["source_fps"] is None
    # catena Intake: il campo arriva nel Project State (la UI lo mostra)
    st = state_store.new_project_state()
    st["media_staging"] = [{"path": str(clip), "source": "local", "drive_file_id": None},
                           {"path": str(photo), "source": "local", "drive_file_id": None}]
    st = await intake.run(st)
    by_path = {Path(m["path"]).name: m for m in st["media"]}
    assert by_path["src25.mp4"]["source_fps"] == 25.0
    assert by_path["foto.jpg"]["source_fps"] is None


async def test_smoke_render_new_pipeline(tmp_path, monkeypatch):
    """Il manifest con i nuovi filtri gira davvero e produce un mp4 valido."""
    _isolated(tmp_path, monkeypatch)
    st = await _compiled_photos(tmp_path)
    mf = st["render_manifest"]
    proc = subprocess.run(mf["args"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = mf["output"]["path"]
    assert Path(out).is_file()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
         "-of", "json", out], capture_output=True, text=True)
    info = json.loads(probe.stdout)["format"]
    assert float(info["duration"]) == pytest.approx(mf["total_sec"], abs=0.6)
    assert int(info["size"]) > 10_000
