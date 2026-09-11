"""API REST del backend. M1: upload media + Intake Agent. M2: normalizer nel
flusso upload + riordino timeline + fill cover/contain + serving anteprime.
M8: eventi realtime (SSE) + gestione errori."""
from __future__ import annotations

import asyncio
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Set, List, Optional, Annotated

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.api.schemas import (
    ClipOverrideRequest,
    HealthCheck,
    ProjectState,
    ReorderRequest,
    UpdateMediaRequest,
    UpdateSettingsRequest,
)
from app.agents import (
    audio_analysis,
    clip_overrides,
    edit_director,
    intake,
    normalizer,
    render as render_agent,
    sequence,
    timeline_compiler,
)
from app.pipeline import state as state_store
from app.pipeline.orchestrator import run_qa_with_retry
from app.pipeline.orchestrator import run_stages as _orch_run_stages
from app.jobs import manager as jobs
from app.services.audio_features import AUDIO_EXTS

router = APIRouter()

# === SECURITY: Limiti e validazione ===
MAX_FILES_PER_REQUEST = 50
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500MB
CHUNK_SIZE = 1024 * 1024  # 1MB per streaming upload
MAGIC_BYTES_SIZE = 64  # Byte sufficienti per validazione magic bytes

ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".mts"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tiff", ".tif", ".gif"}
ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac", ".opus", ".aac", ".wma"}

# Magic bytes per validazione contenuto reale
VIDEO_MAGIC = {
    b"\x00\x00\x00": "ftyp",
    b"\x1A\x45\xDF\xA3": "webm/mkv",
}
IMAGE_MAGIC = {
    b"\xFF\xD8\xFF": "jpeg", 
    b"\x89\x50\x4E\x47": "png",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",  # WebP usa RIFF header
}
# (La validazione audio è per-estensione in _validate_audio_magic: ID3/frame-sync
# per gli MP3, fLaC, ASF per i WMA, OggS, RIFF/RF64, ftyp — vedi sotto.)

# Rate limiting per render (thread-safe)
import threading
from app.ratelimit import limiter
_last_render_lock = threading.Lock()
_last_render_time: dict[str, float] = {}
_RENDER_RATE_LIMIT_SEC = 30
_MAX_TRACKED_PROJECTS = 10000


def _cleanup_old_render_times():
    """Rimuove entries più vecchie di 1 ora."""
    cutoff = time.time() - 3600
    with _last_render_lock:
        stale = [k for k, v in _last_render_time.items() if v < cutoff]
        for k in stale:
            del _last_render_time[k]


@router.get("/health", response_model=HealthCheck)
def health() -> HealthCheck:
    return HealthCheck(
        status="ok",
        service="ai-video-maker-backend",
        projects_count=len(state_store.list_projects()),
    )


@router.get("/projects")
def list_projects() -> list[dict]:
    return state_store.list_projects()


@router.post("/projects", response_model=ProjectState, status_code=201)
@limiter.limit("10/minute")
def create_project(request: Request) -> dict:
    state = state_store.new_project_state()
    state_store.ensure_project_dirs(state["project_id"])
    state_store.save_state(state)
    return state


@router.get("/projects/{project_id}", response_model=ProjectState)
def get_project(project_id: str) -> dict:
    try:
        return state_store.load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Progetto non trovato") from None


async def _validate_and_stream_file(
    file: UploadFile,
    allowed_exts: Set[str],
    dest_path: Path,
) -> tuple[str, int]:
    """Valida e scrive un file in streaming senza caricarlo tutto in RAM.
    
    Restituisce (safe_name, file_size) se valido.
    Solleva HTTPException se invalido.
    
    - Legge solo i primi MAGIC_BYTES_SIZE byte per validazione magic bytes
    - Streaming diretto su disco con chunk
    - Validazione dimensione durante lo streaming
    - Cleanup automatico del file parziale in caso di errore
    """
    ext = Path(file.filename or "").suffix.lower()
    
    # SECURITY: validazione estensione
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Estensione non supportata: {ext}"
        )
    
    safe_name = f"{uuid.uuid4().hex[:8]}{ext}"
    
    # Buffer per magic bytes
    magic_bytes = b""
    total_size = 0
    first_chunk = True
    file_started = False
    
    try:
        async with aiofiles.open(dest_path, "wb") as out_f:
            async for chunk in file.file.iter_chunks(CHUNK_SIZE):
                chunk_size = len(chunk)
                
                # Controlla dimensione totale prima di aggiungere
                if total_size + chunk_size > MAX_FILE_SIZE_BYTES:
                    # Cleanup: rimuovi file parziale
                    await out_f.close()
                    dest_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File troppo grande: massimo {MAX_FILE_SIZE_BYTES // (1024*1024)}MB"
                    )
                
                # Estrai magic bytes dal primo chunk
                if first_chunk:
                    magic_bytes = chunk[:MAGIC_BYTES_SIZE]
                    first_chunk = False
                
                # Scrivi chunk su disco
                await out_f.write(chunk)
                total_size += chunk_size
                file_started = True
        
        # Validazione magic bytes DOPO aver scritto tutto (ma prima di usare il file)
        if not _validate_magic_bytes_streaming(magic_bytes, ext):
            # Cleanup: rimuovi file invalido
            dest_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="Contenuto file non corrisponde all'estensione"
            )
        
        return safe_name, total_size
        
    except HTTPException:
        raise
    except Exception as e:
        # Cleanup in caso di errore generico
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Errore durante l'upload del file: {str(e)}")


