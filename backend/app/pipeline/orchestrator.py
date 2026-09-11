"""Esecutore del DAG degli agenti (architettura sez. 4).

Fasi (rispettano le dipendenze del grafo):
    0 Intake
    1 Normalizer
    2a Sequence  ||  2b Audio Analysis   (paralleli, dipendenze disgiunte)
    3 Edit Director                      (attende entrambi)
    4 Timeline Compiler
    5 Render
    6 QA (+ loop condizionale a 3 in M6, max 1 retry)

Ogni fase scrive nel Project State e nel "pipeline_log" (per la UI di
avanzamento M8). Il rendering resta idempotente: stesso input, stesso video.
"""
from __future__ import annotations

import asyncio
import copy
import time
from typing import Awaitable, Callable

import logging

from app.agents import (
    audio_analysis,
    edit_director,
    clip_overrides,
    intake,
    normalizer,
    qa,
    render,
    sequence,
    timeline_compiler,
)

logger = logging.getLogger(__name__)

AgentFn = Callable[[dict], Awaitable[dict]]


def _copy_for_parallel_task(state: dict, extra_keys: dict | None = None) -> dict:
    """Crea una copia isolata dello stato per un task parallelo.
    
    Copia solo le chiavi necessarie per l'esecuzione dell'agente,
    mantenendo separati pipeline_log e errors per evitare race condition.
    """
    # Copia profonda delle chiavi critiche che l'agente potrebbe modificare
    task_state = {
        "media": copy.deepcopy(state.get("media", [])),
        "timeline": copy.deepcopy(state.get("timeline", [])),
        "project_id": state.get("project_id"),
        "project_dir": state.get("project_dir"),
    }
    
    # Aggiungi chiavi specifiche se fornite
    if extra_keys:
        for key, value in extra_keys.items():
            if isinstance(value, (dict, list)):
                task_state[key] = copy.deepcopy(value)
            else:
                task_state[key] = value
    
    # Inizializza strutture separate per questo task
    task_state["pipeline_log"] = []
    task_state["errors"] = []
    
    return task_state


def _merge_parallel_results(base_state: dict, seq_result: dict, aud_result: dict) -> dict:
    """Unisce i risultati di task paralleli in modo deterministico.
    
    Preserva:
    - Tutti gli entry di pipeline_log da entrambi i task
    - Tutti gli errori da entrambi i task
    - I dati specifici di ciascun task (es. audio da aud_result)
    - Lo stato base aggiornato da sequence
    """
    # Parti dallo stato base aggiornato da sequence
    merged = copy.deepcopy(seq_result)
    
    # Unisci i pipeline_log mantenendo l'ordine temporale
    merged["pipeline_log"] = (
        seq_result.get("pipeline_log", []) + aud_result.get("pipeline_log", [])
    )
    # Ordina per timestamp per garantire consistenza
    merged["pipeline_log"].sort(key=lambda x: x.get("ts", 0))
    
    # Unisci tutti gli errori da entrambi i task
    merged["errors"] = (
        seq_result.get("errors", []) + aud_result.get("errors", [])
    )
    
    # Aggiungi i dati specifici di audio_analysis
    if "audio" in aud_result:
        merged["audio"] = aud_result["audio"]
    elif "audio" in seq_result:
        # Mantieni audio da seq_result se aud_result non ne ha prodotto
        pass
    else:
        # Assicurati che la chiave esista anche se vuota
        merged["audio"] = None
    
    return merged


async def _run_stage(state: dict, name: str, fn: AgentFn) -> dict:
    stage_logger = logging.getLogger(f"pipeline.{name}")
    stage_logger.info("Stage %s avviato", name)
    state["pipeline_log"].append(
        {"stage": name, "status": "running", "ts": time.time()}
    )
    try:
        state = await fn(state)
        stage_logger.info("Stage %s completato", name)
    except Exception as exc:  # un errore di agente non deve corrompere lo state
        stage_logger.error("Stage %s fallito: %s", name, exc, exc_info=True)
        state["errors"].append({"stage": name, "message": str(exc)})
        state["pipeline_log"].append(
            {"stage": name, "status": "failed", "ts": time.time()}
        )
        raise
    state["pipeline_log"].append(
        {"stage": name, "status": "done", "ts": time.time()}
    )
    return state


async def run_stages(state: dict, stages: list[tuple[str, AgentFn]]) -> dict:
    """Esecutore sequenziale condiviso (anche dalle route API)."""
    for name, fn in stages:
        state = await _run_stage(state, name, fn)
    return state


QA_MAX_RETRIES = 1  # un solo ritorno QA -> Edit Director, poi ci si ferma


async def run_qa_with_retry(state: dict) -> dict:
    """QA + feedback loop condizionale (architettura sez. 6, M6).

    Se il verdetto e' rejected e almeno un'issue e' di competenza creativa
    (route_to == edit_director), ripianifica una volta con qa_feedback
    (fit_total al totale del manifest) e riverifica. Verdetti tecnici
    (timeline_compiler) non ritentano: indicano bug, non scelte.
    """
    for attempt in range(QA_MAX_RETRIES + 1):
        state = await run_stages(state, [("qa", qa.run)])
        report = state.get("qa_report") or {}
        if report.get("status") != "rejected" or attempt >= QA_MAX_RETRIES:
            break
        creative = [i for i in report.get("issues", [])
                    if i.get("route_to") == "edit_director"]
        if not creative:
            break
        state["qa_attempts"] = attempt + 1
        total = (state.get("render_manifest") or {}).get("total_sec", 0)
        state["qa_feedback"] = [{"check": i["check"], "message": i["message"],
                                 "type": "fit_total", "total_sec": total}
                                for i in creative]
        state = await run_stages(state, [("edit_director", edit_director.run),
                                         ("clip_overrides", clip_overrides.run),
                                         ("timeline_compiler", timeline_compiler.run),
                                         ("render", render.run)])
    return state


async def run_pipeline(project_state: dict) -> dict:
    """Esegue il grafo completo. In M0 tutti gli agenti sono passthrough,
    quindi e' un drill di integrazione del grafo: verifica wiring e log,
    non la logica di montaggio.
    
    Correzione race condition: i task paralleli (sequence e audio_analysis)
    ricevono copie isolate dello stato per evitare modifiche concorrenti
    allo stesso oggetto mutabile. I risultati vengono uniti deterministicamente.
    """
    state = project_state
    
    # Inizializza strutture condivise se non esistono
    if "pipeline_log" not in state:
        state["pipeline_log"] = []
    if "errors" not in state:
        state["errors"] = []

    state = await _run_stage(state, "intake", intake.run)
    state = await _run_stage(state, "normalizer", normalizer.run)

    # Esecuzione parallela con stati isolati per evitare race condition
    seq_state_input = _copy_for_parallel_task(state)
    aud_state_input = _copy_for_parallel_task(state)
    
    seq_task = asyncio.create_task(_run_stage(seq_state_input, "sequence", sequence.run))
    aud_task = asyncio.create_task(
        _run_stage(aud_state_input, "audio_analysis", audio_analysis.run)
    )
    seq_result, aud_result = await asyncio.gather(seq_task, aud_task)
    
    # Merge deterministico dei risultati paralleli
    state = _merge_parallel_results(state, seq_result, aud_result)

    state = await _run_stage(state, "edit_director", edit_director.run)
    state = await _run_stage(state, "clip_overrides", clip_overrides.run)
    state = await _run_stage(state, "timeline_compiler", timeline_compiler.run)
    state = await _run_stage(state, "render", render.run)
    state = await run_qa_with_retry(state)
    return state
