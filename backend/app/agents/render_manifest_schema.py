"""Schema contrattuale del RenderManifest.

Questo modulo definisce il contratto unico utilizzato da:
- Timeline Compiler (produttore)
- Render (consumer + updater)
- QA (validatore)
- API (serializzazione)
- Frontend (TypeScript types)
- Test (validazione schema)

REGOLE:
1. Tutti i dati necessari al render devono essere presenti nel manifest.
2. Nessun consumer deve ricostruire informazioni fondamentali autonomamente.
3. total_sec deriva dalla timeline quantizzata.
4. output.duration_sec deve essere coerente con il file verificato.
5. filter_complex_script è il comando realmente usato (filter_complex deprecato ma mantenuto per compatibilità).
6. vcodec deve essere sempre presente nell'output.
7. MANIFEST_VERSION aggiornato quando il contratto cambia.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict


MANIFEST_VERSION = 7
"""Versione corrente del contratto RenderManifest.

Storico versioni:
- v1: struttura iniziale
- v2: aggiunto filter_complex_script
- v3: segments con duration_sec quantizzato
- v4: transitions con offset_sec
- v5: audio.tracks array
- v6: output con resolution, fps, vcodec separati
- v7: schema definitivo con tutti i campi required + validation
"""


class InputEntry(TypedDict, total=False):
    """Voce dell'array inputs."""
    index: int
    path: str
    kind: Literal["video", "photo", "audio"]
    audio_track: Optional[int]  # Solo per input audio


class SegmentEntry(TypedDict, total=False):
    """Voce dell'array segments."""
    media_id: str
    input_index: int
    kind: Literal["video", "photo"]
    fit: Literal["cover", "contain"]
    label: str  # etichetta FFmpeg (es. "v0", "v1")
    filter: str  # filtro applicato a questo segmento
    duration_sec: float  # durata quantizzata alla FPS


class TransitionEntry(TypedDict, total=False):
    """Voce dell'array transitions."""
    index: int  # indice nella sequenza (1..N-1)
    from_segment: int  # indice segmento di provenienza
    to_segment: int  # indice segmento di destinazione
    duration_sec: float  # 0.0 = taglio netto, >0 = dissolvenza
    offset_sec: float  # offset temporale per xfade
    cut: bool  # True se transition_sec == 0


class AudioTrackInfo(TypedDict, total=False):
    """Informazioni su una traccia audio."""
    path: Optional[str]
    name: Optional[str]
    duration_sec: float


class AudioBlock(TypedDict, total=False):
    """Blocco audio nel manifest."""
    tracks: list[AudioTrackInfo]


class OutputSpec(TypedDict, total=False):
    """Specifiche output video."""
    path: str
    resolution: str  # "WxH" es. "1920x1080"
    fps: int
    vcodec: str  # "libx264" o "libx265"
    preset: str  # es. "medium"
    crf: int  # es. 18 per h264
    duration_sec: float  # durata verificata post-render
    size_bytes: int  # dimensione file post-render
    rendered_at: Optional[float]  # timestamp completamento


class ValidationReport(TypedDict, total=False):
    """Report di validazione post-render."""
    codec: str
    width: int
    height: int
    duration: float
    size_bytes: int


class RenderManifest(TypedDict, total=False):
    """Schema completo del RenderManifest.
    
    CAMPI OBBLIGATORI (sempre presenti se status != null):
    - version: versione dello schema
    - status: stato del render
    - inputs: lista input FFmpeg
    - segments: lista segmenti video
    - transitions: lista transizioni
    - filter_complex_script: percorso file script FFmpeg
    - args: argomenti CLI FFmpeg
    - total_sec: durata totale timeline quantizzata
    - output: specifiche output
    
    CAMPI CONDIZIONALI:
    - filter_complex: stringa inline (deprecated, mantenuto per compatibilità)
    - audio: presente solo se tracce audio configurate
    - validation: presente solo dopo render completato (status="done")
    """
    # Identificazione
    version: int  # MANIFEST_VERSION
    
    # Stato
    status: Literal["ready", "running", "done", "failed"]
    
    # Input FFmpeg
    inputs: list[InputEntry]
    
    # Segmenti video (uno per clip nella timeline)
    segments: list[SegmentEntry]
    
    # Transizioni tra segmenti
    transitions: list[TransitionEntry]
    
    # Filtro FFmpeg
    filter_complex: str  # deprecated: mantenuto per compatibilità backward
    filter_complex_script: str  # percorso file .txt con script FFmpeg
    
    # Comando FFmpeg
    args: list[str]
    
    # Durata totale (dalla timeline quantizzata)
    total_sec: float
    
    # Specifiche output
    output: OutputSpec
    
    # Audio (opzionale: assente se nessun audio)
    audio: Optional[AudioBlock]
    
    # Metadata aggiuntivi
    fps: int
    resolution: str  # ridondante con output.resolution, mantenuto per compatibilità
    vcodec: str  # ridondante con output.vcodec, mantenuto per compatibilità
    source_video_audio: Literal["muted", "mixed"]  # stato audio originale
    
    # Validazione (solo post-render)
    validation: Optional[ValidationReport]