def _validate_magic_bytes_streaming(magic_bytes: bytes, ext: str) -> bool:
    """Valida magic bytes da un buffer limitato (primi 64 byte)."""
    if not magic_bytes:
        return False
    
    # Video: cerca signature ftyp o webm/mkv
    if ext in ALLOWED_VIDEO_EXTS:
        for magic, fmt in VIDEO_MAGIC.items():
            if magic_bytes.startswith(magic):
                return True
        # Fallback: presenza di byte nulli tipici container video
        if b'\x00' in magic_bytes[:min(len(magic_bytes), 16)]:
            return True
    
    # Immagini: validazione per formati specifici
    if ext in ALLOWED_IMAGE_EXTS:
        # Controllo magic bytes specifici
        for magic, fmt in IMAGE_MAGIC.items():
            if magic_bytes.startswith(magic):
                return True
        
        # JPEG: FF D8 FF
        if magic_bytes.startswith(b"\xFF\xD8"):
            return True
        
        # PNG: 89 50 4E 47 0D 0A 1A 0A
        if magic_bytes.startswith(b"\x89PNG"):
            return True
        
        # GIF: GIF87a o GIF89a
        if magic_bytes.startswith(b"GIF8"):
            return True
        
        # WebP: RIFF....WEBP
        if magic_bytes.startswith(b"RIFF") and b"WEBP" in magic_bytes[:32]:
            return True
        
        # BMP: BM header
        if magic_bytes.startswith(b"BM"):
            return True
        
        # TIFF: II (little-endian) o MM (big-endian)
        if magic_bytes.startswith(b"II\x2A\x00") or magic_bytes.startswith(b"MM\x00\x2A"):
            return True
        
        # HEIC/HEIF: ftyp box tipico
        if b"ftyp" in magic_bytes[:32] or b"heic" in magic_bytes[:64]:
            return True
    
    return False


@router.post("/projects/{project_id}/media", response_model=None)
@limiter.limit("5/minute")
async def upload_media(
    request: Request,
    project_id: str,
    files: Annotated[List[UploadFile], File(...)],
    source: str = Form("local"),
) -> dict:
    try:
        state = state_store.load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Progetto non trovato") from None

    # SECURITY: limite numero file per richiesta (DoS)
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=413,
            detail=f"Troppi file: massimo {MAX_FILES_PER_REQUEST} per richiesta"
        )

    # APPROCCIO C: streaming singolo - valida e scrivi contemporaneamente
    # Ogni file viene validato e scritto in un'unica pass
    media_dir = state_store.media_dir(project_id)
    media_dir.mkdir(parents=True, exist_ok=True)
    
    staging = []
    uploaded_files: list[Path] = []  # Track files per cleanup in caso di errore
    
    try:
        for f in files:
            dest = media_dir / f"{uuid.uuid4().hex[:8]}{Path(f.filename or '').suffix.lower()}"
            safe_name, size = await _validate_and_stream_file(
                f, 
                ALLOWED_VIDEO_EXTS | ALLOWED_IMAGE_EXTS,
                dest
            )
            # Aggiorna il nome del file destination con il safe_name
            final_dest = media_dir / safe_name
            if dest != final_dest:
                dest.rename(final_dest)
            
            uploaded_files.append(final_dest)
            staging.append({"path": str(final_dest), "source": source, "drive_file_id": None})

        state["media_staging"] = staging
        state = await intake.run(state)
        # M2: ogni nuovo media viene subito normalizzato (fit cover/contain,
        # background blur/solid, order_index contigui) — architettura sez. 5 Agente 1.
        state = await normalizer.run(state)
        # M3: durate foto + trim video (deterministico per id, non tocca ordine/fit).
        state = await sequence.run(state)
        state_store.save_state(state)
        return state
        
    except HTTPException:
        # Cleanup: rimuovi tutti i file caricati finora in caso di errore
        for uploaded_file in uploaded_files:
            try:
                if uploaded_file.exists():
                    uploaded_file.unlink()
            except Exception:
                pass
        raise
    except Exception as e:
        # Cleanup per errori non-HTTP
        for uploaded_file in uploaded_files:
            try:
                if uploaded_file.exists():
                    uploaded_file.unlink()
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Errore interno durante l'upload: {str(e)}")


