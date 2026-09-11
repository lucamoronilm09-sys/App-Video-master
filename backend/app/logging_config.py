"""Configurazione centralizzata del logging per il backend AI Video Maker.

Utilizzo:
    from app.logging_config import get_logger
    
    logger = get_logger(__name__)
    logger.info("Messaggio informativo")
    logger.warning("Attenzione")
    logger.error("Errore con traceback", exc_info=True)

Caratteristiche:
- Livello configurabile tramite LOG_LEVEL (default: INFO)
- Timestamp ISO8601
- Nome del logger/modulo
- Request ID (se presente nel context)
- Formattazione coerente per INFO/WARNING/ERROR
- No log di dati sensibili (API key, token, credenziali)
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from contextvars import ContextVar
from typing import Optional

# Context variable per request_id (popolato dal middleware HTTP)
_request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


class RequestIDFilter(logging.Filter):
    """Filtro che aggiunge request_id ai record di log."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


def get_log_level() -> int:
    """Ottiene il livello di logging dalla variabile d'ambiente LOG_LEVEL.
    
    Valori validi: DEBUG, INFO, WARNING, ERROR, CRITICAL
    Default: INFO
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper().strip()
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(level_name, logging.INFO)


def setup_logging() -> None:
    """Configura il logging root per l'applicazione.
    
    Da chiamare una volta all'avvio dell'applicazione (es. in main.py).
    """
    level = get_log_level()
    
    # Formato: timestamp | livello | logger | request_id | messaggio
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(request_id)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        style="%",
    )
    
    # Handler stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIDFilter())
    
    # Configura root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Rimuovi handler esistenti per evitare duplicati
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    
    # Disabilita log troppo verbosi da librerie terze
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Ottiene un logger configurato per il modulo specificato.
    
    Args:
        name: Tipicamente __name__ del modulo chiamante
        
    Returns:
        Logger configurato con il formato centralizzato
    """
    return logging.getLogger(name)


def set_request_id(request_id: Optional[str]) -> None:
    """Imposta il request_id per il context corrente.
    
    Da usare nel middleware HTTP per tracciare le richieste.
    
    Args:
        request_id: ID univoco della richiesta (o None per resettare)
    """
    _request_id_ctx.set(request_id)


def get_request_id() -> Optional[str]:
    """Ottiene il request_id corrente."""
    return _request_id_ctx.get()


def redact_sensitive(value: str) -> str:
    """Maschera valori sensibili per il logging.
    
    Mostra solo i primi 4 e ultimi 2 caratteri se la stringa è lunga abbastanza.
    
    Args:
        value: Stringa da mascherare
        
    Returns:
        Stringa mascherata o "[REDACTED]" se troppo corta
    """
    if not value or len(value) < 8:
        return "[REDACTED]"
    return f"{value[:4]}...{value[-2:]}"


def safe_log_dict(data: dict, sensitive_keys: tuple[str, ...] = (
    "api_key", "token", "secret", "password", "credential", "authorization",
    "access_token", "refresh_token", "client_secret", "private_key"
)) -> dict:
    """Prepara un dizionario per il logging, mascherando chiavi sensibili.
    
    Args:
        data: Dizionario da preparare
        sensitive_keys: Tuple di nomi di chiavi da mascherare (case-insensitive)
        
    Returns:
        Nuova copia del dizionario con valori sensibili mascherati
    """
    result = {}
    for key, value in data.items():
        if any(sensitive.lower() in key.lower() for sensitive in sensitive_keys):
            result[key] = redact_sensitive(str(value)) if isinstance(value, str) else "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = safe_log_dict(value, sensitive_keys)
        else:
            result[key] = value
    return result