def create_manifest(
    inputs: list[InputEntry],
    segments: list[SegmentEntry],
    transitions: list[TransitionEntry],
    filter_complex_script: str,
    args: list[str],
    total_sec: float,
    output_path: str,
    resolution: str,
    fps: int,
    vcodec: str,
    audio_block: Optional[AudioBlock] = None,
    filter_complex_inline: str = "",
) -> RenderManifest:
    """Factory per creare un RenderManifest valido.
    
    Args:
        inputs: Lista input FFmpeg
        segments: Lista segmenti video
        transitions: Lista transizioni
        filter_complex_script: Percorso file script
        args: Argomenti CLI FFmpeg completi
        total_sec: Durata totale dalla timeline quantizzata
        output_path: Percorso file output
        resolution: Risoluzione "WxH"
        fps: Frame rate
        vcodec: Codec video ("h264" o "h265")
        audio_block: Blocco audio opzionale
        filter_complex_inline: Stringa filtro inline (opzionale)
    
    Returns:
        RenderManifest valido e completo
    """
    return {
        "version": MANIFEST_VERSION,
        "status": "ready",
        "inputs": inputs,
        "segments": segments,
        "transitions": transitions,
        "filter_complex": filter_complex_inline,
        "filter_complex_script": filter_complex_script,
        "args": args,
        "total_sec": total_sec,
        "output": {
            "path": output_path,
            "resolution": resolution,
            "fps": fps,
            "vcodec": vcodec,
            "preset": "medium",
            "crf": 18 if vcodec == "h264" else 20,
            "size_bytes": 0,
        },
        "fps": fps,
        "resolution": resolution,
        "vcodec": vcodec,
        "audio": audio_block,
        "source_video_audio": "muted",
        "validation": None,
    }


def validate_manifest_schema(manifest: dict[str, Any]) -> list[str]:
    """Valida uno schema RenderManifest.
    
    Args:
        manifest: Dizionario da validare
        
    Returns:
        Lista di errori (vuota se valido)
    """
    errors: list[str] = []
    
    if not isinstance(manifest, dict):
        return ["render_manifest non è un dizionario"]
    
    # Campi obbligatori
    required_fields = [
        "version", "status", "inputs", "segments", "transitions",
        "filter_complex_script", "args", "total_sec", "output"
    ]
    
    for field in required_fields:
        if field not in manifest:
            errors.append(f"Campo mancante: {field}")
    
    if errors:
        return errors
    
    # Validazione version
    if manifest["version"] != MANIFEST_VERSION:
        errors.append(f"Versione mismatch: atteso {MANIFEST_VERSION}, trovato {manifest['version']}")
    
    # Validazione status
    valid_statuses = {"ready", "running", "done", "failed"}
    if manifest["status"] not in valid_statuses:
        errors.append(f"Status non valido: {manifest['status']}")
    
    # Validazione inputs
    if not isinstance(manifest["inputs"], list):
        errors.append("inputs deve essere una lista")
    else:
        for i, inp in enumerate(manifest["inputs"]):
            if not isinstance(inp, dict):
                errors.append(f"inputs[{i}] non è un dizionario")
            elif "path" not in inp or "kind" not in inp:
                errors.append(f"inputs[{i}] manca di path o kind")
    
    # Validazione segments
    if not isinstance(manifest["segments"], list):
        errors.append("segments deve essere una lista")
    else:
        for i, seg in enumerate(manifest["segments"]):
            if not isinstance(seg, dict):
                errors.append(f"segments[{i}] non è un dizionario")
            else:
                req_seg = ["media_id", "input_index", "kind", "fit", "duration_sec"]
                for field in req_seg:
                    if field not in seg:
                        errors.append(f"segments[{i}] manca di {field}")
    
    # Validazione transitions
    if not isinstance(manifest["transitions"], list):
        errors.append("transitions deve essere una lista")
    else:
        for i, tr in enumerate(manifest["transitions"]):
            if not isinstance(tr, dict):
                errors.append(f"transitions[{i}] non è un dizionario")
            else:
                req_tr = ["index", "from_segment", "to_segment", "duration_sec", "offset_sec"]
                for field in req_tr:
                    if field not in tr:
                        errors.append(f"transitions[{i}] manca di {field}")
    
    # Validazione output
    output = manifest.get("output", {})
    if not isinstance(output, dict):
        errors.append("output deve essere un dizionario")
    else:
        req_out = ["path", "resolution", "fps", "vcodec"]
        for field in req_out:
            if field not in output:
                errors.append(f"output manca di {field}")
        
        # vcodec deve essere presente e valido (libx264 o libx265)
        if "vcodec" in output and output["vcodec"] not in ("libx264", "libx265", "h264", "h265"):
            errors.append(f"output.vcodec non valido: {output['vcodec']}")
    
    # Validazione total_sec
    if not isinstance(manifest["total_sec"], (int, float)) or manifest["total_sec"] <= 0:
        errors.append(f"total_sec deve essere positivo: {manifest['total_sec']}")
    
    # Validazione filter_complex_script
    if not isinstance(manifest["filter_complex_script"], str):
        errors.append("filter_complex_script deve essere una stringa")
    
    # Validazione args
    if not isinstance(manifest["args"], list) or len(manifest["args"]) < 5:
        errors.append("args deve essere una lista non vuota di comandi ffmpeg")
    
    return errors
