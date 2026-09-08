"""Agente -1b: Google Drive Import (architettura sez. 5, M7).

Legge state["drive_import_request"] = {file_ids, folder_ids}: espande la
selezione (cartelle ricorsive), scarica i media in parallelo in
data/projects/<id>/media/ (uuid + nome originale preservato) e li mette in
media_staging con source="google_drive" + drive_file_id. I file non
supportati vanno in errors[] senza bloccare gli altri. Non modifica Drive,
non tocca i metadata (quelli li fa l'Intake a valle, come da grafo).
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from pathlib import Path
from typing import Any

from app.jobs import progress as prog
from app.pipeline import state as state_store
from app.services import drive_client as dc

logger = logging.getLogger(__name__)


def _retry_wait(attempt: int) -> float:
    """Backoff esponenziale con jitter tra i tentativi (2s, 4s, 8s, ...)."""
    return dc.DOWNLOAD_RETRY_BASE_SEC * (2 ** (attempt - 1)) + random.uniform(0, 0.5)


async def _download_one(service_factory, meta: dict, media_dir: Path,
                        sem: asyncio.Semaphore) -> dict:
    """Scarica un file con un service Drive DEDICATO a questo thread.

    service_factory (tipicamente dc.get_drive_service) viene chiamata DENTRO
    il worker thread: ogni download ha il proprio httplib2.Http. Condividere
    un unico service tra i download paralleli corrompe i trasferimenti
    (httplib2.Http riusa le connessioni keep-alive in un dict condiviso SENZA
    lock: i thread si rubano le risposte a vicenda -> IncompleteRead e
    SSL: WRONG_VERSION_NUMBER casuali, mentre l'elenco file - sequenziale -
    funziona sempre).
    """
    name = f"{uuid.uuid4().hex[:8]}_{dc.sanitize_filename(meta.get('name') or 'file')}"
    dest = media_dir / name
    label = meta.get("name") or meta["id"]

    def _do() -> int:
        service = service_factory()
        return dc.download_file(service, meta["id"], dest)

    async with sem:
        for attempt in range(1, dc.DOWNLOAD_MAX_ATTEMPTS + 1):
            try:
                # Timeout per-file: un download piantato (rete lenta, stall) non
                # deve bloccare l'intero import all'infinito. Niente retry sul
                # timeout: un secondo tentativo parallelo raddoppierebbe il carico.
                await asyncio.wait_for(asyncio.to_thread(_do),
                                       timeout=dc.DOWNLOAD_TIMEOUT_SEC)
                break
            except (asyncio.TimeoutError, TimeoutError):
                logger.warning("drive_import: '%s' timeout dopo %ss",
                               label, dc.DOWNLOAD_TIMEOUT_SEC)
                return {"error": {"stage": "drive_import",
                                  "message": f"{label}: timeout dopo "
                                             f"{dc.DOWNLOAD_TIMEOUT_SEC}s — connessione lenta "
                                             f"o file molto grande, riprova"}}
            except Exception as exc:
                transient = dc.is_transient_error(exc)
                last = attempt >= dc.DOWNLOAD_MAX_ATTEMPTS
                if transient and not last:
                    wait = _retry_wait(attempt)
                    logger.warning("drive_import: '%s' tentativo %d/%d fallito "
                                   "(%s), riprovo tra %.1fs",
                                   label, attempt, dc.DOWNLOAD_MAX_ATTEMPTS, exc, wait)
                    await asyncio.sleep(wait)
                    continue
                # DriveDownloadError ha già un messaggio chiaro: non riprefissarlo
                # (evita "download fallito: ... download fallito: ...").
                msg = str(exc) if isinstance(exc, dc.DriveDownloadError) else (
                    f"{label}: download fallito: {exc}")
                if transient:
                    msg += f" (dopo {dc.DOWNLOAD_MAX_ATTEMPTS} tentativi)"
                    logger.warning("drive_import: '%s' fallito definitivamente: %s",
                                   label, msg)
                else:
                    logger.warning("drive_import: '%s' fallito: %s", label, msg)
                return {"error": {"stage": "drive_import", "message": msg}}
    logger.info("drive_import: '%s' pronto", label)
    return {"path": str(dest), "source": "google_drive", "drive_file_id": meta["id"]}


async def run(project_state: dict) -> dict:
    req = project_state.pop("drive_import_request", None)
    if not req:
        return project_state

    try:
        service = await asyncio.wait_for(
            asyncio.to_thread(dc.get_drive_service),
            timeout=dc.SERVICE_TIMEOUT_SEC)
    except (asyncio.TimeoutError, TimeoutError):
        msg = (f"connessione a Google Drive scaduta dopo {dc.SERVICE_TIMEOUT_SEC}s "
               f"— controlla la rete e riprova")
        logger.warning("drive_import: %s", msg)
        project_state.setdefault("errors", []).append(
            {"stage": "drive_import", "message": msg})
        raise TimeoutError(msg) from None
    except RuntimeError as exc:
        project_state.setdefault("errors", []).append(
            {"stage": "drive_import", "message": str(exc)})
        raise

    file_ids = list(req.get("file_ids", []))
    folder_ids = list(req.get("folder_ids", []))
    if not file_ids and not folder_ids:
        raise ValueError("selezione vuota: indica file_ids e/o folder_ids")

    try:
        media, skipped = await asyncio.wait_for(
            asyncio.to_thread(dc.expand_selection, service, file_ids, folder_ids),
            timeout=dc.EXPAND_TIMEOUT_SEC)
    except (asyncio.TimeoutError, TimeoutError):
        msg = (f"esplorazione Drive scaduta dopo {dc.EXPAND_TIMEOUT_SEC}s "
               f"(cartella troppo grande o rete lenta) — prova con meno file")
        logger.warning("drive_import: %s", msg)
        project_state.setdefault("errors", []).append(
            {"stage": "drive_import", "message": msg})
        raise TimeoutError(msg) from None
    errors = project_state.setdefault("errors", [])
    for s in skipped:
        label = s.get("name") or s.get("id") or "?"
        errors.append({"stage": "drive_import", "message": f"{label}: {s.get('reason')}"})
    if not media:
        raise ValueError("nessun file immagine/video nella selezione")
    logger.info("drive_import: avvio download di %d file (timeout %ss/file)",
                len(media), dc.DOWNLOAD_TIMEOUT_SEC)

    media_dir = state_store.media_dir(project_state["project_id"])
    media_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(dc.DOWNLOAD_WORKERS)
    job_id = project_state.get("_job_id")

    # Factory (non il service condiviso!): ogni download costruisce il proprio
    # service nel suo thread, vedi _download_one. In produzione è
    # dc.get_drive_service (cred nuovi + Http nuovo a ogni chiamata).
    service_factory = dc.get_drive_service

    async def _indexed(idx: int, meta: dict) -> tuple[int, dict]:
        return idx, await _download_one(service_factory, meta, media_dir, sem)

    # as_completed per il progress, ma staging in ordine deterministico (indice)
    results: list = [None] * len(media)
    done_n = 0
    for coro in asyncio.as_completed([_indexed(i, m) for i, m in enumerate(media)]):
        idx, r = await coro
        results[idx] = r
        done_n += 1
        prog.set(job_id, done_n / len(media), f"{done_n}/{len(media)} file")

    staging = project_state.setdefault("media_staging", [])
    failed = 0
    for r in results:
        if "error" in r:
            errors.append(r["error"])
            failed += 1
        else:
            staging.append(r)
    logger.info("drive_import: %d ok, %d falliti su %d file",
                len(results) - failed, failed, len(results))
    if not staging:
        raise ValueError("tutti i download sono falliti")
    return project_state