def _validate_magic_bytes(content: bytes, ext: str) -> bool:
    """Valida che il contenuto del file corrisponda ai magic bytes attesi."""
    if not content:
        return False
    
    # Video: cerca signature ftyp o webm/mkv
    if ext in ALLOWED_VIDEO_EXTS:
        for magic, fmt in VIDEO_MAGIC.items():
            if content.startswith(magic):
                return True
        # Fallback: presenza di byte nulli tipici container video
        if b'\x00' in content[:512]:
            return True
    
    # Immagini: validazione per formati specifici
    if ext in ALLOWED_IMAGE_EXTS:
        # Controllo magic bytes specifici
        for magic, fmt in IMAGE_MAGIC.items():
            if content.startswith(magic):
                return True
        
        # JPEG: FF D8 FF
        if content.startswith(b"\xFF\xD8"):
            return True
        
        # PNG: 89 50 4E 47 0D 0A 1A 0A
        if content.startswith(b"\x89PNG"):
            return True
        
        # GIF: GIF87a o GIF89a
        if content.startswith(b"GIF8"):
            return True
        
        # WebP: RIFF....WEBP
        if content.startswith(b"RIFF") and b"WEBP" in content[:32]:
            return True
        
        # BMP: BM header
        if content.startswith(b"BM"):
            return True
        
        # TIFF: II (little-endian) o MM (big-endian)
        if content.startswith(b"II\x2A\x00") or content.startswith(b"MM\x00\x2A"):
            return True
        
        # HEIC/HEIF: ftyp box tipico
        if b"ftyp" in content[:32] or b"heic" in content[:64]:
            return True
    
    return False


_RESOLUTION_RE = re.compile(r"^(\d+)x(\d+)$")
_ALLOWED_FPS = {23, 24, 25, 29, 30, 50, 59, 60}


def _get_state_or_404(project_id: str) -> dict:
    try:
        return state_store.load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Progetto non trovato") from None


@router.put("/projects/{project_id}/media/order", response_model=ProjectState)
async def reorder_media(project_id: str, body: ReorderRequest) -> dict:
    """M2: applica l'ordine manuale della timeline (RF2).

    `media_ids` deve contenere esattamente tutti gli id esistenti, nel nuovo
    ordine. Rispetta l'ordine utente (Sequence Agent M3 non riordinerà mai
    autonomamente) e rinormalizza gli order_index 0..N-1 + fit via Normalizer.
    """
    state = _get_state_or_404(project_id)
    media = state.get("media", [])
    existing_ids = [m["id"] for m in media]
    if len(body.media_ids) != len(existing_ids):
        raise HTTPException(
            status_code=400,
            detail=f"media_ids deve contenere tutti i {len(existing_ids)} media "
            f"(ricevuti {len(body.media_ids)})",
        )
    if set(body.media_ids) != set(existing_ids):
        raise HTTPException(
            status_code=400, detail="media_ids contiene id sconosciuti o ne omette alcuni"
        )
    if len(set(body.media_ids)) != len(body.media_ids):
        raise HTTPException(status_code=400, detail="media_ids contiene duplicati")

    by_id = {m["id"]: m for m in media}
    for idx, mid in enumerate(body.media_ids):
        by_id[mid]["order_index"] = idx
    state["media"] = [by_id[mid] for mid in body.media_ids]
    # Rinormalizza fit/background senza alterare l'ordine appena impostato.
    # (order_index gia' contigui nell'ordine voluto: il sort del normalizer
    # preserva l'ordine richiesto.)
    state = await normalizer.run(state)
    # M3: riassegna durate/trim in modo idempotente (non altera l'ordine).
    state = await sequence.run(state)
    state_store.save_state(state)
    return state


