"""Manager della coda job (vedi package docstring).

Gestione completa del ciclo di vita dei job con cleanup affidabile delle risorse:
- Cleanup eseguito al completamento (successo/errore), cancellazione, retry
- Try/finally per garantire cleanup anche in caso di eccezioni
- Logging strutturato con project/job ID
- Prevenzione race condition tra job paralleli
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import DATA_DIR
from app.jobs import progress as prog
from app.logging_config import get_logger, safe_log_dict
from app.pipeline import state as state_store

logger = get_logger(__name__)

JOBS_DIR = DATA_DIR / "jobs"
KINDS = ("render", "drive_import")

# Directory per file temporanei associati ai job
JOB_TEMP_DIR = DATA_DIR / "jobs_temp"


class JobExistsError(Exception):
    pass


def _path(job_id: str) -> Path:
    if "/" in job_id or "\\" in job_id or not job_id:
        raise ValueError("job_id non valido")
    return JOBS_DIR / f"{job_id}.json"


def _write(job: dict) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = JOBS_DIR / f".{job['job_id']}.tmp"
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_path(job["job_id"]))


def get(job_id: str) -> dict | None:
    try:
        p = _path(job_id)
    except ValueError:
        return None
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _all() -> list[dict]:
    if not JOBS_DIR.is_dir():
        return []
    out = []
    for p in JOBS_DIR.glob("*.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def recent_for_project(project_id: str, limit: int = 5) -> list[dict]:
    jobs = [j for j in _all() if j.get("project_id") == project_id]
    jobs.sort(key=lambda j: j.get("updated_at", 0), reverse=True)
    return jobs[:limit]


def active_for_project(project_id: str, kind: str) -> dict | None:
    for j in _all():
        if (j.get("project_id") == project_id and j.get("kind") == kind
                and j.get("status") in ("queued", "running")):
            return j
    return None


def submit(project_id: str, kind: str, params: dict | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind non supportato: {kind}")
    if active_for_project(project_id, kind):
        raise JobExistsError(f"job {kind} già in corso per questo progetto")
    now = time.time()
    job = {"job_id": uuid.uuid4().hex[:12], "project_id": project_id, "kind": kind,
           "status": "queued", "params": params or {},
           "progress": {"fraction": 0.0, "note": "in coda", "stage": "queued"},
           "result": None, "error": None,
           "created_at": now, "updated_at": now}
    _write(job)
    return job


def _touch(job: dict, **fields) -> dict:
    job.update(fields)
    job["updated_at"] = time.time()
    _write(job)
    return job


def set_stage(job_id: str, stage: str, note: str = "") -> None:
    job = get(job_id)
    if not job:
        return
    lvl = prog.pop(job_id)
    frac, pnote = lvl if lvl else (job["progress"].get("fraction", 0.0),
                                  job["progress"].get("note", ""))
    job["progress"] = {"fraction": frac, "note": pnote or note, "stage": stage}
    _touch(job)


def recover() -> int:
    """-running -> queued all'avvio (crash precedenti). Ritorna i recuperati."""
    n = 0
    for job in _all():
        if job.get("status") == "running":
            job["status"] = "queued"
            job["progress"] = {"fraction": 0.0, "note": "riaccodato dopo riavvio",
                               "stage": "queued"}
            _touch(job)
            n += 1
    return n


def _claim() -> dict | None:
    queued = [j for j in _all() if j.get("status") == "queued"]
    if not queued:
        return None
    queued.sort(key=lambda j: j.get("created_at", 0))
    job = queued[0]
    job["status"] = "running"
    job["progress"] = {"fraction": 0.0, "note": "avvio", "stage": "starting"}
    _touch(job)
    return job


