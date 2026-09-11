"""Test di render reale con FFmpeg usando il manifest generato.

Verifica che:
1. Il manifest generato dal Timeline Compiler produca un comando FFmpeg eseguibile
2. Il video output sia valido e coerente con le specifiche del manifest
3. La durata del file corrisponda a total_sec (entro tolleranza)
4. I codec e le risoluzioni siano corretti
"""
import io
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.agents import edit_director, timeline_compiler, render
from app.agents.render_manifest_schema import validate_manifest_schema
from app.pipeline import state as state_store


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    """Fixture per isolare i progetti in una directory temporanea."""
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def _photo(tmp_path, name, size, color, mid, order):
    """Crea una foto di test."""
    p = tmp_path / name
    Image.new("RGB", size, color).save(p)
    w, h = size
    orient = "portrait" if h > w else ("square" if h == w else "landscape")
    return {
        "id": mid,
        "source": "local",
        "drive_file_id": None,
        "path": str(p),
        "type": "photo",
        "orientation": orient,
        "width": w,
        "height": h,
        "duration_sec": 4.0,
        "order_index": order,
        "fit_mode": "contain" if orient == "portrait" else "cover",
        "background_fill": "blur" if orient == "portrait" else None,
        "trim_start_sec": None,
        "trim_end_sec": None,
        "vision_analysis": {
            "ai_used": True,
            "importance": 0.5,
            "emotional_intensity": 0.5,
            "people_count": 0,
            "recommended_pacing": "normal"
        }
    }


