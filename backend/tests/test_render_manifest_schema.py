"""Test di schema del RenderManifest.

Verifica che:
1. Il manifest generato dal Timeline Compiler rispetti lo schema contrattuale
2. Tutti i campi required siano presenti
3. I tipi siano corretti
4. La validazione funzioni correttamente
"""
import pytest
from app.agents.render_manifest_schema import (
    MANIFEST_VERSION,
    create_manifest,
    validate_manifest_schema,
    InputEntry,
    SegmentEntry,
    TransitionEntry,
    AudioBlock,
)


class TestManifestSchemaValidation:
    """Test di validazione dello schema RenderManifest."""
    
    def test_valid_manifest_minimal(self):
        """Manifest minimale valido."""
        manifest = create_manifest(
            inputs=[{"index": 0, "path": "/tmp/video.mp4", "kind": "video"}],
            segments=[{
                "media_id": "m1",
                "input_index": 0,
                "kind": "video",
                "fit": "cover",
                "label": "v0",
                "filter": "[0:v]scale=1920:1080[v0]",
                "duration_sec": 5.0
            }],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-i", "/tmp/video.mp4", "-c:v", "libx264", "/tmp/out.mp4"],
            total_sec=5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
        )
        
        errors = validate_manifest_schema(manifest)
        assert errors == [], f"Errori di validazione: {errors}"
        assert manifest["version"] == MANIFEST_VERSION
        assert manifest["status"] == "ready"
    
    def test_valid_manifest_with_audio(self):
        """Manifest con audio valido."""
        audio_block: AudioBlock = {
            "tracks": [
                {"path": "/tmp/audio.mp3", "name": "Song", "duration_sec": 30.0}
            ]
        }
        
        manifest = create_manifest(
            inputs=[
                {"index": 0, "path": "/tmp/video.mp4", "kind": "video"},
                {"index": 1, "path": "/tmp/audio.mp3", "kind": "audio", "audio_track": 0}
            ],
            segments=[{
                "media_id": "m1",
                "input_index": 0,
                "kind": "video",
                "fit": "cover",
                "label": "v0",
                "filter": "[0:v]scale=1920:1080[v0]",
                "duration_sec": 5.0
            }],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-i", "/tmp/video.mp4", "-i", "/tmp/audio.mp3", "-c:v", "libx264", "/tmp/out.mp4"],
            total_sec=5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
            audio_block=audio_block,
        )
        
        errors = validate_manifest_schema(manifest)
        assert errors == [], f"Errori di validazione: {errors}"
        assert manifest["audio"] is not None
        assert len(manifest["audio"]["tracks"]) == 1
    
    def test_valid_manifest_with_transitions(self):
        """Manifest con transizioni valide."""
        manifest = create_manifest(
            inputs=[
                {"index": 0, "path": "/tmp/v1.mp4", "kind": "video"},
                {"index": 1, "path": "/tmp/v2.mp4", "kind": "video"},
            ],
            segments=[
                {
                    "media_id": "m1",
                    "input_index": 0,
                    "kind": "video",
                    "fit": "cover",
                    "label": "v0",
                    "filter": "[0:v]scale=1920:1080[v0]",
                    "duration_sec": 3.0
                },
                {
                    "media_id": "m2",
                    "input_index": 1,
                    "kind": "video",
                    "fit": "cover",
                    "label": "v1",
                    "filter": "[1:v]scale=1920:1080[v1]",
                    "duration_sec": 3.0
                }
            ],
            transitions=[{
                "index": 1,
                "from_segment": 0,
                "to_segment": 1,
                "duration_sec": 0.5,
                "offset_sec": 2.5,
                "cut": False
            }],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-i", "/tmp/v1.mp4", "-i", "/tmp/v2.mp4", "-c:v", "libx264", "/tmp/out.mp4"],
            total_sec=5.5,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
        )
        
        errors = validate_manifest_schema(manifest)
        assert errors == [], f"Errori di validazione: {errors}"
        assert len(manifest["transitions"]) == 1
        assert manifest["transitions"][0]["duration_sec"] == 0.5
    
    def test_missing_required_field(self):
        """Manifest con campo required mancante."""
        manifest = create_manifest(
            inputs=[],
            segments=[],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-c:v", "libx264", "/tmp/out.mp4"],
            total_sec=5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
        )
        
        # Rimuovi un campo required
        del manifest["total_sec"]
        
        errors = validate_manifest_schema(manifest)
        assert any("total_sec" in err for err in errors)
    
    def test_invalid_version(self):
        """Manifest con versione non corretta."""
        manifest = create_manifest(
            inputs=[],
            segments=[],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-c:v", "libx264", "/tmp/out.mp4"],
            total_sec=5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
        )
        
        manifest["version"] = 999
        
        errors = validate_manifest_schema(manifest)
        assert any("Versione mismatch" in err for err in errors)
    
    def test_invalid_status(self):
        """Manifest con status non valido."""
        manifest = create_manifest(
            inputs=[],
            segments=[],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-c:v", "libx264", "/tmp/out.mp4"],
            total_sec=5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
        )
        
        manifest["status"] = "invalid_status"
        
        errors = validate_manifest_schema(manifest)
        assert any("Status non valido" in err for err in errors)
    
    def test_output_missing_vcodec(self):
        """Manifest con output.vcodec mancante."""
        manifest = create_manifest(
            inputs=[],
            segments=[],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-c:v", "libx264", "/tmp/out.mp4"],
            total_sec=5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
        )
        
        del manifest["output"]["vcodec"]
        
        errors = validate_manifest_schema(manifest)
        assert any("output manca di vcodec" in err for err in errors)
    
    def test_negative_total_sec(self):
        """Manifest con total_sec negativo."""
        manifest = create_manifest(
            inputs=[],
            segments=[],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-c:v", "libx264", "/tmp/out.mp4"],
            total_sec=-5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
        )
        
        errors = validate_manifest_schema(manifest)
        assert any("total_sec deve essere positivo" in err for err in errors)
    
    def test_empty_args(self):
        """Manifest con args vuoto."""
        manifest = create_manifest(
            inputs=[],
            segments=[],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=[],
            total_sec=5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
        )
        
        errors = validate_manifest_schema(manifest)
        assert any("args deve essere una lista non vuota" in err for err in errors)


