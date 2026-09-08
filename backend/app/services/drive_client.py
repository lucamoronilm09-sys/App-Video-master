"""Client Google Drive: OAuth2 + browse + download (Agente -1b, M7).

Scope minimo: drive.readonly. Le credenziali OAuth (client_id/secret inseriti
una tantum dall'utente) e il token vivono in data/ (gitignored, mai esposti via
API). Tutte le funzioni che toccano la rete prendono un `service` Drive
iniettabile -> test senza rete con service finti.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import re
import secrets
import ssl
from collections import deque
from io import FileIO
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from httplib2 import HttpLib2Error

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."  # Docs/Sheets/Slides: niente bytes binari, serve export
REDIRECT_PATH = "/api/drive/callback"
MAX_IMPORT_ITEMS = 3000
DOWNLOAD_WORKERS = 6
# Limite dimensione per singolo file da Drive: allineato al cap di upload
# locale (routes.MAX_FILE_SIZE_BYTES = 500MB) per non saturare disco/worker.
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
# Timeout per singolo download: oltre questa soglia l'agent interrompe il
# file (errore esplicito) invece di restare appeso all'infinito.
DOWNLOAD_TIMEOUT_SEC = 300
# Timeout per la creazione del service (fetch discovery doc) e per
# l'espansione della selezione (paginazione cartelle): senza questi, uno
# stallo di rete in queste fasi bloccherebbe il job (e tutta la coda FIFO).
SERVICE_TIMEOUT_SEC = 60
EXPAND_TIMEOUT_SEC = 600
# Retry su errori transitori (rete instabile, TLS intercettato a intermittenza,
# SSL: WRONG_VERSION_NUMBER, IncompleteRead, 5xx/429): gli errori permanenti
# (401/403/404, file troppo grande, nativo Google) falliscono subito.
DOWNLOAD_MAX_ATTEMPTS = 4
DOWNLOAD_RETRY_BASE_SEC = 2.0
# Retry interni a ogni chunk (riprende lo stesso chunk, backoff di googleapiclient).
DOWNLOAD_CHUNK_RETRIES = 3


class DriveDownloadError(RuntimeError):
    """Errore di download con messaggio già chiaro per l'utente.

    transient=True: ha senso riprovare (rete/TLS instabile, 5xx/429).
    transient=False: riprovare è inutile (permessi, file assente, limiti).
    """

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


def is_transient_error(exc: Exception) -> bool:
    """True per gli errori che vale la pena ritentare."""
    if isinstance(exc, DriveDownloadError):
        return exc.transient
    if isinstance(exc, HttpError):
        status = _http_status(exc)
        return status is not None and (status == 429 or status >= 500)
    return isinstance(exc, (TimeoutError, ssl.SSLError, ConnectionError,
                            HttpLib2Error, http.client.HTTPException, OSError))

CREDS_PATH = DATA_DIR / "google_credentials.json"
TOKEN_PATH = DATA_DIR / "drive_token.json"
OAUTH_STATE_PATH = DATA_DIR / "drive_oauth_state.json"


def redirect_uri(host: str = "http://127.0.0.1:8000") -> str:
    return f"{host}{REDIRECT_PATH}"


# --- credenziali OAuth (client) ---

def save_client_config(client_id: str, client_secret: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CREDS_PATH.write_text(json.dumps({"client_id": client_id.strip(),
                                      "client_secret": client_secret.strip()}),
                          encoding="utf-8")


def load_client_config() -> dict[str, str] | None:
    if not CREDS_PATH.is_file():
        return None
    try:
        cfg = json.loads(CREDS_PATH.read_text(encoding="utf-8"))
        if cfg.get("client_id") and cfg.get("client_secret"):
            return {"client_id": cfg["client_id"], "client_secret": cfg["client_secret"]}
    except Exception:
        pass
    return None


def _client_config_for_flow(cfg: dict[str, str], host: str) -> dict[str, Any]:
    return {"web": {"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri(host)]}}


def build_flow(host: str = "http://127.0.0.1:8000") -> Flow:
    cfg = load_client_config()
    if not cfg:
        raise RuntimeError("Credenziali Google non configurate")
    return Flow.from_client_config(_client_config_for_flow(cfg, host),
                                   scopes=SCOPES, redirect_uri=redirect_uri(host))


def get_authorization_url(host: str = "http://127.0.0.1:8000") -> str:
    """URL consenso Google; salva lo state anti-CSRF lato server."""
    flow = build_flow(host)
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OAUTH_STATE_PATH.write_text(
        json.dumps({"state": state, "code_verifier": flow.code_verifier}),
        encoding="utf-8"
    )
    return url


def exchange_code_and_save(code: str, returned_state: str,
                           host: str = "http://127.0.0.1:8000") -> None:
    try:
        saved_data = json.loads(OAUTH_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        saved_data = {}
    saved_state = saved_data.get("state")
    saved_verifier = saved_data.get("code_verifier")
    if not saved_state or not returned_state or saved_state != returned_state:
        raise ValueError("state OAuth non valido (riprova la connessione)")
    flow = build_flow(host)
    if saved_verifier:
        flow.code_verifier = saved_verifier
    flow.fetch_token(code=code)
    TOKEN_PATH.write_text(flow.credentials.to_json(), encoding="utf-8")
    try:
        OAUTH_STATE_PATH.unlink()
    except OSError:
        pass


def load_credentials() -> Credentials | None:
    """Credenziali salvate (con refresh automatico); None se assenti/revocate.

    Un token scaduto con refresh_token viene rinnovato subito, così il
    download non parte mai con un access token noto-scaduto.
    """
    if not TOKEN_PATH.is_file():
        logger.debug("drive: nessun token salvato, OAuth da completare")
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    except Exception as exc:
        logger.warning("drive: token illeggibile (%s), serve riconnessione", exc)
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            logger.info("drive: access token scaduto, refresh in corso")
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
            logger.info("drive: token aggiornato con successo")
        except Exception as exc:
            logger.warning("drive: refresh token fallito (%s), serve riconnessione", exc)
            return None
    if not creds or not creds.valid:
        logger.warning("drive: credenziali non valide (revocate o scadute senza refresh)")
        return None
    return creds


def disconnect() -> None:
    try:
        TOKEN_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def get_drive_service():
    creds = load_credentials()
    if not creds:
        raise RuntimeError("Drive non connesso: completa prima il collegamento OAuth")
    proxy_vars = [k for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                              "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy")
                  if os.getenv(k)]
    if proxy_vars:
        # httplib2 raccoglie queste variabili da solo: se i download falliscono
        # con errori SSL (es. WRONG_VERSION_NUMBER), il primo sospettato è qui
        # (proxy/VPN/antivirus con intercettazione TLS). I valori non si loggano
        # (potrebbero contenere credenziali).
        logger.warning("drive: variabili proxy di sistema attive (%s); "
                       "in caso di errori SSL sui download, provare a disattivare "
                       "proxy/VPN/scansione HTTPS dell'antivirus",
                       ",".join(proxy_vars))
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    return build("drive", "v3", credentials=None,
                 http=AuthorizedHttp(creds, http=httplib2.Http(timeout=300)),
                 cache_discovery=False)


def get_account_email(service) -> str | None:
    try:
        about = service.about().get(fields="user(emailAddress)").execute()
        return (about.get("user") or {}).get("emailAddress")
    except Exception:
        return None


# --- browse ---

def is_supported_media(mime: str) -> bool:
    if mime == "image/svg+xml":
        return False
    return mime.startswith("image/") or mime.startswith("video/")


def _safe_id(folder_id: str) -> str:
    if folder_id == "root" or re.fullmatch(r"[\w-]+", folder_id):
        return folder_id
    raise ValueError(f"folder_id non valido: {folder_id}")


def list_children(service, folder_id: str = "root", page_token: str | None = None,
                  page_size: int = 100) -> dict[str, Any]:
    """Figli non cestinati di una cartella: {entries: [{id,name,mimeType,is_folder,size}], nextPageToken}."""
    fid = _safe_id(folder_id)
    q = f"'{fid}' in parents and trashed=false"
    logger.debug("drive: list figli di '%s' (page_size=%s)", fid, page_size)
    req = service.files().list(q=q, fields="nextPageToken,files(id,name,mimeType,size)",
                               orderBy="folder,name", pageSize=max(1, min(page_size, 200)),
                               pageToken=page_token)
    try:
        res = req.execute()
    except HttpError as exc:
        logger.warning("drive: list '%s' fallita: %s", fid, _short_http_error(exc))
        raise
    entries = [{"id": f["id"], "name": f.get("name", "?"),
                "mimeType": f.get("mimeType", ""),
                "is_folder": f.get("mimeType") == FOLDER_MIME,
                "size": _to_int_or_none(f.get("size"))}
               for f in res.get("files", [])]
    logger.debug("drive: '%s' -> %d voci", fid, len(entries))
    return {"entries": entries, "nextPageToken": res.get("nextPageToken")}


def list_shared_with_me(service, page_token: str | None = None,
                        page_size: int = 100) -> dict[str, Any]:
    """File e cartelle condivisi con l'utente: {entries: [{id,name,mimeType,is_folder}], nextPageToken}.
    
    Query: sharedWithMe=true and trashed=false. Stessi campi e ordinamento di list_children.
    """
    q = "sharedWithMe=true and trashed=false"
    logger.debug("drive: list 'condivisi con me' (page_size=%s)", page_size)
    req = service.files().list(q=q, fields="nextPageToken,files(id,name,mimeType,size)",
                               orderBy="folder,name", pageSize=max(1, min(page_size, 200)),
                               pageToken=page_token)
    try:
        res = req.execute()
    except HttpError as exc:
        logger.warning("drive: list condivisi fallita: %s", _short_http_error(exc))
        raise
    entries = [{"id": f["id"], "name": f.get("name", "?"),
                "mimeType": f.get("mimeType", ""),
                "is_folder": f.get("mimeType") == FOLDER_MIME,
                "size": _to_int_or_none(f.get("size"))}
               for f in res.get("files", [])]
    logger.debug("drive: condivisi -> %d voci", len(entries))
    return {"entries": entries, "nextPageToken": res.get("nextPageToken")}


def _to_int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _http_status(exc: HttpError) -> int | None:
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _short_http_error(exc: HttpError) -> str:
    status = _http_status(exc)
    detail = str(exc)[:300]
    return f"HTTP {status}: {detail}" if status else detail


def _friendly_download_error(file_label: str, exc: Exception) -> str:
    """Messaggio esplicito per l'utente a partire dall'errore Drive grezzo."""
    if isinstance(exc, HttpError):
        status = _http_status(exc)
        if status == 401:
            return (f"{file_label}: sessione Google scaduta o revocata "
                    f"(HTTP 401) — riconnetti Drive e riprova")
        if status == 403:
            return (f"{file_label}: permesso negato da Google Drive "
                    f"(HTTP 403) — verifica condivisione/quota e riprova")
        if status == 404:
            return f"{file_label}: file non trovato su Drive (HTTP 404, spostato?)"
        if status == 429:
            return (f"{file_label}: quota Google Drive esaurita "
                    f"(HTTP 429) — attendi e riprova")
        if status and status >= 500:
            return (f"{file_label}: errore lato Google "
                    f"(HTTP {status}) — riprova più tardi")
        return f"{file_label}: errore Google Drive ({_short_http_error(exc)})"
    if isinstance(exc, TimeoutError):
        return (f"{file_label}: timeout dopo {DOWNLOAD_TIMEOUT_SEC}s — "
                f"connessione lenta o file molto grande, riprova")
    if isinstance(exc, ssl.SSLError):
        return (f"{file_label}: connessione sicura a Google interrotta ({exc}) — "
                f"spesso è proxy/VPN o scansione HTTPS dell'antivirus: "
                f"prova a disattivarli e riprova")
    return f"{file_label}: download fallito: {exc}"


def get_file_meta(service, file_id: str) -> dict[str, Any]:
    try:
        res = service.files().get(fileId=file_id,
                                  fields="id,name,mimeType,size").execute()
    except HttpError as exc:
        logger.warning("drive: meta di '%s' illeggibile: %s", file_id,
                       _short_http_error(exc))
        raise
    return {"id": res["id"], "name": res.get("name", "?"),
            "mimeType": res.get("mimeType", ""),
            "is_folder": res.get("mimeType") == FOLDER_MIME,
            "size": _to_int_or_none(res.get("size"))}


def expand_selection(service, file_ids: list[str],
                     folder_ids: list[str]) -> tuple[list[dict], list[dict]]:
    """Espande la selezione: cartelle ricorsive (BFS, nomi ordinati per stabilita').

    Ritorna (media[{id,name,mimeType}], skipped[{id?,name?,reason}]).
    I formati non supportati non bloccano gli altri (architettura sez. 5).
    """
    media: list[dict] = []
    skipped: list[dict] = []
    queue: deque[str] = deque(folder_ids)
    visited: set[str] = set()
    touched = 0
    logger.info("drive: espansione selezione (%d file, %d cartelle)",
                len(file_ids), len(folder_ids))

    for fid in file_ids:
        try:
            meta = get_file_meta(service, fid)
        except HttpError as exc:
            skipped.append({"id": fid, "reason": f"non leggibile: {_short_http_error(exc)}"})
            logger.warning("drive: file '%s' non leggibile, saltato", fid)
            continue
        if meta["is_folder"]:
            queue.append(meta["id"])
        elif is_supported_media(meta["mimeType"]):
            media.append(meta)
        else:
            reason = _unsupported_reason(meta)
            skipped.append({"id": meta["id"], "name": meta["name"],
                            "reason": reason})
            logger.info("drive: '%s' escluso (%s)", meta.get("name"), reason)

    while queue:
        fid = queue.popleft()
        if fid in visited:
            continue
        visited.add(fid)
        page = None
        while True:
            batch = list_children(service, fid, page_token=page, page_size=200)
            entries = sorted(batch["entries"], key=lambda e: e["name"].lower())
            for e in entries:
                touched += 1
                if touched > MAX_IMPORT_ITEMS:
                    skipped.append({"reason": f"limite di {MAX_IMPORT_ITEMS} elementi raggiunto"})
                    queue.clear()
                    break
                if e["is_folder"]:
                    queue.append(e["id"])
                elif is_supported_media(e["mimeType"]):
                    media.append(e)
                else:
                    reason = _unsupported_reason(e)
                    skipped.append({"id": e["id"], "name": e["name"],
                                    "reason": reason})
            page = batch.get("nextPageToken")
            if not page:
                break
    logger.info("drive: selezione espansa -> %d media, %d esclusi",
                len(media), len(skipped))
    return media, skipped


def _unsupported_reason(entry: dict) -> str:
    mime = entry.get("mimeType", "")
    if mime.startswith(GOOGLE_NATIVE_PREFIX):
        return (f"documento nativo Google ({mime}): aprilo in Drive ed "
                f"esportalo come immagine/video prima di importarlo")
    return f"formato non supportato ({mime})"


# --- download ---

def sanitize_filename(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._+() -]", "_", (name or "file").strip())
    base = base[:120] or "file"
    return base


def is_google_native(mime: str) -> bool:
    """Documenti nativi Google (Docs/Sheets/Slides/...): non hanno bytes
    scaricabili via files.get alt=media, richiederebbero export."""
    return mime.startswith(GOOGLE_NATIVE_PREFIX) and mime != FOLDER_MIME


def check_download_size(size: int | None, file_label: str) -> None:
    """Rifiuta prima di scaricare i file oltre il limite dell'app."""
    if size is not None and size > MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"{file_label}: file troppo grande "
            f"({_format_bytes(size)} > limite {_format_bytes(MAX_DOWNLOAD_BYTES)}): "
            f"riducilo o caricalo in parti più piccole")


