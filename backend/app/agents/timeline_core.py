"""Modulo centrale per il calcolo deterministico della timeline.

Questo modulo definisce un unico contratto matematico per la timeline,
usato da Edit Director, Clip Overrides, Timeline Compiler, Render e QA.

Regole:
1. Tutte le durate sono quantizzate sulla griglia FPS.
2. total_sec = somma(durata_clip_quantizzate) - somma(crossfade_quantizzati)
3. Per ogni coppia di clip: previous.transition_out == next.transition_in
4. Prima clip: transition_in = 0
5. Ultima clip: transition_out = 0
6. Cut: transizione = 0
7. Crossfade: sottrae esattamente la durata del crossfade dal totale
8. start_sec_in_final_video calcolato dallo stesso modello temporale
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TimelineEntry:
    """Voce della timeline calcolata."""
    media_id: str
    duration_sec: float  # durata quantizzata della clip
    transition_in: float  # durata transizione in ingresso (quantizzata)
    transition_out: float  # durata transizione in uscita (quantizzata)
    start_sec: float  # start quantizzato nel video finale
    frames: int  # numero di frame della clip


def quantize_to_fps(sec: float, fps: int) -> float:
    """Quantizza un valore in secondi alla griglia FPS."""
    if sec <= 0:
        return 0.0
    frames = round(sec * fps)
    return round(frames / fps, 6)


def compute_timeline(
    edl: list[dict[str, Any]],
    fps: int = 30,
    apply_transitions: bool = True,
) -> tuple[list[TimelineEntry], float]:
    """Calcola la timeline finale a partire dall'EDL.
    
    Questa è la FUNZIONE DI VERITÀ per tutti i calcoli temporali.
    
    Args:
        edl: Edit Decision List con voci contenenti:
            - media_id: identificativo del media
            - duration_sec: durata dichiarata della clip
            - transition_in: durata transizione in ingresso
            - transition_out: durata transizione in uscita
            - start_sec_in_final_video: start (verrà ricalcolato)
        fps: frame rate per la quantizzazione
        apply_transitions: se False, tratta tutte le transizioni come cut
        
    Returns:
        Tuple di:
        - lista di TimelineEntry con valori quantizzati e coerenti
        - total_sec: durata totale del video finale
        
    La funzione garantisce:
        - total_sec = somma(duration_sec) - somma(transition_in per clip > 0)
        - start_sec[i] = start_sec[i-1] + duration_sec[i-1] - transition_in[i-1]
        - transition_out[i] == transition_in[i+1] per tutte le coppie
        - transition_in[0] = 0
        - transition_out[-1] = 0
    """
    if not edl:
        return [], 0.0
    
    n = len(edl)
    entries: list[TimelineEntry] = []
    
    # Passo 1: quantizza tutte le durate e transizioni
    for i, entry in enumerate(edl):
        duration_raw = float(entry.get("duration_sec", 0.0))
        t_in_raw = float(entry.get("transition_in", 0.0))
        t_out_raw = float(entry.get("transition_out", 0.0))
        
        # Quantizza sulla griglia FPS
        duration_q = quantize_to_fps(duration_raw, fps)
        
        if apply_transitions:
            t_in_q = quantize_to_fps(t_in_raw, fps)
            t_out_q = quantize_to_fps(t_out_raw, fps)
        else:
            t_in_q = 0.0
            t_out_q = 0.0
        
        # Calcola numero di frame
        frames = max(1, round(duration_q * fps))
        duration_final = round(frames / fps, 6)
        
        entries.append(TimelineEntry(
            media_id=str(entry.get("media_id", f"unknown_{i}")),
            duration_sec=duration_final,
            transition_in=t_in_q,
            transition_out=t_out_q,
            start_sec=0.0,  # verrà calcolato nel passo 2
            frames=frames,
        ))
    
    # Passo 2: applica regole di coerenza delle transizioni
    # Prima clip deve avere transition_in = 0
    if entries:
        entries[0].transition_in = 0.0
    
    # Ultima clip deve avere transition_out = 0
    if entries:
        entries[-1].transition_out = 0.0
    
    # Coerenza tra clip adiacenti: transition_out[i] == transition_in[i+1]
    # Usiamo transition_out della clip precedente come riferimento
    for i in range(1, n):
        # La transizione in ingresso della clip i deve essere uguale
        # alla transizione in uscita della clip i-1
        entries[i].transition_in = entries[i - 1].transition_out
    
    # Passo 3: calcola gli start cumulativi
    current_start = 0.0
    for i, entry in enumerate(entries):
        entry.start_sec = round(current_start, 6)
        if i < n - 1:
            # Avanza di: durata clip corrente - transizione in uscita
            current_start += entry.duration_sec - entry.transition_out
    
    # Passo 4: calcola il totale
    # total_sec = somma(durate) - somma(transizioni)
    total_duration = sum(e.duration_sec for e in entries)
    total_transitions = sum(e.transition_in for e in entries[1:])  # skip first (always 0)
    total_sec = round(total_duration - total_transitions, 6)
    
    return entries, total_sec


def validate_timeline(
    entries: list[TimelineEntry],
    total_sec: float,
    fps: int = 30,
) -> list[str]:
    """Valida la timeline rispetto al contratto matematico.
    
    Returns:
        Lista di messaggi di errore (vuota se tutto ok).
    """
    errors: list[str] = []
    
    if not entries:
        if total_sec != 0.0:
            errors.append(f"Timeline vuota ma total_sec={total_sec}")
        return errors
    
    n = len(entries)
    
    # Controllo 1: prima clip transition_in == 0
    if entries[0].transition_in != 0.0:
        errors.append(f"Prima clip ha transition_in={entries[0].transition_in} (deve essere 0)")
    
    # Controllo 2: ultima clip transition_out == 0
    if entries[-1].transition_out != 0.0:
        errors.append(f"Ultima clip ha transition_out={entries[-1].transition_out} (deve essere 0)")
    
    # Controllo 3: coerenza transition_out/transition_in tra clip adiacenti
    for i in range(1, n):
        t_out_prev = entries[i - 1].transition_out
        t_in_curr = entries[i].transition_in
        if abs(t_out_prev - t_in_curr) > 1e-6:
            errors.append(
                f"Transizione incoerente tra clip {i-1} e {i}: "
                f"transition_out={t_out_prev} != transition_in={t_in_curr}"
            )
    
    # Controllo 4: verifica calcolo start
    for i in range(1, n):
        expected_start = entries[i - 1].start_sec + entries[i - 1].duration_sec - entries[i - 1].transition_out
        if abs(entries[i].start_sec - expected_start) > 1e-6:
            errors.append(
                f"Clip {i}: start={entries[i].start_sec} ma atteso {expected_start}"
            )
    
    # Controllo 5: verifica total_sec
    expected_total = sum(e.duration_sec for e in entries) - sum(e.transition_in for e in entries[1:])
    if abs(total_sec - expected_total) > max(0.05, 1.0 / fps):
        errors.append(
            f"total_sec={total_sec} ma calcolo dà {expected_total} "
            f"(somma_durata={sum(e.duration_sec for e in entries)}, "
            f"somma_transizioni={sum(e.transition_in for e in entries[1:])})"
        )
    
    # Controllo 6: durate positive
    for i, e in enumerate(entries):
        if e.duration_sec <= 0:
            errors.append(f"Clip {i} ha durata non positiva: {e.duration_sec}")
    
    return errors


def edl_to_timeline_entries(
    edl: list[dict[str, Any]],
    computed_entries: list[TimelineEntry],
) -> list[dict[str, Any]]:
    """Aggiorna l'EDL con i valori calcolati dalla timeline.
    
    Restituisce una nuova lista di voci EDL con:
    - start_sec_in_final_video aggiornato
    - duration_sec quantizzata
    - transition_in/transition_out coerenti
    """
    result = []
    for orig, comp in zip(edl, computed_entries):
        new_entry = dict(orig)
        new_entry["start_sec_in_final_video"] = comp.start_sec
        new_entry["duration_sec"] = comp.duration_sec
        new_entry["transition_in"] = comp.transition_in
        new_entry["transition_out"] = comp.transition_out
        result.append(new_entry)
    return result
