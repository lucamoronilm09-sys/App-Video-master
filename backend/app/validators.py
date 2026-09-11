"""Validazione centralizzata degli identificatori di progetto.

Questo modulo previene vulnerabilità di path traversal validando project_id
alla fonte, prima di qualsiasi operazione su filesystem o database.

Formato valido: stringa esadecimale di esattamente 8 caratteri (es. "a1b2c3d4").
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

# Regex per validare project_id: esattamente 8 caratteri esadecimali lowercase
# Questo corrisponde al formato generato da uuid.uuid4().hex[:8] in state.py
PROJECT_ID_PATTERN = re.compile(r"^[0-9a-f]{8}$")


class InvalidProjectIDError(ValueError):
    """Eccezione sollevata quando un project_id non è valido."""
    pass


def validate_project_id(project_id: str) -> str:
    """Valida un project_id e restituisce il valore se valido.
    
    Args:
        project_id: L'identificatore del progetto da validare.
        
    Returns:
        Il project_id validato (stesso valore in input se valido).
        
    Raises:
        InvalidProjectIDError: Se il project_id non è valido.
        HTTPException: Se usato in contesto API con status 400.
    """
    if not isinstance(project_id, str):
        raise InvalidProjectIDError(f"project_id deve essere una stringa, ricevuto {type(project_id).__name__}")
    
    # Rifiuta immediatamente pattern sospetti di path traversal
    if ".." in project_id:
        raise InvalidProjectIDError("project_id non può contenere '..'")
    
    if "/" in project_id or "\\" in project_id:
        raise InvalidProjectIDError("project_id non può contenere separatori di percorso")
    
    # Rifiuta path assoluti o riferimenti alla directory corrente
    if project_id.startswith("/") or project_id.startswith("."):
        raise InvalidProjectIDError("project_id non può essere un path assoluto o relativo")
    
    # Verifica il formato esadecimale di 8 caratteri
    if not PROJECT_ID_PATTERN.match(project_id):
        raise InvalidProjectIDError(
            f"project_id deve essere una stringa esadecimale di 8 caratteri (es. 'a1b2c3d4'), "
            f"ricevuto: '{project_id}'"
        )
    
    return project_id


def validate_project_id_or_404(project_id: str) -> str:
    """Valida un project_id e solleva HTTPException 400 se non valido.
    
    Da usare negli endpoint API per restituire immediatamente un errore 400
    per project_id malformati, prima di qualsiasi altra elaborazione.
    
    Args:
        project_id: L'identificatore del progetto da validare.
        
    Returns:
        Il project_id validato.
        
    Raises:
        HTTPException: Con status 400 e dettaglio descrittivo.
    """
    try:
        return validate_project_id(project_id)
    except InvalidProjectIDError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


def is_safe_project_path(base_dir: Path, target_path: Path) -> bool:
    """Verifica che un path risolto sia contenuto nella directory base.
    
    SECURITY: controllo aggiuntivo anti path-traversal che verifica che
    il path risolto sia effettivamente contenuto nella directory attesa.
    
    Args:
        base_dir: La directory base (es. PROJECTS_DIR o project_dir).
        target_path: Il path da verificare.
        
    Returns:
        True se il path è sicuro, False altrimenti.
    """
    try:
        base_resolved = base_dir.resolve(strict=True)
        target_resolved = target_path.resolve()
        # Verifica che target sia dentro base
        _ = target_resolved.relative_to(base_resolved)
        return True
    except (ValueError, OSError, FileNotFoundError):
        return False