def _audio_track(tmp_path, name, duration_sec=6.0):
    """Crea una traccia audio di test."""
    sr = 22050
    n = int(duration_sec * sr)
    x = np.zeros(n, dtype=np.float32)
    # Aggiungi click periodici per simulare beat
    for start in range(0, n - 64, sr // 2):
        x[start:start + 64] += 0.8 * np.hanning(64)
    
    wav_path = tmp_path / name
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    
    return {
        "path": str(wav_path),
        "name": name,
        "duration_sec": duration_sec,
        "bpm": 120.0,
        "beat_times_sec": [x * 0.5 for x in range(int(duration_sec * 2))],
        "beat_markers_sec": [0.0, 2.0, 4.0],
        "energy_curve": [0.5] * int(duration_sec)
    }


def _probe_video(path: Path) -> dict:
    """Estrae metadata da un video usando ffprobe."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", 
         "-show_entries", "stream=codec_name,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe fallito: {proc.stderr}")
    return json.loads(proc.stdout)


class TestRealFfmpegRender:
    """Test di render reale con FFmpeg."""
    
    @pytest.mark.asyncio
    async def test_manifest_produces_valid_ffmpeg_command(self, isolated_projects, tmp_path):
        """Il manifest genera un comando FFmpeg che esegue correttamente."""
        # Prepara stato del progetto
        st = state_store.new_project_state()
        st["media"] = [
            _photo(tmp_path, "land.jpg", (320, 240), "red", "a", 0),
            _photo(tmp_path, "port.jpg", (240, 320), "blue", "b", 1),
        ]
        st["audio"] = _audio_track(tmp_path, "song.wav", duration_sec=6.0)
        
        # Esegui Edit Director
        st = await edit_director.run(st)
        assert len(st["edit_decision_list"]) == 2
        
        # Esegui Timeline Compiler
        st = await timeline_compiler.run(st)
        manifest = st["render_manifest"]
        
        # Verifica che il manifest sia valido secondo lo schema
        errors = validate_manifest_schema(manifest)
        assert errors == [], f"Manifest non valido: {errors}"
        
        # Verifica campi required
        assert "args" in manifest
        assert len(manifest["args"]) > 5
        assert manifest["output"]["vcodec"] in ("libx264", "libx265")
        assert manifest["total_sec"] > 0
        
        # Esegui FFmpeg usando gli args del manifest
        proc = subprocess.run(manifest["args"], capture_output=True, text=True, timeout=60)
        
        assert proc.returncode == 0, f"FFmpeg fallito: {proc.stderr[-2000:]}"
        
        # Verifica che il file output esista
        out_path = Path(manifest["output"]["path"])
        assert out_path.is_file(), "File output non creato"
        assert out_path.stat().st_size > 10000, "File output troppo piccolo"
    
    @pytest.mark.asyncio
    async def test_output_duration_matches_manifest(self, isolated_projects, tmp_path):
        """La durata dell'output corrisponde al total_sec del manifest."""
        st = state_store.new_project_state()
        st["media"] = [
            _photo(tmp_path, "p1.jpg", (320, 240), "red", "p1", 0),
            _photo(tmp_path, "p2.jpg", (320, 240), "green", "p2", 1),
        ]
        st["audio"] = _audio_track(tmp_path, "audio.wav", duration_sec=8.0)
        
        st = await edit_director.run(st)
        st = await timeline_compiler.run(st)
        st = await render.run(st)
        
        manifest = st["render_manifest"]
        assert manifest["status"] == "done"
        
        # Verifica durata con ffprobe
        info = _probe_video(Path(manifest["output"]["path"]))
        actual_duration = float(info["format"]["duration"])
        
        # Tolleranza di 0.5s per differenze di container/PTS
        assert abs(actual_duration - manifest["total_sec"]) <= 0.6, \
            f"Durata mismatch: {actual_duration}s vs {manifest['total_sec']}s"
        
        # Verifica che output.duration_sec sia stato popolato
        assert "duration_sec" in manifest["output"]
        assert abs(manifest["output"]["duration_sec"] - actual_duration) <= 0.01
    
    @pytest.mark.asyncio
    async def test_output_codec_and_resolution(self, isolated_projects, tmp_path):
        """Codec e risoluzione dell'output corrispondono alle specifiche."""
        st = state_store.new_project_state()
        st["output_spec"] = {"resolution": "1920x1080", "fps": 30, "vcodec": "h264"}
        st["media"] = [_photo(tmp_path, "p.jpg", (320, 240), "yellow", "p", 0)]
        st["audio"] = _audio_track(tmp_path, "a.wav", duration_sec=5.0)
        
        st = await edit_director.run(st)
        st = await timeline_compiler.run(st)
        st = await render.run(st)
        
        manifest = st["render_manifest"]
        info = _probe_video(Path(manifest["output"]["path"]))
        
        streams = info.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_name") in ("h264", "hevc")), None)
        
        assert video_stream is not None, "Nessuno stream video trovato"
        
        # Verifica codec
        expected_vcodec = manifest["output"]["vcodec"]
        actual_codec = video_stream.get("codec_name")
        # libx264 -> h264, libx265 -> hevc
        codec_map = {"libx264": "h264", "libx265": "hevc"}
        assert actual_codec == codec_map.get(expected_vcodec, expected_vcodec), \
            f"Codec mismatch: {actual_codec} vs {expected_vcodec}"
        
        # Verifica risoluzione
        width = video_stream.get("width")
        height = video_stream.get("height")
        expected_res = manifest["output"]["resolution"]
        exp_w, exp_h = map(int, expected_res.split("x"))
        
        assert width == exp_w and height == exp_h, \
            f"Risoluzione mismatch: {width}x{height} vs {exp_w}x{exp_h}"
    
    @pytest.mark.asyncio
    async def test_render_segmented_fallback(self, isolated_projects, tmp_path):
        """Il fallback segmentato funziona se il render monolitico fallisce."""
        st = state_store.new_project_state()
        st["media"] = [
            _photo(tmp_path, "p1.jpg", (320, 240), "red", "p1", 0),
            _photo(tmp_path, "p2.jpg", (320, 240), "blue", "p2", 1),
            _photo(tmp_path, "p3.jpg", (320, 240), "green", "p3", 2),
        ]
        st["audio"] = _audio_track(tmp_path, "audio.wav", duration_sec=10.0)
        
        st = await edit_director.run(st)
        st = await timeline_compiler.run(st)
        
        manifest = st["render_manifest"]
        
        # Verifica che il manifest abbia segments e filter_complex_script
        assert len(manifest["segments"]) >= 2
        assert Path(manifest["filter_complex_script"]).is_file()
        
        # Simula fallimento del render monolitico corrompendo args
        original_args = manifest["args"].copy()
        manifest["args"] = ["ffmpeg", "-y", "-i", "/nonexistent.mp4"] + original_args[3:]
        
        # Il render dovrebbe fallbackare su quello segmentato
        try:
            st = await render.run(st)
            # Se arriva qui, il fallback ha funzionato
            assert st["render_manifest"]["status"] == "done"
        except RuntimeError as e:
            # Se fallisce anche il fallback, è un errore
            if "fallback segmentato fallito" in str(e):
                pytest.fail(f"Il fallback segmentato non ha funzionato: {e}")
            raise
    
    @pytest.mark.asyncio
    async def test_validation_report_populated(self, isolated_projects, tmp_path):
        """Il validation report viene popolato dopo il render."""
        st = state_store.new_project_state()
        st["media"] = [_photo(tmp_path, "p.jpg", (320, 240), "purple", "p", 0)]
        st["audio"] = _audio_track(tmp_path, "a.wav", duration_sec=4.0)
        
        st = await edit_director.run(st)
        st = await timeline_compiler.run(st)
        st = await render.run(st)
        
        manifest = st["render_manifest"]
        
        assert manifest["validation"] is not None
        assert "codec" in manifest["validation"]
        assert "width" in manifest["validation"]
        assert "height" in manifest["validation"]
        assert "duration" in manifest["validation"]
        assert manifest["output"]["size_bytes"] > 0
        assert "rendered_at" in manifest["output"]


class TestManifestSchemaInPipeline:
    """Test che il manifest rispetti lo schema durante la pipeline."""
    
    @pytest.mark.asyncio
    async def test_manifest_schema_after_compiler(self, isolated_projects, tmp_path):
        """Il manifest dopo il compiler rispetta lo schema."""
        st = state_store.new_project_state()
        st["media"] = [
            _photo(tmp_path, "p1.jpg", (320, 240), "red", "p1", 0),
            _photo(tmp_path, "p2.jpg", (240, 320), "blue", "p2", 1),
        ]
        st["audio"] = _audio_track(tmp_path, "a.wav", duration_sec=6.0)
        
        st = await edit_director.run(st)
        st = await timeline_compiler.run(st)
        
        manifest = st["render_manifest"]
        errors = validate_manifest_schema(manifest)
        
        assert errors == [], f"Manifest post-compiler non valido: {errors}"
        assert manifest["status"] == "ready"
        assert manifest["version"] == 7  # MANIFEST_VERSION corrente
    
    @pytest.mark.asyncio
    async def test_manifest_schema_after_render(self, isolated_projects, tmp_path):
        """Il manifest dopo il render rispetta lo schema."""
        st = state_store.new_project_state()
        st["media"] = [_photo(tmp_path, "p.jpg", (320, 240), "orange", "p", 0)]
        st["audio"] = _audio_track(tmp_path, "a.wav", duration_sec=5.0)
        
        st = await edit_director.run(st)
        st = await timeline_compiler.run(st)
        st = await render.run(st)
        
        manifest = st["render_manifest"]
        errors = validate_manifest_schema(manifest)
        
        assert errors == [], f"Manifest post-render non valido: {errors}"
        assert manifest["status"] == "done"
        assert manifest["validation"] is not None