class TestManifestFactory:
    """Test della factory create_manifest."""
    
    def test_factory_sets_defaults(self):
        """La factory imposta i valori di default corretti."""
        manifest = create_manifest(
            inputs=[],
            segments=[],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-c:v", "libx264", "/tmp/out.mp4"],
            total_sec=5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
        )
        
        assert manifest["version"] == MANIFEST_VERSION
        assert manifest["status"] == "ready"
        assert manifest["output"]["preset"] == "medium"
        assert manifest["output"]["crf"] == 18
        assert manifest["source_video_audio"] == "muted"
        assert manifest["validation"] is None
    
    def test_factory_h265_crf(self):
        """La factory usa CRF corretto per h265."""
        manifest = create_manifest(
            inputs=[],
            segments=[],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-c:v", "libx265", "/tmp/out.mp4"],
            total_sec=5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h265",
        )
        
        assert manifest["output"]["crf"] == 20
    
    def test_factory_includes_filter_complex_inline(self):
        """La factory include filter_complex inline se fornito."""
        filter_inline = "[0:v]scale=1920:1080[vout]"
        manifest = create_manifest(
            inputs=[],
            segments=[],
            transitions=[],
            filter_complex_script="/tmp/filter.txt",
            args=["ffmpeg", "-y", "-c:v", "libx264", "/tmp/out.mp4"],
            total_sec=5.0,
            output_path="/tmp/out.mp4",
            resolution="1920x1080",
            fps=30,
            vcodec="h264",
            filter_complex_inline=filter_inline,
        )
        
        assert manifest["filter_complex"] == filter_inline