def cleanup_job_temp_files(job_id: str, project_id: str | None = None, 
                            keep_output: bool = True) -> dict[str, int]:
    """Esegue il cleanup dei file temporanei di un job completato.
    
    Args:
        job_id: ID del job da pulire
        project_id: ID del progetto (opzionale, per logging)
        keep_output: Se True, preserva l'output finale del render
        
    Returns:
        Dizionario con conteggio file/directory rimossi
    """
    job_logger = get_logger(f"jobs.cleanup.{job_id}")
    stats = {"files_removed": 0, "dirs_removed": 0, "errors": 0}
    
    log_context = safe_log_dict({"job_id": job_id, "project_id": project_id})
    job_logger.info("Cleanup risorse job %s: %s", job_id, log_context)
    
    try:
        # 1. Cleanup directory temp specifica del job in JOB_TEMP_DIR
        job_temp_dir = JOB_TEMP_DIR / job_id
        if job_temp_dir.exists():
            try:
                removed_count = sum(1 for _ in job_temp_dir.rglob("*"))
                shutil.rmtree(job_temp_dir, ignore_errors=False)
                stats["dirs_removed"] += 1
                stats["files_removed"] += removed_count
                job_logger.info("Rimossa directory temp %s (%d file)", job_temp_dir, removed_count)
            except Exception as exc:
                job_logger.warning("Errore nel rimuovere %s: %s", job_temp_dir, exc)
                stats["errors"] += 1
        
        # 2. Cleanup file temporanei ffmpeg nella system temp dir
        import tempfile
        temp_dir = Path(tempfile.gettempdir())
        try:
            for pattern in [f"render_{job_id}*", f".render_parts_{job_id}*"]:
                for tmp_file in temp_dir.glob(pattern):
                    try:
                        if tmp_file.is_dir():
                            shutil.rmtree(tmp_file)
                            stats["dirs_removed"] += 1
                        else:
                            tmp_file.unlink(missing_ok=True)
                            stats["files_removed"] += 1
                        job_logger.debug("Rimosso file temp %s", tmp_file)
                    except Exception as exc:
                        job_logger.warning("Errore nel rimuovere %s: %s", tmp_file, exc)
                        stats["errors"] += 1
        except Exception as exc:
            job_logger.warning("Errore durante scan temp dir: %s", exc)
            stats["errors"] += 1
        
        # 3. Rimuovi eventuali .tmp.json residui nella JOBS_DIR
        try:
            tmp_job_file = JOBS_DIR / f".{job_id}.tmp"
            if tmp_job_file.exists():
                tmp_job_file.unlink()
                stats["files_removed"] += 1
                job_logger.debug("Rimosso file temp job %s", tmp_job_file)
        except Exception as exc:
            job_logger.warning("Errore nel rimuovere tmp job file: %s", exc)
            stats["errors"] += 1
            
    except Exception as exc:
        job_logger.error("Errore imprevisto durante cleanup job %s: %s", job_id, exc, exc_info=True)
        stats["errors"] += 1
    
    job_logger.info("Cleanup job %s completato: %s", job_id, 
                   safe_log_dict(stats))
    return stats


def delete_job(job_id: str) -> bool:
    """Elimina un job dalla coda e esegue cleanup delle risorse.
    
    Args:
        job_id: ID del job da eliminare
        
    Returns:
        True se il job è stato eliminato, False se non esisteva
    """
    job = get(job_id)
    if not job:
        return False
    
    project_id = job.get("project_id")
    job_logger = get_logger(f"jobs.delete.{job_id}")
    job_logger.info("Eliminazione job %s (project=%s)", job_id, project_id)
    
    # Esegui cleanup prima di eliminare il record
    cleanup_job_temp_files(job_id, project_id)
    
    # Rimuovi il record del job
    job_path = _path(job_id)
    try:
        if job_path.exists():
            job_path.unlink()
            job_logger.info("Job %s eliminato con successo", job_id)
            return True
    except Exception as exc:
        job_logger.error("Errore nell'eliminare job %s: %s", job_id, exc, exc_info=True)
    
    return False


async def _handle_render(job: dict) -> dict:
    from app.pipeline.orchestrator import run_qa_with_retry, run_stages
    from app.agents import clip_overrides, edit_director, render, sequence, timeline_compiler

    jid = job["job_id"]
    state = state_store.load_state(job["project_id"])
    if not state.get("media"):
        raise ValueError("Nessun media: carica prima foto/video")
    state["_job_id"] = jid
    try:
        set_stage(jid, "sequence", "piano di montaggio")
        state = await run_stages(state, [("sequence", sequence.run),
                                         ("edit_director", edit_director.run),
                                         ("clip_overrides", clip_overrides.run),
                                         ("timeline_compiler", timeline_compiler.run)])
        set_stage(jid, "render", "rendering ffmpeg")
        state = await run_stages(state, [("render", render.run)])
        set_stage(jid, "qa", "controllo qualità")
        state = await run_qa_with_retry(state)
    except Exception:
        state.pop("_job_id", None)
        state_store.save_state(state)  # preserva log failed + errors
        raise
    state.pop("_job_id", None)
    state_store.save_state(state)
    mf = state.get("render_manifest") or {}
    return {"total_sec": mf.get("total_sec"),
            "output_path": (mf.get("output") or {}).get("path"),
            "qa_status": (state.get("qa_report") or {}).get("status")}


