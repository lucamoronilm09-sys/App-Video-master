"""Agente 1: Media Normalizer Agent (architettura sez. 5).

Regole di inquadratura nel frame 16:9 finale:
- Landscape / Square -> fit_mode = "cover" (riempie il frame, crop minimo se serve).
  background_fill = None (non serve sfondo, il frame e' pieno).
- Portrait -> fit_mode = "contain" (centrato orizzontalmente e verticalmente,
  MAI croppato o deformato oltre l'aspect ratio originale).
  background_fill = "blur" (di default) o "solid_color" se indicato dall'utente
  (nel singolo media o in output_spec).

Preserva l'aspect ratio originale del soggetto in primo piano.
Normalizza inoltre gli order_index se non contigui.
"""
from __future__ import annotations

from typing import Any


async def run(project_state: dict) -> dict:
    media_list: list[dict[str, Any]] = project_state.get("media", [])
    if not media_list:
        return project_state

    default_fill = project_state.get("output_spec", {}).get("background_fill", "blur")
    if default_fill not in ("blur", "solid_color"):
        default_fill = "blur"

    # Ordina per order_index se gia' assegnato, poi riassegna contiguo 0..N-1
    # per garantire coerenza
    media_list.sort(key=lambda m: m.get("order_index", 0))

    for idx, item in enumerate(media_list):
        item["order_index"] = idx
        orientation = item.get("orientation")

        # Se non determinato, ricava da width e height
        if not orientation:
            w = item.get("width", 0)
            h = item.get("height", 0)
            if w > h:
                orientation = "landscape"
            elif w == h and w > 0:
                orientation = "square"
            else:
                orientation = "portrait"
            item["orientation"] = orientation

        if orientation in ("landscape", "square"):
            item["fit_mode"] = "cover"
            # Niente sfondo visibile perche' l'immagine copre l'intero frame
            item["background_fill"] = None
        else:  # portrait
            item["fit_mode"] = "contain"
            # Se l'utente non ha specificato una preferenza sul singolo media,
            # usiamo quella definita a livello di progetto in output_spec (default "blur")
            user_fill = item.get("background_fill")
            if user_fill in ("blur", "solid_color"):
                item["background_fill"] = user_fill
            else:
                item["background_fill"] = default_fill

    project_state["media"] = media_list
    return project_state
