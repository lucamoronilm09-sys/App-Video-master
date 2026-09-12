"""Modulo per il rate limiting SlowAPI.

Questo modulo è indipendente e può essere importato da qualsiasi altro modulo
senza creare dipendenze circolari.
"""
from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Il rate limiting resta attivo in development/staging/production.
# Nei test di integrazione disabilitarlo evita che il limite per IP del TestClient
# trasformi una suite deterministica in una sequenza dipendente dall'ordine.
limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("APP_ENV", "development").lower() != "testing",
)
