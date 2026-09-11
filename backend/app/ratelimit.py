"""Modulo per il rate limiting SlowAPI.

Questo modulo è indipendente e può essere importato da qualsiasi altro modulo
senza creare dipendenze circolari.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Istanza globale del Limiter per il rate limiting
limiter = Limiter(key_func=get_remote_address)