async def _handle_drive_import(job: dict) -> dict:
    from app.pipeline.orchestrator import run_stages
    from app.agents import drive_import, intake, normalizer, sequence

    jid = job["job_id"]
    params = job.get("params", {})
    state = state_store.load_state(job["project_id"])
    state["drive_import_request"] = {"file_ids": params.get("file_ids", []),
                                     "folder_ids": params.get("folder_ids", [])}
    state["_job_id"] = jid
    try:
        set_stage(jid, "drive_import", "download da Drive")
        state = await run_stages(state, [("drive_import", drive_import.run),
                                         ("intake", intake.run),
                                         ("normalizer", normalizer.run),
                                         ("sequence", sequence.run)])
    except Exception:
        state.pop("_job_id", None)
        state_store.save_state(state)
        raise
    state.pop("_job_id", None)
    state_store.save_state(state)
    return {"media_count": len(state.get("media", []))}


async def _run_one(job: dict) -> None:
    jid = job["job_id"]
    project_id = job.get("project_id")
    stop = asyncio.Event()
    job_logger = get_logger(f"jobs.{jid}")
    
    job_logger.info("Job %s iniziato: kind=%s, project=%s", 
                    jid, job["kind"], project_id)

    async def heartbeat() -> None:
        """Riversa frazione/nota dal registro nel record ogni 2s."""
        while not stop.is_set():
            await asyncio.sleep(2)
            lvl = prog.peek(jid)
            if lvl is None:
                continue
            cur = get(jid)
            if cur is None or cur.get("status") != "running":
                continue
            cur["progress"] = {"fraction": lvl[0], "note": lvl[1],
                               "stage": cur["progress"].get("stage", "")}
            _touch(cur)

    beat = asyncio.create_task(heartbeat())
    cleanup_done = False
    try:
        if job["kind"] == "render":
            result = await _handle_render(job)
        elif job["kind"] == "drive_import":
            result = await _handle_drive_import(job)
        else:
            raise ValueError(f"kind sconosciuto: {job['kind']}")
    except Exception as exc:
        job_logger.error("Job %s fallito: %s", jid, exc, exc_info=True)
        cur = get(jid) or job
        cur["status"] = "failed"
        cur["error"] = str(exc)[-1000:]
        try:
            _touch(cur)
        except Exception:
            logger.exception("jobs: impossibile registrare il fallimento di %s", jid)
        
        # Cleanup dopo errore - garantito anche in caso di eccezione
        try:
            cleanup_job_temp_files(jid, project_id, keep_output=False)
            cleanup_done = True
        except Exception as cleanup_exc:
            job_logger.warning("Errore durante cleanup dopo fallimento: %s", cleanup_exc)
        return
    finally:
        stop.set()
        try:
            await beat
        except Exception:
            # L'heartbeat non deve mai mascherare l'esito del job.
            job_logger.exception("jobs: heartbeat di %s terminato con errore", jid)
        
        # Cleanup dopo successo - eseguito solo se non già fatto in caso di errore
        if not cleanup_done:
            try:
                cleanup_job_temp_files(jid, project_id, keep_output=True)
            except Exception as cleanup_exc:
                job_logger.warning("Errore durante cleanup dopo successo: %s", cleanup_exc)
    
    job_logger.info("Job %s completato con successo", jid)
    cur = get(jid) or job
    cur["status"] = "done"
    cur["progress"] = {"fraction": 1.0, "note": "completato", "stage": "done"}
    cur["result"] = result
    _touch(cur)


async def worker_loop(poll_sec: float = 1.0) -> None:
    """Loop infinito del worker (task di lifespan). Un job alla volta, FIFO.

    Non deve mai morire in silenzio: se il worker crollasse, tutti i job
    futuri resterebbero in coda all'infinito senza alcun errore visibile.
    Qualsiasi errore imprevisto viene quindi loggato e il loop continua
    (con backoff) invece di propagare l'eccezione.
    """
    failures = 0
    while True:
        try:
            job = await asyncio.to_thread(_claim)
            if job is None:
                failures = 0
                await asyncio.sleep(poll_sec)
                continue
            failures = 0
            await _run_one(job)
        except asyncio.CancelledError:
            logger.info("Worker loop cancellato (shutdown)")
            raise  # shutdown pulito da lifespan
        except Exception:
            failures += 1
            logger.exception("jobs: errore imprevisto nel worker, continuo")
            await asyncio.sleep(min(30.0, poll_sec * (2 ** min(failures, 5))))
