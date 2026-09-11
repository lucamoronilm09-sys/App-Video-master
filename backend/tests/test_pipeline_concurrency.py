"""Test di concorrenza per la pipeline.

Verifica che l'esecuzione parallela di sequence e audio_analysis
non provochi race condition e che tutti i log/errori vengano preservati.
"""
import asyncio
import copy
import pytest
import shutil
from app.pipeline.orchestrator import run_pipeline, _copy_for_parallel_task, _merge_parallel_results


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    """Reindirizza i progetti in una cartella temporanea per non sporcare data/."""
    from app.api.routes import state_store
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


class TestParallelTaskIsolation:
    """Test per l'isolamento dei task paralleli."""

    def test_copy_creates_isolated_state(self):
        """Verifica che _copy_for_parallel_task crei copie isolate."""
        original = {
            "media": [{"id": 1, "duration": 10}],
            "timeline": [{"start": 0, "end": 10}],
            "project_id": "test-123",
            "project_dir": "/tmp/test",
            "pipeline_log": [{"stage": "intake", "status": "done"}],
            "errors": [],
            "extra_key": "value"
        }

        copied = _copy_for_parallel_task(original)

        # Verifica che le chiavi principali siano copiate
        assert copied["media"] == original["media"]
        assert copied["timeline"] == original["timeline"]
        assert copied["project_id"] == original["project_id"]
        assert copied["project_dir"] == original["project_dir"]

        # Verifica che pipeline_log e errors siano inizializzati vuoti
        assert copied["pipeline_log"] == []
        assert copied["errors"] == []

        # Verifica che non ci sia condivisione di riferimenti
        copied["media"].append({"id": 2})
        assert len(original["media"]) == 1, "Modifica alla copia non deve influenzare l'originale"

        copied["timeline"].append({"start": 10})
        assert len(original["timeline"]) == 1, "Modifica alla copia non deve influenzare l'originale"

    def test_copy_with_extra_keys(self):
        """Verifica il passaggio di chiavi extra."""
        original = {
            "media": [{"id": 1}],
            "audio_config": {"sample_rate": 44100},
        }

        extra = {"audio_config": {"bitrate": 128}, "tags": ["tag1", "tag2"]}
        copied = _copy_for_parallel_task(original, extra_keys=extra)

        assert copied["audio_config"] == {"bitrate": 128}
        assert copied["tags"] == ["tag1", "tag2"]

        # Verifica isolamento
        copied["audio_config"]["bitrate"] = 999
        assert extra["audio_config"]["bitrate"] == 128
        
        copied["tags"].append("tag3")
        assert extra["tags"] == ["tag1", "tag2"], "Le liste devono essere copiate in profondità"


class TestMergeResults:
    """Test per il merge deterministico dei risultati."""

    def test_merge_preserves_all_logs(self):
        """Verifica che tutti i log vengano preservati."""
        base = {"pipeline_log": [], "errors": []}
        seq_result = {
            "pipeline_log": [
                {"stage": "sequence", "status": "running", "ts": 1.0},
                {"stage": "sequence", "status": "done", "ts": 2.0},
            ],
            "errors": [],
            "media": [{"id": 1}],
        }
        aud_result = {
            "pipeline_log": [
                {"stage": "audio_analysis", "status": "running", "ts": 1.5},
                {"stage": "audio_analysis", "status": "done", "ts": 2.5},
            ],
            "errors": [],
            "audio": {"peaks": [1, 2, 3]},
        }

        merged = _merge_parallel_results(base, seq_result, aud_result)

        # Tutti i log devono essere presenti
        assert len(merged["pipeline_log"]) == 4
        
        # Devono essere ordinati per timestamp
        timestamps = [entry["ts"] for entry in merged["pipeline_log"]]
        assert timestamps == sorted(timestamps)

        # Verifica presenza di entrambi gli stage
        stages = [entry["stage"] for entry in merged["pipeline_log"]]
        assert "sequence" in stages
        assert "audio_analysis" in stages

    def test_merge_preserves_all_errors(self):
        """Verifica che tutti gli errori vengano preservati."""
        base = {"pipeline_log": [], "errors": []}
        seq_result = {
            "pipeline_log": [],
            "errors": [{"stage": "sequence", "message": "Errore seq"}],
        }
        aud_result = {
            "pipeline_log": [],
            "errors": [{"stage": "audio_analysis", "message": "Errore aud"}],
        }

        merged = _merge_parallel_results(base, seq_result, aud_result)

        assert len(merged["errors"]) == 2
        error_stages = [e["stage"] for e in merged["errors"]]
        assert "sequence" in error_stages
        assert "audio_analysis" in error_stages

    def test_merge_preserves_audio_data(self):
        """Verifica che i dati audio vengano preservati."""
        base = {"pipeline_log": [], "errors": []}
        seq_result = {
            "pipeline_log": [],
            "errors": [],
            "media": [{"id": 1}],
        }
        aud_result = {
            "pipeline_log": [],
            "errors": [],
            "audio": {"peaks": [1, 2, 3], "rms": 0.5},
        }

        merged = _merge_parallel_results(base, seq_result, aud_result)

        assert "audio" in merged
        assert merged["audio"]["peaks"] == [1, 2, 3]
        assert merged["audio"]["rms"] == 0.5

    def test_merge_deterministic_order(self):
        """Verifica che il merge sia deterministico."""
        base = {"pipeline_log": [], "errors": []}
        
        results = []
        for _ in range(10):
            seq_result = {
                "pipeline_log": [
                    {"stage": "sequence", "status": "done", "ts": 1.0},
                ],
                "errors": [],
                "media": [{"id": 1}],
            }
            aud_result = {
                "pipeline_log": [
                    {"stage": "audio_analysis", "status": "done", "ts": 1.5},
                ],
                "errors": [],
                "audio": {"data": "test"},
            }
            results.append(_merge_parallel_results(base, seq_result, aud_result))

        # Tutti i risultati devono essere identici
        for i in range(1, len(results)):
            assert results[i] == results[0], "Il merge deve essere deterministico"