@router.patch("/projects/{project_id}/media/{media_id}", response_model=ProjectState)
async def update_media(project_id: str, media_id: str, body: UpdateMediaRequest) -> dict:
    """M2: preferenza di sfondo del singolo media (solo portrait ha effetto).

    Per landscape/square il Normalizer forza fit=cover e background=None
    (il frame e' pieno, nessuno sfondo visibile): la preferenza viene
    accettata ma normalizzata a None.
    """
    state = _get_state_or_404(project_id)
    target = next((m for m in state.get("media", []) if m["id"] == media_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Media non trovato")
    if body.background_fill is not None:
        # Marca come override esplicito dell'utente sul singolo media.
        target["background_fill"] = body.background_fill
    state = await normalizer.run(state)
    state_store.save_state(state)
    return state


@router.patch("/projects/{project_id}/settings", response_model=ProjectState)
async def update_settings(project_id: str, body: UpdateSettingsRequest) -> dict:
    """M2: output_spec (sfondo di default, risoluzione, fps).

    Se cambia background_fill, viene propagato a tutti i portrait (il default
    di progetto si applica a tutti; la personalizzazione per-singolo si fa
    dopo via PATCH media).
    """
    state = _get_state_or_404(project_id)
    spec = state.setdefault("output_spec", {})

    if body.background_fill is not None:
        spec["background_fill"] = body.background_fill
        # Propagazione: il nuovo default si applica a tutti i portrait.
        for m in state.get("media", []):
            if m.get("orientation") == "portrait":
                m["background_fill"] = body.background_fill

    if body.resolution is not None:
        m = _RESOLUTION_RE.match(body.resolution)
        if not m:
            raise HTTPException(
                status_code=400, detail="resolution deve essere nel formato LARGHEZZAxALTEZZA (es. 1920x1080)"
            )
        w, h = int(m.group(1)), int(m.group(2))
        if w <= 0 or h <= 0 or w > 7680 or h > 4320:
            raise HTTPException(status_code=400, detail="resolution fuori intervallo supportato")
        spec["resolution"] = body.resolution

    if body.fps is not None:
        if body.fps not in _ALLOWED_FPS:
            raise HTTPException(
                status_code=400,
                detail=f"fps deve essere uno di {sorted(_ALLOWED_FPS)}",
            )
        spec["fps"] = body.fps

    if body.vcodec is not None:
        spec["vcodec"] = body.vcodec

    state = await normalizer.run(state)
    state_store.save_state(state)
    return state


@router.post("/projects/{project_id}/audio", response_model=ProjectState)
async def upload_audio(project_id: str, file: UploadFile = File(...)) -> dict:
    """Carica una nuova traccia audio e la aggiunge alla sequenza del progetto."""
    state = _get_state_or_404(project_id)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(status_code=400, detail=f"Formato audio non supportato: {ext}")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File audio troppo grande: massimo 500MB")
    if not _validate_audio_magic(content, ext):
        raise HTTPException(status_code=400, detail="Contenuto audio non valido")

    audio_dir = state_store.audio_dir(project_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    dest = audio_dir / f"{uuid.uuid4().hex[:8]}{ext}"
    dest.write_bytes(content)

    track = {"id": uuid.uuid4().hex[:12], "name": file.filename or dest.name,
             "path": str(dest), "duration_sec": 0.0, "bpm": 0.0,
             "beat_markers_sec": [], "energy_curve": []}
    temp_state = {"audio": track}
    temp_state = await audio_analysis.run(temp_state)
    track = temp_state["audio"]

    tracks = list(state.get("audio_tracks") or [])
    tracks.append(track)
    state["audio_tracks"] = tracks

    # Backward compatibility: audio è un riepilogo concatenato delle tracce.
    total = 0.0
    bpm_weight = 0.0
    bpm_sum = 0.0
    markers: list[float] = []
    energy: list[float] = []
    for t in tracks:
        dur = float(t.get("duration_sec") or 0.0)
        markers.extend(round(float(x) + total, 3) for x in (t.get("beat_markers_sec") or []))
        energy.extend(t.get("energy_curve") or [])
        bpm = float(t.get("bpm") or 0.0)
        if bpm > 0 and dur > 0:
            bpm_sum += bpm * dur
            bpm_weight += dur
        total += dur
    state["audio"] = {
        "path": tracks[0].get("path") if tracks else None,
        "duration_sec": round(total, 3),
        "bpm": round(bpm_sum / bpm_weight, 2) if bpm_weight else 0.0,
        "beat_markers_sec": markers,
        "energy_curve": energy,
    }
    state_store.save_state(state)
    return state


def _has_mp3_frame_sync(content: bytes, window: int = 8192) -> bool:
    """True se c'è un frame header MP3/ADTS (0xFF + top-3-bit) in testa.

    Copre tutte le versioni MPEG (1/2/2.5) e layer (I/II/III): il vecchio
    controllo accettava solo 0xFF 0xFB, ma quasi tutti gli MP3 reali iniziano
    con un tag ID3v2 o con sync diversi (0xF3/0xF2/0xF9...). La scansione
    copre anche eventuali tag APE/Lyrics in testa.
    """
    head = content[:max(2, window)]
    for i in range(len(head) - 1):
        if head[i] == 0xFF and (head[i + 1] & 0xE0) == 0xE0:
            return True
    return False


def _validate_audio_magic(content: bytes, ext: str) -> bool:
    """Valida magic bytes per file audio (un formato per estensione).

    Ogni estensione supportata DEVE avere la sua firma qui: in passato
    mancavano ID3 (quasi tutti gli MP3 reali), fLaC e l'header ASF dei WMA,
    e l'upload di quei file veniva rifiutato con 400 pur essendo validi.
    """
    if not content or len(content) < 16:
        return False

    if ext == ".mp3":
        return content.startswith(b"ID3") or _has_mp3_frame_sync(content, 2) \
            or _has_mp3_frame_sync(content)

    if ext == ".wav":
        # RIFF....WAVE (o RF64 per i >4GB)
        return content.startswith(b"RIFF") or content.startswith(b"RF64")

    if ext in (".ogg", ".oga", ".opus"):
        return content.startswith(b"OggS")

    if ext == ".flac":
        return content.startswith(b"fLaC")

    if ext == ".m4a":
        # box ftyp quasi sempre a offset 4
        return b"ftyp" in content[:32]

    if ext == ".aac":
        # ADTS (frame sync) o ADIF
        return content.startswith(b"ADIF") or _has_mp3_frame_sync(content, 2)

    if ext == ".wma":
        # header ASF GUID 30 26 B2 75 ...
        return content.startswith(bytes([0x30, 0x26, 0xB2, 0x75]))

    return False


@router.post("/projects/{project_id}/edit", response_model=ProjectState)
async def plan_edit(project_id: str) -> dict:
    """M4: genera il piano di montaggio (Sequence -> Edit Director -> Compiler).

    Tra Director e Compiler vengono riapplicate le modifiche manuali per-clip
    (clip_overrides): "Rigenera" crea nuove idee ma non cancella i lucchetti
    dell'utente (si tolgono col cestino sulla clip).
    """
    state = _get_state_or_404(project_id)
    if not state.get("media"):
        raise HTTPException(status_code=400, detail="Nessun media: carica prima foto/video")
    state = await _run_stages(state, (("sequence", sequence.run),
                                      ("edit_director", edit_director.run),
                                      ("clip_overrides", clip_overrides.run),
                                      ("timeline_compiler", timeline_compiler.run)))
    state_store.save_state(state)
    return state


async def _run_stages(state: dict, stages) -> dict:
    """Esegue stage via orchestratore; al primo errore salva e solleva 500
    (stop downstream, AGENTS.md). Errori/log failed gia' registrati dal runner."""
    try:
        return await _orch_run_stages(state, list(stages))
    except HTTPException:
        raise
    except Exception as exc:
        state_store.save_state(state)
        raise HTTPException(status_code=500, detail=f"{exc}") from None


def _get_edl_or_400(state: dict) -> list[dict]:
    edl = state.get("edit_decision_list") or []
    if not edl:
        raise HTTPException(status_code=400,
                            detail="Nessun montaggio: usa prima 'Genera montaggio'")
    return edl


@router.patch("/projects/{project_id}/edit/clips/{media_id}", response_model=ProjectState)
async def update_clip(project_id: str, media_id: str, body: ClipOverrideRequest) -> dict:
    """Modifica manuale di una clip (durata / dissolvenza in uscita / movimento).

    Salva l'override in state["clip_overrides"] e riesegue solo
    clip_overrides + compiler (veloce, il regista non viene toccato).
    Invalida il QA precedente: serve riesportare per vedere il risultato.
    """
    from app.agents import edit_director as director_mod

    state = _get_state_or_404(project_id)
    edl = _get_edl_or_400(state)
    target = next((m for m in state.get("media", []) if m.get("id") == media_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Media non trovato nel progetto")
    if not any(e.get("media_id") == media_id for e in edl):
        raise HTTPException(status_code=404, detail="Clip non presente nel montaggio")
    if (body.duration_sec is None and body.transition_out is None
            and body.ken_burns_movement is None):
        raise HTTPException(status_code=400, detail="Niente da modificare: indica almeno un campo")

    entry = state.setdefault("clip_overrides", {}).setdefault(media_id, {})
    if body.duration_sec is not None:
        d = round(float(body.duration_sec), 2)
        if target.get("type") == "photo":
            if not (clip_overrides.PHOTO_MANUAL_MIN_SEC <= d <= clip_overrides.PHOTO_MANUAL_MAX_SEC):
                raise HTTPException(
                    status_code=400,
                    detail=f"Durata foto {d}s fuori "
                    f"[{clip_overrides.PHOTO_MANUAL_MIN_SEC}, {clip_overrides.PHOTO_MANUAL_MAX_SEC}]s")
        else:
            src = float(target.get("duration_sec") or 0.0)
            if not (clip_overrides.VIDEO_MANUAL_MIN_SEC <= d <= src):
                raise HTTPException(
                    status_code=400,
                    detail=f"Durata video {d}s fuori [0.5, {src:.1f}]s (sorgente)")
        entry["duration_sec"] = d
    if body.transition_out is not None:
        t = round(float(body.transition_out), 2)
        is_last = edl[-1].get("media_id") == media_id
        if is_last and t != 0.0:
            raise HTTPException(status_code=400,
                                detail="L'ultima clip non può avere transizione in uscita")
        if t < 0.0 or t > clip_overrides.TRANS_MANUAL_MAX_SEC:
            raise HTTPException(
                status_code=400,
                detail=f"Transizione {t}s fuori [0.0, {clip_overrides.TRANS_MANUAL_MAX_SEC}]s "
                f"(0.0 = stacco secco)")
        entry["transition_out"] = t
    if body.ken_burns_movement is not None:
        mv = body.ken_burns_movement
        if target.get("type") != "photo":
            raise HTTPException(status_code=400, detail="Il movimento si imposta solo sulle foto")
        if mv == "auto":
            entry.pop("ken_burns", None)
        elif mv in director_mod.MOVEMENTS or mv == "static":
            entry["ken_burns"] = mv
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Movimento sconosciuto: {mv} "
                f"({', '.join([*director_mod.MOVEMENTS, 'static', 'auto'])})")
    if not entry:
        state["clip_overrides"].pop(media_id, None)

    state = await _run_stages(state, (("clip_overrides", clip_overrides.run),
                                      ("timeline_compiler", timeline_compiler.run)))
    state["qa_report"] = None  # piano cambiato a mano: il verdetto precedente non vale più
    state_store.save_state(state)
    return state


@router.delete("/projects/{project_id}/edit/clips/{media_id}", response_model=ProjectState)
async def reset_clip(project_id: str, media_id: str) -> dict:
    """Toglie tutte le modifiche manuali di una clip (torna al piano del regista)."""
    state = _get_state_or_404(project_id)
    if not state.get("clip_overrides", {}).pop(media_id, None):
        return state  # nessun override: niente da fare
    if state.get("edit_decision_list"):
        state = await _run_stages(state, (("clip_overrides", clip_overrides.run),
                                          ("timeline_compiler", timeline_compiler.run)))
        state["qa_report"] = None
    state_store.save_state(state)
    return state


@router.post("/projects/{project_id}/render", response_model=ProjectState)
async def render_video(project_id: str, background: bool = False) -> dict:
    """M5/M6: esportazione end-to-end (piano fresco + render + QA con retry).

    Riesegue Sequence -> Director -> Compiler (idempotenti) poi Render e QA;
    se il QA rigetta per motivi creativi, una ripianificazione con qa_feedback.
    Con background=true accoda invece un job (202) per progetti lunghi.
    Il download e' su GET /projects/{id}/download.
    """
    state = _get_state_or_404(project_id)
    if not state.get("media"):
        raise HTTPException(status_code=400, detail="Nessun media: carica prima foto/video")
    
    # SECURITY: rate limiting su render sincrono (DoS) - thread-safe
    if not background:
        now = time.time()
        with _last_render_lock:
            last = _last_render_time.get(project_id, 0)
            if now - last < _RENDER_RATE_LIMIT_SEC:
                remaining = int(_RENDER_RATE_LIMIT_SEC - (now - last))
                raise HTTPException(
                    status_code=429,
                    detail=f"Render troppo frequente: attendi {remaining}s",
                    headers={"Retry-After": str(remaining)},
                )
            _last_render_time[project_id] = now
        
        # Cleanup periodico per evitare memory leak
        if len(_last_render_time) > _MAX_TRACKED_PROJECTS:
            _cleanup_old_render_times()
    
    if background:
        try:
            job = jobs.submit(project_id, "render")
        except jobs.JobExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return JSONResponse(status_code=202, content={"job": _public_job(job)})
    state = await _run_stages(state, (("sequence", sequence.run),
                                      ("edit_director", edit_director.run),
                                      ("clip_overrides", clip_overrides.run),
                                      ("timeline_compiler", timeline_compiler.run),
                                      ("render", render_agent.run)))
    if not (state.get("render_manifest") or {}).get("status") == "done":
        raise HTTPException(status_code=500, detail="render: manifest non completato")
    try:
        state = await run_qa_with_retry(state)
    except Exception as exc:
        state_store.save_state(state)
        raise HTTPException(status_code=500, detail=f"{exc}") from None
    state_store.save_state(state)
    return state


@router.get("/projects/{project_id}/download")
def download_video(project_id: str):
    """M5: scarica l'mp4 finale (404 se mai renderizzato, 404 se file mancante)."""
    state = _get_state_or_404(project_id)
    out_path = (state.get("render_manifest") or {}).get("output", {}).get("path")
    if not out_path:
        raise HTTPException(status_code=404, detail="Nessun video renderizzato: usa prima Esporta")
    p = Path(out_path)
    if not p.is_absolute():
        p = state_store.project_dir(project_id) / p
    
    # SECURITY: verifica anti path-traversal unificata
    resolved = _ensure_path_within_project(project_id, p)
    
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File video mancante su disco")
    return FileResponse(path=str(resolved), media_type="video/mp4",
                        filename=f"video-{project_id}.mp4")


def _ensure_path_within_project(project_id: str, path: Path) -> Path:
    """Helper unificato per verificare che un path sia dentro la sandbox del progetto.
    
    SECURITY: previene path-traversal attacks risolvendo il path assoluto
    e verificando che sia contenuto nella root del progetto.
    """
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Percorso non valido")
    
    project_root = state_store.project_dir(project_id).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Accesso negato: percorso fuori sandbox")
    
    return resolved


def _resolve_media_path(project_id: str, media_id: str) -> tuple[dict, Path]:
    """Metadata + path assoluto verificato (dentro il progetto, esistente)."""
    state = _get_state_or_404(project_id)
    target = next((m for m in state.get("media", []) if m["id"] == media_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Media non trovato")
    p = Path(target["path"])
    if not p.is_absolute():
        p = state_store.project_dir(project_id) / p
    
    # SECURITY: usa helper unificato anti path-traversal
    resolved = _ensure_path_within_project(project_id, p)
    
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File media mancante su disco")
    return target, resolved


@router.get("/projects/{project_id}/media/{media_id}/file")
def get_media_file(project_id: str, media_id: str):
    """M2: serve il file originale per le anteprime nella timeline.

    Risolve il path dal Project State (non dal nome file richiesto) e verifica
    che resti dentro la cartella del progetto (anti path-traversal).
    """
    _, resolved = _resolve_media_path(project_id, media_id)
    media_type, _ = mimetypes.guess_type(resolved.name)
    return FileResponse(path=str(resolved), media_type=media_type or "application/octet-stream")


def _photo_thumb(src: Path, dest: Path, w: int) -> None:
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((w, w * 4))
        im.save(dest, "JPEG", quality=72)


def _video_thumb(src: Path, dest: Path, w: int, target: dict) -> None:
    ts = float(target.get("trim_start_sec") or 0.0)
    te = target.get("trim_end_sec")
    eff = (float(te) - ts) if te else float(target.get("duration_sec") or 2.0)
    ss = round(ts + max(0.1, min(2.0, eff * 0.1)), 2)
    for attempt_ss in (ss, 0):
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(attempt_ss), "-i", str(src),
             "-frames:v", "1", "-vf", f"scale={w}:-2", "-q:v", "4", str(dest)],
            capture_output=True)
        if proc.returncode == 0 and dest.is_file():
            return
    raise RuntimeError(f"thumb video non generabile: {src.name}")


@router.get("/projects/{project_id}/media/{media_id}/thumb")
def get_media_thumb(project_id: str, media_id: str,
                    w: int = Query(320, ge=64, le=960)):
    """Polish: anteprima JPEG leggera con cache (foto via Pillow, video via ffmpeg).

    La timeline usa queste invece degli originali (centinaia di file OK).
    """
    target, src = _resolve_media_path(project_id, media_id)
    tdir = state_store.thumbs_dir(project_id)
    tdir.mkdir(parents=True, exist_ok=True)
    thumb = tdir / f"{media_id}_w{w}.jpg"
    fresh = thumb.is_file() and thumb.stat().st_mtime >= src.stat().st_mtime
    if not fresh:
        try:
            if target["type"] == "photo":
                _photo_thumb(src, thumb, w)
            else:
                _video_thumb(src, thumb, w, target)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Anteprima non generabile: {exc}") from None
    return FileResponse(path=str(thumb), media_type="image/jpeg")


def _public_job(job: dict) -> dict:
    status_map = {"queued": "pending", "running": "running", "done": "completed", "failed": "failed"}
    return {
        "id": job.get("job_id") or job.get("id"),
        "kind": job.get("kind"),
        "status": status_map.get(job.get("status"), job.get("status")),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "progress": job.get("progress"),
    }


def progress_payload(state: dict) -> dict:
    """Snapshot leggero per la UI realtime (M8): avanzamento, errori, esiti."""
    manifest = state.get("render_manifest") or {}
    qa = state.get("qa_report") or {}
    return {
        "pipeline_log": (state.get("pipeline_log") or [])[-100:],
        "errors_count": len(state.get("errors", [])),
        "media_count": len(state.get("media", [])),
        "has_audio": bool((state.get("audio") or {}).get("path")),
        "has_edit": bool(state.get("edit_decision_list")),
        "has_render": bool(manifest.get("status") == "done"),
        "qa_status": qa.get("status"),
        "updated_at": state.get("updated_at", 0),
        "jobs": [_public_job(j) for j in jobs.recent_for_project(state.get("project_id", ""), 5)],
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    """Stato di un job in coda (202 submit -> poll fino a done/failed)."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job non trovato")
    return job


@router.get("/projects/{project_id}/events")
async def project_events(project_id: str):
    """M8: stream SSE con lo snapshot di avanzamento a ogni cambiamento.

    Il client riceve subito uno snapshot e poi un evento per ogni modifica
    dello state (upload, reorder, import, render...), piu' heartbeat.
    La chiusura del client cancella il task (fine stream ordinata).
    """
    _get_state_or_404(project_id)
    return StreamingResponse(watch_project(project_id),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


async def watch_project(project_id: str, poll_sec: float = 1.0,
                        heartbeat_every: int = 15):
    """Generatore SSE (anche per test): snapshot a ogni modifica + ping.

    Termina se il progetto sparisce o se il consumer chiude (CancelledError).
    """
    last: str | None = None
    idle = 0
    try:
        while True:
            try:
                state = state_store.load_state(project_id)
            except FileNotFoundError:
                break
            payload = json.dumps(progress_payload(state), ensure_ascii=False)
            if payload != last:
                last = payload
                idle = 0
                yield f"data: {payload}\n\n"
            else:
                idle += 1
                if idle >= heartbeat_every:
                    idle = 0
                    yield ": ping\n\n"
            await asyncio.sleep(poll_sec)
    except asyncio.CancelledError:
        pass


@router.post("/projects/{project_id}/errors/clear", response_model=ProjectState)
def clear_errors(project_id: str) -> dict:
    """M8: azzera gli errori non bloccanti dopo che l'utente li ha visionati."""
    state = _get_state_or_404(project_id)
    state["errors"] = []
    state_store.save_state(state)
    return state


@router.delete("/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    """Elimina un progetto e tutti i suoi file associati."""
    try:
        state = state_store.load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Progetto non trovato") from None
    
    # Elimina tutti i file del progetto
    project_path = state_store.project_dir(project_id)
    if project_path.exists():
        shutil.rmtree(project_path)
    
    return {"message": "Progetto eliminato con successo", "project_id": project_id}