def _format_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / 1024:.0f} KB"


def _execute_download(request, dest: Path,
                      num_retries: int = DOWNLOAD_CHUNK_RETRIES) -> int:
    """Download reale via MediaIoBaseDownload (mockabile nei test).

    Logga ogni chunk così un download lento resta tracciabile; gli errori
    HTTP grezzi vengono arricchiti dal chiamante (download_file).
    num_retries: tentativi interni per-chunk (stesso chunk ripreso con backoff).
    """
    chunks = 0
    with FileIO(str(dest), "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
        done = False
        while not done:
            try:
                status, done = downloader.next_chunk(num_retries=num_retries)
            except HttpError:
                logger.warning("drive: chunk #%d verso '%s' fallito",
                               chunks + 1, dest.name)
                raise
            chunks += 1
            if status is not None:
                logger.debug("drive: '%s' chunk #%d (%.0f%%)",
                             dest.name, chunks, (status.progress() or 0) * 100)
            elif chunks % 10 == 0:
                logger.debug("drive: '%s' chunk #%d…", dest.name, chunks)
    size = dest.stat().st_size
    logger.debug("drive: '%s' scaricato (%d chunk, %s)", dest.name, chunks,
                 _format_bytes(size))
    return size


def download_file(service, file_id: str, dest: Path) -> int:
    """Scarica il contenuto binario di un file (endpoint files.get alt=media).

    Controlli espliciti prima/durante il download così nessun fallimento è
    silenzioso: token scaduto, documento nativo Google, file oltre il limite,
    errori HTTP di Drive e file vuoti producono tutti eccezioni con messaggi
    chiari (l'agent li registra in errors[] senza bloccare gli altri file).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Best-effort: se il token salvato risulta scaduto/revocato lo segnaliamo
    # subito nei log; l'errore operativo resta il 401 mappato sotto.
    try:
        if load_credentials() is None:
            logger.warning("drive: token non valido prima del download di '%s' "
                           "(probabile 401: servirà riconnettere Drive)", file_id)
    except Exception as exc:  # mai bloccare il download per il check
        logger.debug("drive: check credenziali fallito: %s", exc)
    try:
        meta = get_file_meta(service, file_id)
    except Exception:
        raise
    label = meta.get("name") or file_id
    mime = meta.get("mimeType", "")
    if is_google_native(mime):
        raise ValueError(
            f"{label}: documento nativo Google ({mime}) non scaricabile "
            f"come file — esportalo da Drive in formato immagine/video")
    check_download_size(meta.get("size"), label)
    if meta.get("size"):
        logger.info("drive: download '%s' (%s, %s)", label, mime,
                    _format_bytes(meta["size"]))
    else:
        logger.info("drive: download '%s' (%s, dimensione sconosciuta)",
                    label, mime)
    request = service.files().get_media(fileId=file_id)
    try:
        size = _execute_download(request, dest)
    except Exception as exc:
        # Non lasciare file parziali che l'Intake scambierebbe per corrotti.
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        msg = _friendly_download_error(label, exc)
        logger.warning("drive: %s", msg)
        raise DriveDownloadError(msg, transient=is_transient_error(exc)) from exc
    if size <= 0:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise DriveDownloadError(f"{label}: Drive ha restituito un file vuoto")
    logger.info("drive: '%s' completato (%s)", label, _format_bytes(size))
    return size
