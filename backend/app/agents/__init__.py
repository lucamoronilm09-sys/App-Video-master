"""Agenti del grafo AI Video Maker (architettura sez. 4-5).

Ogni agente e' un modulo indipendente con firma:
    run(project_state: dict) -> dict
Lo state JSON e' l'unico canale tra agenti (niente chiamate incrociate):
le catene (upload, edit, render...) vivono nelle route API / orchestratore.
"""
__all__ = [
    "drive_import",
    "intake",
    "normalizer",
    "sequence",
    "audio_analysis",
    "edit_director",
    "clip_overrides",
    "timeline_compiler",
    "render",
    "qa",
]
