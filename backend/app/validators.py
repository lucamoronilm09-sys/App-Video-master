"""Validazione centralizzata degli identificatori di progetto.

Questo modulo previene vulnerabilità di path traversal validando project_id
alla fonte, prima di qualsiasi operazione su filesystem o database.

Formato valido: stringa esadecimale di esattamente 8 caratteri (es. "a1b2c3d4").
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

PROJECT_ID_PATTERN = re.compile(r"^[0-9a-f]{8}$")


class InvalidProjectIDError(ValueError, FileNotFoundError):
    """Errore per ID malformati, trattabile anche come risorsa inesistente."""
    pass


def validate_project_id(project_id: str) -> str:
    """Valida un project_id e restituisce il valore se valido."""
    if not isinstance(project_id, str):
        raise InvalidProjectIDError(
            f"project_id deve essere una stringa, ricevuto {type(project_id).__name__}"
        )
    if ".." in project_id:
        raise InvalidProjectIDError("project_id non può contenere '..'")
    if "/" in project_id or "\\" in project_id:
        raise InvalidProjectIDError("project_id non può contenere separatori di percorso")
    if project_id.startswith("/") or project_id.startswith("."):
        raise InvalidProjectIDError("project_id non può essere un path assoluto o relativo")
    if not PROJECT_ID_PATTERN.match(project_id):
        raise InvalidProjectIDError(
            f"project_id deve essere una stringa esadecimale di 8 caratteri (es. 'a1b2c3d4'), "
            f"ricevuto: '{project_id}'"
        )
    return project_id


def validate_project_id_or_404(project_id: str) -> str:
    """Valida un project_id e solleva HTTPException 400 se non valido."""
    try:
        return validate_project_id(project_id)
    except InvalidProjectIDError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


def is_safe_project_path(base_dir: Path, target_path: Path) -> bool:
    """Verifica che un path risolto sia contenuto nella directory base."""
    try:
        base_resolved = base_dir.resolve(strict=True)
        target_resolved = target_path.resolve()
        _ = target_resolved.relative_to(base_resolved)
        return True
    except (ValueError, OSError, FileNotFoundError):
        return False
