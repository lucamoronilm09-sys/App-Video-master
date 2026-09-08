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
import time
from typing import Awaitable, Callable

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

AgentFn = Callable[[dict], Awaitable[dict]]


async def _run_stage(state: dict, name: str, fn: AgentFn) -> dict:
    state["pipeline_log"].append(
        {"stage": name, "status": "running", "ts": time.time()}
    )
    try:
        state = await fn(state)
    except Exception as exc:  # un errore di agente non deve corrompere lo state
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
    non la logica di montaggio."""
    state = project_state

    state = await _run_stage(state, "intake", intake.run)
    state = await _run_stage(state, "normalizer", normalizer.run)

    seq_task = asyncio.create_task(_run_stage(state, "sequence", sequence.run))
    aud_task = asyncio.create_task(
        _run_stage(state, "audio_analysis", audio_analysis.run)
    )
    seq_state, aud_state = await asyncio.gather(seq_task, aud_task)
    # merge: sequence tocca le durate dei media; audio_analysis tocca "audio"
    state = {**seq_state, "audio": aud_state.get("audio", seq_state.get("audio"))}

    state = await _run_stage(state, "edit_director", edit_director.run)
    state = await _run_stage(state, "clip_overrides", clip_overrides.run)
    state = await _run_stage(state, "timeline_compiler", timeline_compiler.run)
    state = await _run_stage(state, "render", render.run)
    state = await run_qa_with_retry(state)
    return state