class TestConcurrencyStress:
    """Test di stress per verificare assenza di race condition.
    
    Nota: I test end-to-end della pipeline completa richiedono file multimediali
    reali e sono gestiti da altri test nella suite. Questi test si concentrano
    sulla verifica dell'isolamento e del merge in scenari concorrenti simulati.
    """

    @pytest.mark.asyncio
    async def test_parallel_task_isolation_simulation(self, isolated_projects):
        """Simula l'esecuzione parallela con stati isolati."""
        from app.api.routes import state_store
        
        # Crea uno stato base condiviso
        project_id = "abcdef01"
        project_dir = state_store.project_dir(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        base_state = {
            "project_id": project_id,
            "project_dir": str(project_dir),
            "media": [{"filename": "video.mp4", "duration": 10.0}],
            "timeline": [],
            "pipeline_log": [{"stage": "intake", "status": "done", "ts": 1.0}],
            "errors": [],
        }

        try:
            # Simula la creazione di stati isolati per task paralleli
            seq_input = _copy_for_parallel_task(base_state)
            aud_input = _copy_for_parallel_task(base_state)
            
            # Simula modifiche concorrenti
            seq_input["pipeline_log"].append({"stage": "sequence", "status": "done", "ts": 2.0})
            seq_input["media"].append({"filename": "seq_added.mp4"})
            seq_input["errors"].append({"stage": "sequence", "message": "Seq error"})
            
            aud_input["pipeline_log"].append({"stage": "audio_analysis", "status": "done", "ts": 2.5})
            aud_input["audio"] = {"peaks": [1, 2, 3]}
            aud_input["errors"].append({"stage": "audio_analysis", "message": "Aud error"})
            
            # Verifica che le modifiche non abbiano influenzato lo stato base
            assert len(base_state["pipeline_log"]) == 1
            assert len(base_state["errors"]) == 0
            assert len(base_state["media"]) == 1
            
            # Esegui il merge - base_state ha pipeline_log vuoto perche' _merge_parallel_results
            # usa solo seq_result e aud_result, non include il base_state nei log
            merged = _merge_parallel_results(base_state, seq_input, aud_input)
            
            # Verifica che tutti i log siano presenti (solo quelli dei task paralleli)
            assert len(merged["pipeline_log"]) == 2
            stages = [e["stage"] for e in merged["pipeline_log"]]
            assert "sequence" in stages
            assert "audio_analysis" in stages
            
            # Verifica che tutti gli errori siano presenti
            assert len(merged["errors"]) == 2
            error_stages = [e["stage"] for e in merged["errors"]]
            assert "sequence" in error_stages
            assert "audio_analysis" in error_stages
            
            # Verifica che i dati audio siano preservati
            assert "audio" in merged
            assert merged["audio"]["peaks"] == [1, 2, 3]
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @pytest.mark.asyncio  
    async def test_deterministic_merge_multiple_times(self, isolated_projects):
        """Verifica che merge multipli producano sempre lo stesso risultato."""
        from app.api.routes import state_store
        
        project_id = "abcdef02"
        project_dir = state_store.project_dir(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        base_state = {
            "project_id": project_id,
            "project_dir": str(project_dir),
            "media": [{"filename": "video.mp4", "duration": 10.0}],
            "timeline": [],
            "pipeline_log": [],
            "errors": [],
        }

        try:
            results = []
            for _ in range(20):
                seq_result = {
                    "pipeline_log": [
                        {"stage": "sequence", "status": "done", "ts": 1.0 + i * 0.1}
                        for i in range(3)
                    ],
                    "errors": [{"stage": "sequence", "message": f"Error {i}"} for i in range(2)],
                    "media": [{"id": i} for i in range(3)],
                }
                aud_result = {
                    "pipeline_log": [
                        {"stage": "audio_analysis", "status": "done", "ts": 1.5 + i * 0.1}
                        for i in range(2)
                    ],
                    "errors": [{"stage": "audio_analysis", "message": f"Aud error {i}"} for i in range(1)],
                    "audio": {"data": "test"},
                }
                merged = _merge_parallel_results(base_state, seq_result, aud_result)
                results.append(merged)
            
            # Tutti i risultati devono essere identici
            for i in range(1, len(results)):
                assert results[i] == results[0], "Il merge deve essere deterministico"
                
            # Verifica struttura
            assert len(results[0]["pipeline_log"]) == 5  # 3 seq + 2 aud
            assert len(results[0]["errors"]) == 3  # 2 seq + 1 aud
            assert "audio" in results[0]
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)
