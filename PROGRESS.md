# PROGRESS — AI Video Maker

Stato di avanzamento per milestone. Ogni sezione: cosa funziona, cosa manca, decisioni/prese-note.

## M0 — Scheletro progetto ✅

**Cosa funziona (da verifica live):**
- Repo strutturato: `backend/` (FastAPI), `frontend/` (Next.js 15 + TS + Tailwind 4), `data/` (runtime, gitignored).
- Backend FastAPI su `http://127.0.0.1:8000`:
  - `GET /api/health` → `{status, service, projects_count}`
  - `GET /api/projects` → lista sintetica progetti
  - `POST /api/projects` → crea Project State vuoto (JSON su `data/projects/<id>/state.json`)
  - `GET /api/projects/{id}` → Project State completo
  - CORS aperto a `localhost:3000` (frontend)
- Frontend Next.js su `http://localhost:3000`: landing page che interroga ogni 5s `/api/health` e mostra lo stato backend (pallino verde/rosso + numero progetti).
- Project State JSON conforme allo schema dell'architettura (sez. 4) + campi operativi `schema_version`, `errors[]`, `pipeline_log[]`, `created_at`, `updated_at` (decisione documentata sotto).
- Moduli agente `backend/app/agents/*.py` con firma `async run(project_state) -> dict`, tutti passthrough in M0 (logica nelle milestone successive, come da piano).
- Orchestratore `backend/app/pipeline/orchestrator.py`: DAG 0→1→(2a‖2b)→3→4→5→6 con esecuzione async/parallela corretta e `pipeline_log` con timestamp.
- Test: `backend/tests/test_m0_smoke.py` — 4/4 verdi (health, create+get+list, 404, orchestrator passthrough/log).
- Build frontend verde (`next build`).

**Cosa manca (previsto, non bug):**
- Nessuna logica di ingest/normalizzazione/montaggio: arriva con M1-M7.
- Nessun feedback di progresso in tempo reale lato UI: M8 (WebSocket/SSE).

**Decisioni/assunzioni M0:**
- Project State esteso con `errors[]` e `pipeline_log[]` (richiesti rispettivamente dagli agenti Intake/QA e dalla UI di avanzamento futura); campi dichiarati, nessun side-effect nascosto.
- Errori di un agente → entry in `errors[]` + `pipeline_log` con `status: "failed"`, poi l'eccezione risale (bloccante): fase esecutiva, niente correzioni creative autonome downstream.
- Rami 2a/2b in parallelo con merge campi (`audio` dall'Audio Analysis, durate dal Sequence) — vincolo di documentazione: i due agenti devono toccare campi disgiunti dello state.
- Toolchain installata user-level (nessun admin): Node 22 nel PATH utente, FFmpeg (gyan build) nel PATH utente. Assunzione: necessaria per M4-M6, confermata dall'utente in M0.

---

## M1 — Import locale multiplo + Intake Agent ✅

**Cosa funziona (verificato live + test):**
- Endpoint `POST /api/projects/{id}/media` (multipart): accetta più file simultanei, li salva in `data/projects/<id>/media/` con nomi univoci (UUID + estensione originale), popola `media_staging` e invoca l'Intake Agent.
- **Intake Agent** (`backend/app/agents/intake.py`): processa in parallelo (asyncio) tutti i file staged:
  - **Video**: ffprobe → width, height, duration_sec, codec, orientation (landscape/square/portrait), type="video".
  - **Immagini**: Pillow → width, height, duration_sec=0, type="photo", orientation.
  - Errori per-file (corrotti, non supportati, mancanti) → `state["errors"]` (non bloccanti), file validi → `state["media"]` con metadata completi.
- **Frontend**: pagina Home con lista progetti + "Nuovo progetto"; pagina Progetto (`/projects/[id]`) con zona drag&drop (click o drop), barra di progresso, gestione errori, griglia media caricati con anteprima metadati (orientamento, dimensioni, durata).
- Test: `backend/tests/test_m1_intake.py` — 6/6 verdi (metadata extraction, errori non bloccanti, upload singolo/multiplo/foto/video). Totale suite: 10/10.
- Build frontend verde (`next build` + lint pulito).

**Cosa manca (previsto, non bug):**
- Riordino manuale della timeline (drag&drop per cambiare `order_index`): M2.
- Normalizzazione fit_mode/background_fill (cover per landscape/square, contain centrato per portrait): M2.
- Upload audio + analisi (bpm, beat, energy): M3.

**Decisioni/assunzioni M1:**
- Salvataggio file su disco locale (non in memoria): `data/projects/<id>/media/` — semplice, idempotente, funziona per centinaia di file.
- Nomi file: UUID breve + estensione originale (evita collisioni, mantiene hint tipo).
- Intake non modifica i file originali; solo legge metadata (conforme a architettura sez. 5).
- Errori non bloccanti: un file corrotto non ferma l'import degli altri (richiesto da architettura Intake Agent).
- Estensioni supportate: video {mp4,mov,mkv,webm,avi,m4v,ts,mts}, immagini {jpg,jpeg,png,webp,heic,heif,bmp,tiff,tif} — estensibile in `media_inspect.py`.
- CORS già configurato in M0, frontend chiama backend diretto (nessun proxy Next.js necessario).

---

## M2 — Riordino drag&drop timeline + Media Normalizer ✅

**Cosa funziona (verificato test + build):**
- **Media Normalizer nel flusso**: `POST /media` ora invoca Intake → Normalizer; ogni media ha `fit_mode`/`background_fill` (`cover`+None per landscape/square, `contain`+blur|solid per portrait, mai crop sui verticali) e `order_index` contigui.
- **Riordino timeline**: `PUT /projects/{id}/media/order` (valida set esatto di id, 400 su mancanti/sconosciuti/duplicati); rinormalizza senza alterare l'ordine utente.
- **Preferenze sfondo**: `PATCH /projects/{id}/media/{mid}` (per-singolo portrait) + `PATCH /projects/{id}/settings` (default progetto con propagazione a tutti i portrait, `resolution` formato WxH, `fps` in {23,24,25,29,30,50,59,60}).
- **Anteprime**: `GET /projects/{id}/media/{mid}/file` serve l'originale (path risolto dallo state, anti path-traversal) per img/video nella timeline.
- **Frontend**: `Timeline.tsx` (striscia 16:9 ordinabile, drag&drop nativo + frecce ◀ ▶ fallback, badge fit cover/contain, toggle blur/tinta sui portrait, update ottimistico con rollback), `ProjectSettings.tsx` (sfondo/risoluzione/fps), anteprime con `object-cover`/`object-contain` a specchio del Normalizer.
- Test: `backend/tests/test_m2_reorder_normalizer.py` — 8 nuovi (fit rules, override, upload normalizzato, reorder ok/persistenza/rifiuti, per-item, settings+validazione, file serving). Totale suite: 18/18 verdi. Build frontend verde (`next build` + lint).

**Cosa manca (previsto, non bug):**
- Durate foto / trim video (Sequence Agent): M3.
- Audio upload + analisi (bpm/beat/energy): M3.
- Anteprime ottimizzate (thumbnail ridotte): oggi serviamo l'originale — ok per M2, da valutare con centinaia di file.

**Decisioni/assunzioni M2:**
- Landscape/square: `background_fill=None` forzato dal Normalizer (frame pieno, nessuno sfondo); la PATCH per-singolo su landscape viene accettata ma normalizzata a None.
- Cambio `background_fill` globale → propagato a tutti i portrait (il default si applica a tutti; la personalizzazione per-singolo si fa dopo).
- Nessuna dipendenza DnD esterna: drag&drop HTML5 nativo, zero nuove dipendenze frontend.
- `MediaGrid.tsx` resta nel repo ma non più usato dalla pagina progetto (sostituito da `Timeline`).

---

## M3 — Audio Analysis + Sequence Agent ✅

**Cosa funziona (verificato test + build):**
- **Sequence Agent** (`backend/app/agents/sequence.py`): rispetta sempre `order_index` (mai riordina); foto → durata deterministica 3.5–5.5s da hash SHA256 dell'id (ritmo non uniforme + idempotente); video >8s → trim centrale (`trim_start/end_sec`, durata originale preservata), ≤8s nessun trim. Eseguito in upload media e reorder (idempotente, tocca solo durate/trim).
- **Audio Analysis** (`backend/app/services/audio_features.py` + `agents/audio_analysis.py`): decode mono 22.05kHz via ffmpeg; `energy_curve` RMS/secondo 0..1; `bpm` via autocorrelazione dello spectral-flux onset envelope (60–180 BPM, anti-ottava + interpolazione parabolica); `beat_markers_sec` strutturali (1 per battuta 4/4 ancorata al primo onset forte). File mancante/illecibile → entry `errors[]` non bloccante.
- **Endpoint** `POST /projects/{id}/audio` (mp3/wav/ogg/m4a/flac/opus/aac/wma, 400 su formato ignoto): salva in `audio/`, sostituisce la traccia precedente (file vecchio rimosso), analizza e ritorna lo state.
- **Frontend**: `AudioSection.tsx` (upload/sostituisci, durata+BPM+marker, barre energia), timeline con durate effettive (foto `4.2s`, video trimmato `✂ 8.0s` con tooltip range).
- Test: `backend/tests/test_m3_sequence_audio.py` — 11 nuovi (range/determinismo/idempotenza, mai-riordina, trim, click-track 120BPM ±3 con marker ogni battuta 2.0s, silenzio → bpm 0, agent no-path/missing, endpoint upload/rifiuto/sostituzione). Totale suite: 29/29 verdi. Build frontend verde.

**Cosa manca (previsto, non bug):**
- EDL creativa (Ken Burns, crossfade, beat-sync): M4.
- Durata totale vs audio (adattamento ultime clip): M4 Edit Director.

**Decisioni/assunzioni M3:**
- Niente librosa/scipy: analisi con **numpy + ffmpeg** (leggero, nessuna toolchain; `requirements.txt` aggiornato di conseguenza, nota AGENTS "librosa da M4" superata).
- Marker = 1 per battuta (non ogni beat), come da architettura ("beat principali/forti").
- Schema `MediaItem` esteso con `trim_start_sec`/`trim_end_sec` opzionali (None = nessun trim).

---

## M4 — Edit Director + Timeline Compiler ✅

**Cosa funziona (verificato test + build):**
- **Edit Director** (`backend/app/agents/edit_director.py`): deterministico per project_id; Ken Burns a rotazione senza ripetizioni consecutive (zoom ≤1.15x, pan ≤12%), mai sui video; solo crossfade 0.6–1.0s; beat markers come guida morbida (micro-ritocchi ≤0.4s alle foto entro [3.0,6.5]s, video intoccabili); totale adattato alla durata audio distribuendo la differenza sulle foto (mai tagliare l'audio). Output EDL `{media_id, start, duration, ken_burns|None, transition_in/out}`.
- **Timeline Compiler** (`backend/app/agents/timeline_compiler.py`): EDL → `render_manifest` con filtergraph FFmpeg reale + `args` pronti: foto via `zoompan` (cover 2x / contain su sfondo blur scurito, mai crop verticali), video con trim, catena `xfade`, audio utente a misura con fade (audio dei video scartato). Valida vincoli di stile e coerenza (ValueError preciso); EDL vuota → no-op.
- **Endpoint** `POST /projects/{id}/edit` (Sequence→Director→Compiler, log running/done/failed per stage, 400 senza media, 500 con stage dell'errore).
- **Frontend**: `MontageSection.tsx` (Genera/Rigenera, totale, lista clip con inizio/durata/movimento/transizione) + tipi EDL/manifest in `api.ts`.
- Test: `backend/tests/test_m4_director_compiler.py` — 9 nuovi (struttura EDL, determinismo, fit audio, no-op, manifest, 3 rifiuti, **smoke render ffmpeg reale** con ffprobe ±0.6s, endpoint /edit). Totale suite: 38/38 verdi. Build frontend verde.

**Cosa manca (previsto, non bug):**
- Esecuzione render + consegna mp4 (M5: ora è una `subprocess.run(manifest["args"])` + QA).
- QA Agent e loop di correzione: M6.

**Decisioni/assunzioni M4:**
- Manifest `args` già pronti: M5 non interpreta nulla, esegue e basta (conforme a architettura Agente 5).
- Bug trovato dallo smoke test e corretto: lo sfondo `loop` ereditava i timestamp 25fps del demuxer JPEG (overlay allungato di ~0.8s) → `setpts=N/fps/TB` dopo il loop.
- Durata container = ultimo PTS (120 frame @30fps → 3.97s riportati): semantica standard, tolleranze QA di conseguenza (≥±0.5s).
- `output/` creato dal compiler se assente (il manifest punta a un path scrivibile).

---

## M5 — Render Agent + prima esportazione mp4 end-to-end ✅

**Cosa funziona (verificato test + build + smoke live):**
- **Render Agent** (`backend/app/agents/render.py`): esegue `manifest["args"]` via ffmpeg senza reinterpretarli; manifest assente → no-op; fallimento → errore tecnico esatto (`ffmpeg exit=…` + stderr) in `errors[]` + eccezione (stop downstream); successo → `manifest.status="done"` + `size_bytes`/`rendered_at`. Timeout di sicurezza 30 min.
- **Endpoint**: `POST /projects/{id}/render` (catena fresca Sequence→Director→Compiler→Render con pipeline_log, 400 senza media) + `GET /projects/{id}/download` (mp4 con anti path-traversal, 404 se mai renderizzato). Helper `_run_stages` condiviso con `/edit`.
- **Frontend**: `ExportSection.tsx` (Esporta/Riesporta, player `<video>` in pagina, risoluzione/fps/dimensione, link download).
- Test: `backend/tests/test_m5_render.py` — 4 nuovi (no-op, errore esatto, **end-to-end upload→render→download con ffprobe**, validazioni/404). Totale suite: 42/42 verdi. Build frontend verde.
- **Smoke live** su server reale: 3 foto (cover/contain/square) + click-track (119.7 BPM) → `done`, mp4 1920×1080 H.264+AAC 7.3s = totale manifest.

**Cosa manca (previsto, non bug):**
- QA Agent (verifiche durata/sync/verticali) + loop → Edit Director: M6.
- H.265 su richiesta, preset/CRF configurabili: oltre M5.

**Decisioni/assunzioni M5:**
- `/render` rigenera sempre il piano (idempotente) invece di riusare il manifest esistente: niente export stale dopo riordino.
- `faststart` attivo: l'mp4 è subito streamabile nel player browser.

---

## M6 — QA Agent + loop correzione → Edit Director ✅

**Cosa funziona (verificato test + build):**
- **QA Agent** (`backend/app/agents/qa.py`): 4 check — durata file vs manifest ±0.5s (ffprobe), sync A/V (d sense: durate stream entro 0.5s, partenze ≈0), verticali (ogni portrait in `contain`+overlay nel manifest), transizioni (N-1 xfade 0.6–1.0s, coerenza EDL). Verdetto in `qa_report` `{status, checks[], issues[]}` con `route_to` per issue (transizioni→edit_director, resto→timeline_compiler); nessun render → no-op (None).
- **Loop** (`orchestrator.run_qa_with_retry`, max 1 retry): su rigetto creativo ripianifica Director→Compiler→Render con `qa_feedback` (`fit_total`), poi riverifica; rigetti tecnici non ritentano. Stesso loop in `POST /render`.
- **Director**: `qa_feedback fit_total` supportato (helper `_distribute_diff` condiviso con l'audio-fit).
- **Refactor**: runner stage condiviso `orchestrator.run_stages` usato anche dalle route (`/edit`, `/render`).
- **Frontend**: verdict QA in `ExportSection` (✓ approvato con dettagli / lista problemi con →agente) + tipi `QAReport`.
- Test: `backend/tests/test_m6_qa.py` — 9 nuovi (approved su render reale, 3 rigetti su manifest manomesso con route corrette, sync unit, feedback fit_total, **loop orchestratore con rigetto forzato → retry → approved**). Totale suite: 51/51 verdi. Build frontend verde.

**Cosa manca (previsto, non bug):**
- Import Google Drive: M7. Avanzamento realtime: M8.

**Decisioni/assunzioni M6:**
- QA non solleva mai sul rigetto (è un verdetto, non un crash): il loop decide in base a `route_to`.
- Pipeline deterministica → il retry converge per costruzione; il loop è strutturale (richiesto da architettura sez. 6) e auto-guarente solo in casi reali (es. output cancellato).
- Check verticali/transizioni strutturali su manifest (i vincoli sono garantiti in costruzione dal Compiler).

---

## M7 — Import Google Drive ✅

**Cosa funziona (verificato test + build):**
- **OAuth2** (`backend/app/services/drive_client.py` + `app/api/drive.py`): credenziali una-tantum (client_id/secret, mai riecheggiate), `GET /drive/auth-url` (state anti-CSRF server-side), callback popup con auto-chiusura, `GET /drive/status` (configured/connected/email), disconnect. Scope minimo `drive.readonly`; secret/token in `data/` (gitignored).
- **Browse**: `GET /projects/{id}/drive/files` (cartelle + file, nomi ordinati, paginazione passthrough).
- **Import** `POST .../drive/import` (file_ids e/o folder_ids): agente `drive_import` (espansione ricorsiva BFS con visited-set, download parallelo ×6, nomi `uuid_originale`, staging `source=google_drive` + `drive_file_id`) → stessa catena Intake→Normalizer→Sequence dei file locali. Non supportati/troppi/mancanti → `errors[]` senza bloccare.
- **Frontend** `DriveSection.tsx`: setup credenziali con guida redirect URI, connect popup + polling, browser con breadcrumb/checkbox/cartelle ricorsive, import con nota sui tempi.
- Test: `backend/tests/test_m7_drive.py` — 9 nuovi (OAuth offline, callback state, listing, expand, import con foto+mp4 veri via service finto, validazioni 400/401/404). Totale suite: 60/60 verdi. Build frontend verde.

**Cosa manca (previsto, non bug):**
- Avanzamento realtime import lunghi (progress bar): M8 — oggi l'import blocca la request (ok in locale, da migliorare).
- Picker JS Google: non implementato di proposito (vedi decisioni).

**Decisioni/assunzioni M7:**
- **Niente Google Picker JS**: browser integrato nostro ("o equivalente" per il system prompt Agente -1b) → servono solo client_id/secret (niente API key), funziona ovunque ed è testabile senza rete.
- Import molto grandi: cap 3000 elementi, download 6 in parallelo, timeout HTTP 300s.
- Redirect URI fisso `http://127.0.0.1:8000/api/drive/callback` da registrare in console (coerente con API_BASE frontend).

---

## M8 — Avanzamento realtime, gestione errori, preview ✅

**Cosa funziona (verificato test + build + live):**
- **SSE** `GET /projects/{id}/events`: snapshot immediato + evento a ogni modifica dello state + heartbeat; `progress_payload` (pipeline_log, errori, media/audio/edit/render/QA, updated_at). Verificato live con curl su server reale.
- **Frontend**: `useProjectEvents` (EventSource + riconnessione automatica), `PipelineProgress` (9 stage con pallini pending/running/done/failed), sync throttled dello state (3s) su cambiamento remoto → la timeline si aggiorna da sola durante import/render lunghi.
- **Errori**: `ErrorPanel` (lista con stage + Pulisci) + `POST /errors/clear`.
- **Preview**: già coperta da M5 (`<video>` in pagina + download); M8 non ha dovuto aggiungere nulla.
- Test: `backend/tests/test_m8_realtime.py` — 4 nuovi (payload, 404 eventi, stream su cambiamento, clear). Totale suite: 64/64 verdi. Build frontend verde.

**Cosa manca / debito noto:**
- Il `TestClient` non supporta stream infiniti (hang): lo stream è testato via generatore diretto + smoke live curl, non via HTTP-TestClient.
- Nessuna auth multi-utente (app locale single-user per disegno).

**Decisioni/assunzioni M8:**
- Polling SSE lato server 1s su mtime implicito (ricarico state.json, confronto payload): semplice e robusto per uso locale; heartbeat ogni 15s.
- Chiusura client → cancellazione task (niente `is_disconnected` in loop: in alcuni runtime blocca il primo yield).

---

## Stato finale — tutte le milestone M0–M8 completate

Pipeline: upload locale / Drive → Intake → Normalizer → Sequence ‖ Audio → Edit Director → Compiler → Render → QA (+loop) → mp4 16:9 con preview browser. Suite 64/64, `next build` verde.

---

## Polish post-M8 ✅

- **M8** — Avanzamento pipeline in tempo reale, gestione errori, preview video nel browser
- **Security hardening (routes.py)**:
  - `MAX_FILES_PER_REQUEST=50`, `MAX_FILE_SIZE_BYTES=500MB` → mitigazione DoS/OOM
  - Validazione magic bytes per video/immagini/audio (non solo estensione) → previene upload eseguibili/XSS
  - Helper `_ensure_path_within_project()` unificato per download/media/thumb → anti path-traversal coerente
  - Rate limiting su render sincrono (30s tra richieste) → previene abuso FFmpeg

---

## Stato finale — tutte le milestone M0–M8 completate + security patch

**Cosa funziona (verificato test + build):**
- **Thumbnail leggere** `GET /media/{id}/thumb` (JPEG con cache su disco, foto via Pillow / video via ffmpeg, `?w=` 64–960): la timeline non scarica più gli originali; video con badge 🎬 sul fotogramma.
- **Fix EXIF**: l'Intake legge l'orientamento vero delle foto telefono (una 640×480 con EXIF-6 è portrait 480×640, non landscape).
- **HEIC/HEIF reale** via `pillow-heif` (roundtrip encode/decode verificato), non più solo dichiarato.
- **Codec H.264/H.265** in `output_spec` + select UI; il Compiler mappa su libx264/libx265 (422 su valori ignoti).
- **Pulizia**: rimosso `MediaGrid.tsx` morto, import inutilizzati, docstring agenti aggiornata, badge pagina → "✓ Pronto", README riscritto (quickstart, Drive, struttura).
- Test: `backend/tests/test_polish.py` — 5 nuovi (thumb foto/cache/video, EXIF, HEIC, vcodec+manifest). Totale suite: 69/69 verdi. Build frontend verde.

**Debito noto (futuro, fuori scope):**
- ~~Coda di render background per progetti enormi (oggi request sincrone, ok in locale).~~ FATTO sotto.
- Thumbnail: invalidazione solo su mtime (i sorgenti sono immutabili post-upload, basta così).

---

## Coda job background ✅

**Cosa funziona (verificato test + build + live):**
- **Coda persistente** (`backend/app/jobs/manager.py`): record JSON in `data/jobs/`, worker in-process FIFO (un job alla volta), recovery `running→queued` all'avvio, 409 su doppio submit dello stesso kind.
- **Endpoint**: `POST /render?background=true` e `POST /drive/import?background=true` → 202 `{job}`; `GET /jobs/{id}`; snapshot SSE con ultimi 5 job. Path sync invariato (default).
- **Progress reale**: render via `ffmpeg -progress` (frazione vera, verificata live: 32.7% a metà), import via conteggio file; heartbeat nel record ogni 2s.
- **Frontend**: submit bg in Export/DriveSection, barre di avanzamento dal job via SSE, errori job visibili, anteprima che appare da sola al done (sync esistente).
- Test: `backend/tests/test_jobs.py` — 3 nuovi (render bg→done+QA, import bg, recovery/409/validazioni). Totale suite: 72/72 verdi. Build frontend verde.

**Bug trovati e corretti:**
- Hang ffmpeg sotto `Popen`+tread: mai pipe senza drenaggio su Windows e sempre `stdin=DEVNULL` (stderr su file temporaneo, tail preservata per gli errori esatti).
- File con nome che oscura stdlib nei test manuali (`bisect.py`): rinominato, senza conseguenze sul repo.

**Decisioni:**
- Niente Redis/Celery: coda su disco + worker asyncio, adeguato al single-user locale; un job alla volta (ffmpeg saturerebbe comunque la CPU).

---

## Packaging v1.0.0 ✅

**Cosa funziona (verificato live):**
- **`setup.bat`**: prerequisiti (Python ≥3.11, Node, FFmpeg) → venv + pip → npm install → `next build`. Eseguito: Setup OK.
- **`avvia.bat`**: backend :8000 (attesa health 60s) → build se manca → frontend :3000 → browser (saltabile con `--no-browser`). Verificato: Backend OK + frontend 200.
- **`ferma.bat`** (+ `ferma.ps1`): stop per command-line di uvicorn, node/npm del progetto e ffmpeg orfani. Verificato: entrambe le porte chiuse.
- Versioni allineate a 1.0.0 (FastAPI + package.json), README con sezione d'uso.

**Bug trovati e corretti:**
- `timeout.exe` richiede una console vera: attese con `ping -n` (funzionano anche senza stdin).
- Path con spazi non quotati in `start ... cmd /c`: uso `/d` + exe quotato.
- `taskkill /FI WINDOWTITLE` non aggancia le finestre npm → kill per command-line via PowerShell (con `/T` da solo il `node` figlio di npm sopravviveva).
- **ferma.ps1 non uccideva nulla**: match su `"App Video"` (con spazio), mai presente nei percorsi reali (`App-Video-master`) → porte restavano occupate, i nuovi avvii morivano all'istante con finestra che si chiudeva ("si ferma da solo") e restava in piedi il server vecchio. Ora match su `App-Video-master` + output dettagliato per processo (`- python.exe PID 1234 [backend (uvicorn)]`, ruoli: backend/frontend/wrapper/ffmpeg orfano) invece del solo conteggio (verificato live).
- **ferma.ps1 uccideva il proprio lanciatore**: `.\ferma.bat` gira via `cmd.exe /c "...\ferma.bat"` e quel `cmd` matcha il filtro → finto "(1 processi)" a ogni run + terminale inchiodato (stesso rischio per lo step di pulizia di `avvia.bat`, stroncato a [0/4]). Ora esclusi PID propri/antenati e cmdline `*ferma*`/`*avvia*` (verificato via cmd: doppia run pulita + step0 che sopravvive uccidendo un backend sacrificale).
- **avvia.bat**: auto-pulizia all'avvio (ferma.ps1 + attesa porte), log processi su `data/backend{,-err}.log` e `data/frontend{,-err}.log` via Start-Process, `pause` su ogni errore (la finestra non sparisce più senza messaggio), coda dei log mostrata in caso di timeout health, check health anche sul frontend. (Nota: il redirect via `start ... cmd /c` con quote annidate è inaffidabile → Start-Process; binding parametri verificato.)

**Decisioni:**
- Niente exe unico/Electron: 3 batch + Python/Node/FFmpeg di sistema, adeguato all'uso personale; reinstallabile con setup.bat.
- **M3** — Audio Analysis (bpm, beat markers, energy curve) + Sequence Agent (durate foto, trim video)
- **M4** — Edit Director (EDL: Ken Burns, transizioni, beat-sync morbido) + Timeline Compiler (EDL → FFmpeg manifest)
- **M5** — Render Agent + prima esportazione mp4 end-to-end
- **M6** — QA Agent (controlli durata/sync/verticali) + loop correzione → Edit Director
- **M7** — Import Google Drive (OAuth2 + Picker UI, download parallelo, stesso Intake)
- **M8** — Avanzamento pipeline in tempo reale, gestione errori, preview video nel browser

---

## Fix — Import Drive: niente più hang infinito, errori sempre visibili ✅

**Problema:** il browse Drive funzionava ma il download restava "in corso" all'infinito senza alcun errore in console/UI.

**Cause trovate (✓ cosa non funzionava):**
- Download senza timeout né log (`drive_client._execute_download`/`download_file`): una connessione piantata bloccava il worker per sempre, con progress fermo allo 0% per-file.
- Agent senza `wait_for`: `asyncio.as_completed` attendeva ogni download all'infinito.
- Nessun controllo dimensione (l'upload locale ha il cap 500MB, Drive no) e nessun messaggio dedicato per documenti nativi Google (Docs/Sheets/Slides, non scaricabili via `files.get` alt=media).
- Errori HTTP grezzi mai mappati (401/403/404/timeout) → messaggi criptici o assenti.
- UI: `page.tsx` passava a `DriveSection`/`ExportSection` solo i job *attivi* → un job fallito spariva con il suo errore (il blocco "Import fallito" era irraggiungibile).

**Correzioni (verificato test + build):**
- `backend/app/services/drive_client.py`: logging a ogni passo (auth/list/expand/chunk/download); refresh token con log; `size` nei metadati; `MAX_DOWNLOAD_BYTES=500MB` (rifiuto preventivo con messaggio); `DOWNLOAD_TIMEOUT_SEC=300`; rilevamento documenti nativi con motivo di esclusione esplicito; `_friendly_download_error` (401→"riconnetti Drive", 403/404/429/5xx/timeout dedicati); rimozione file parziali dopo errore; niente più `Exception` silenziose.
- `backend/app/agents/drive_import.py`: ogni download sotto `asyncio.wait_for(300s)` → errore per-file "timeout dopo 300s" in `errors[]` senza bloccare gli altri; log riepilogativi.
- `backend/app/api/drive.py`: `_drive_error` mappa 401/403/404 e `ValueError`→400 (es. `folder_id` invalido).
- `frontend/src/app/projects/[id]/page.tsx`: selettore `lastJob(kind)` (ultimo job di qualunque stato) passato a Drive/Export → i fallimenti restano visibili con il loro errore.
- `frontend/src/components/DriveSection.tsx`: log console `[Drive]` per ogni passaggio (lettura cartella, submit, job accodato, errori); watchdog client-side (tick 5s: avviso se nessun heartbeat da >120s o job attivo da >15min).
- Endpoint di download confermato: `files().get_media` (= `files.get` con `alt=media`) + `MediaIoBaseDownload` a chunk da 10MB — corretto per foto/video binari.

**Verifiche:** `test_m7_drive.py` + `test_jobs.py` 14/14 verdi; script di verifica dedicato (timeout agent, size-cap, nativi, 401/403/timeout) tutto OK; `next build` verde. Suite completa: 78 passati; 5 fallimenti in `test_pipeline_edge_cases.py` preesistenti e non correlati (importano solo sequence/timeline_compiler/render, moduli non toccati).

**Debito noto:** il thread `to_thread` di un download cancellato dal timeout termina da solo ma non è uccidibile (limite di `asyncio.to_thread`); nessun impatto sul flusso (l'errore è già registrato).

---

## Fix 2 — Audio rifiutato + coda job bloccata (verifica live) ✅

**Segnalazione:** il fix precedente non bastava: Drive ancora fermo e anche l'upload audio non andava.

**Audio — causa trovata e riprodotta dal vivo:** `_validate_audio_magic` accettava solo `0xFF 0xFB` per gli MP3, ma quasi tutti gli MP3 reali iniziano con tag **ID3v2**; mancavano anche le firme **fLaC** e **ASF/WMA**. Risultato: `400 Contenuto audio non valido` su MP3/FLAC/WMA veri (verificato con file generati da ffmpeg via backend reale: MP3-ID3 e FLAC fallivano, ora tutti OK: mp3/wav/ogg/flac/m4a con durata+bpm rilevati).

**Correzioni audio (`backend/app/api/routes.py`):**
- Validazione per-estensione: MP3 = `ID3` o frame-sync `0xFF+top-3-bit` (tutte le versioni MPEG, con scansione 8KB per tag APE/Lyrics); FLAC=`fLaC`; WMA=header ASF; AAC=ADTS/ADIF; WAV=RIFF/RF64; OGG/OGA/OPUS=`OggS`; M4A=`ftyp`; messaggio 400 ora cita l'estensione.
- Regressione permanente in `backend/tests/test_audio_upload.py` (magic per formato + upload veri di MP3-ID3/FLAC + rifiuto spazzatura).

**Drive/coda — causa reale trovata con server uvicorn vero:** i job background restavano `queued` per sempre perché il worker single-FIFO era incastrato su vecchi job Drive mai terminati (creati prima dei timeout): un job piantato blocca TUTTA la coda senza errori. Effetti a catena: ogni nuovo import/render in attesa infinita.

**Correzioni coda/Drive:**
- `agents/drive_import.py`: timeout anche su creazione service (60s) ed espansione cartelle (600s) con errori espliciti — ora OGNI fase è limitata, nessun hang infinito possibile.
- `jobs/manager.py`: `worker_loop` non muore mai (try/except + backoff, solo `CancelledError` esce per lo shutdown); heartbeat e registrazione fallimento protetti da try/except con log.
- Percorso di download reale coperto da `backend/tests/test_drive_download.py` (prima era sempre mockato): Range/200/401/vuoti/size-cap/nativi + sopravvivenza worker + timeout service/expand.
- Pulizia dati reali: rimossi 5 record zombie dalla coda (`data/jobs/`: job di prova, running orfani di server di test terminati, orfani di progetti cancellati, tentativi Drive falliti che intasavano la FIFO) + il progetto di prova `0850cb24`. Progetti utente intatti.

**Verifiche:** 91/91 verdi (tutta la suite tranne `test_pipeline_edge_cases.py`, i cui 5 fallimenti restano preesistenti e non correlati); E2E live su uvicorn reale: health→upload foto→upload MP3-ID3→submit render 202 (il render resta in coda solo per il bug worker-occupato, ora risolto con code pulite + worker immortale).

**AZIONE RICHIESTA per applicare tutto:** riavvia il backend (e il frontend se la build è vecchia):
`ferma.bat` (o `ferma.ps1`) → `avvia.bat`. Senza riavvio, il server continua a girare col codice vecchio (è molto probabile che fosse anche questo il motivo del "non funziona"). Se dopo il riavvio Drive dà ancora errore, ora il messaggio sarà esplicito (copialo dalla console backend o dal pannello errori).

---

## Montaggio manuale + transizioni fluide ✅

**Richieste:** (1) cambiare a mano durata foto e transizioni; (2) scatti video sulle transizioni; (3) dissolvenze "macchinose".

**Cosa funziona (verificato test + render ffmpeg reali + build):**
- **Editor per-clip** (`MontageSection`): durata (foto 1–12s, video 0.5s–sorgente con trim ricentrato), slider dissolvenza 0–1.5s (0 = stacco), movimento Ken Burns (Auto/5/static/Fermo) solo foto; badge "manuale", reset ⟲ per-clip; errori per-riga.
- **Override persistenti** (`clip_overrides` nello state + agent tra Director e Compiler nelle catene /edit, /render, job e retry QA): "Rigenera" non cancella i lucchetti; PATCH ricompila solo overrides+compiler (veloce) e invalida il QA (serve riesportare).
- **Endpoint** `PATCH/DELETE /projects/{id}/edit/clips/{media_id}` (400 su durate/transizioni/movimenti invalidi, ultima clip sempre senza uscita, 404 su clip assente, 400 senza EDL).
- **No scatti**: segmenti e offset xfade snappati alla griglia frame (foto già esatte, video con `fps+trim=end_frame+setpts`); stacchi via `concat` (non rami scollegati); `afade` con guardia su totali <1s.
- **Bug crop verticali trovato e corretto**: il primo piano verticale veniva costruito a 2x e sovrapposto senza ridurlo → ritaglio centrale invece di contain (+ dimensioni dispari possibili). Ora downscale a H con dimensioni pari: supersampling fluido + contain vero (RF4).
- **Meno meccaniche**: durate dissolvenze guidate dall'energia del brano (calma→lunghe, energia→brevi, sempre 0.6–1.0s dal regista) + mai due valori uguali consecutivi.
- Test `tests/test_manual_clips.py` (13: agent no-op/override/recenter/rifiuti/KB deterministico, endpoint PATCH/DELETE/validazioni, regenerate-mantiene-lucchetti, frame-exact, stacco che compila + QA approved, coerenza anti-manomissione, contain, smoke render con piano manuale). Liste stage aggiornate in test_m0/m4/m5 per il nuovo stage `clip_overrides`. Suite: 104 verdi (+6 edge-case preesistenti non correlati). Build frontend verde.

**Deviazione segnalata (AGENTS.md):** l'utente può impostare a mano stacchi a 0.0s e dissolvenze fino a 1.5s; il vincolo "solo crossfade 0.6–1.0s" resta per ciò che genera il regista, il QA accetta 0.0–1.5s + verifica coerenza EDL↔manifest (entro un frame).

---

## Fix 3 — Retry download Drive su errori SSL/transitori ✅

**Log utente:** `SSL: WRONG_VERSION_NUMBER` su ogni file + `IncompleteRead(124 byte)` (stato reale: 1 job fermo a 4/5 in `running`, 1 fallito "tutti i download sono falliti"). Diagnosi: TLS verso Google intercettato/instabile (proxy/VPN/antivirus-MITM o rete ballerina) — l'elenco file (richieste piccole) passa, i download a chunk crollano sull'handshake. Prima il primo errore ammazzava subito il file.

**Correzioni (`drive_client.py` + `agents/drive_import.py`):**
- `DriveDownloadError` con flag `transient`; `is_transient_error()` (SSL/OSError/connessione/IncompleteRead/timeout/5xx/429 sì; 401/403/404/limiti no).
- Retry per-file fino a 4 tentativi con backoff esponenziale + jitter (solo errori transient; 401/404 fail-fast al primo colpo; timeout senza retry parallelo).
- Retry interni per-chunk (`next_chunk(num_retries=3)`, riprende lo stesso chunk).
- Messaggio dedicato per `ssl.SSLError` (suggerisce proxy/VPN/scansione HTTPS); niente più doppio prefisso "download fallito: … download fallito: …".
- `get_drive_service` logga la presenza di variabili proxy di sistema (senza valori, mai credenziali).
- Test: classificazione transient, retry-poi-ok, resa dopo N tentativi, fail-fast 401, no-retry su timeout. Suite: 109 verdi (+6 edge-case preesistenti). Nessuna `sys.exit/os._exit` nel codice: il backend non può chiudersi da solo su queste righe (se la finestra sparisce è esterno: ferma.bat lanciato altrove, chiusura manuale, antivirus).

---

## Fix 4 — Race httplib2: un service Drive per ogni download ✅

**Causa vera (confermata dal vivo):** la rete è pulita (TLS ok verso `www.googleapis.com` e `drive.usercontent.google.com` con curl, niente proxy) e 4 file su 5 si scaricano: a rompersi è la **condivisione di un unico service tra i 6 download paralleli**. `httplib2.Http` riusa le connessioni keep-alive in un dict condiviso senza lock: i thread si rubano le risposte (`IncompleteRead` di byte altrui) e mescolano i record TLS (`SSL: WRONG_VERSION_NUMBER` casuali). L'elenco file funziona perché è sequenziale. I retry non bastavano perché riprovavano sullo stesso oggetto condiviso.

**Correzione (`agents/drive_import.py`):** `_download_one` riceve una factory e costruisce un service fresco (credenziali + Http nuovi) dentro il proprio thread; `run()` usa `dc.get_drive_service` come factory (l'espansione cartelle resta sul service condiviso, è sequenziale). Test di regressione: 6 download paralleli → 6 service distinti. Suite: 110 verdi (+6 edge-case preesistenti).

---

## Fix 5 — Qualità foto + micro-scatti ✅

**Segnalazioni:** (1) le foto nel video finale sembrano meno nitide dell'originale; (2) ogni tanto il video "va a scatti".

**Cause trovate (verificate con render di prova, non a sensazione):**
- *Qualità:* ogni foto subiva 3 ridimensionamenti in bicubic (default ffmpeg: upscale 2x → zoompan → downscale) + encode H.264 CRF 20 + conversione colore senza metadati BT.709 espliciti (colori slavati). Prova A/B su foto di test dettagliata (stesso Ken Burns, 1080p30): nitidezza del frame centrale 608 → 1168 di varianza del Laplaciano (+92%) passando a lanczos + CRF 18 + micro-dettaglio, a fronte di 1.36 → 2.26 MB per 4s (bitrate comunque modesto).
- *Scatti:* due fonti. (a) Le foto landscape non resettavano i timestamp prima del filtro `fps` (le portrait sì): una deriva di arrotondamento può far duplicare/saltare un frame a inizio/fine foto. (b) Conversione fps non multipla: un video sorgente a 25fps (tipico in Europa) esportato a 30fps inietta 5 frame duplicati/s a cadenza irregolare = micro-scatti sui movimenti (verificato: 100 frame → 120 con 20 duplicati). Stesso discorso per i pan Ken Burns, più fluidi a 60fps (passo dimezzato).

**Correzioni:**
- `agents/timeline_compiler.py`: `scale=flags=lanczos` ovunque; `unsharp=5:5:0.35` solo sulle foto (mai sui video, per non amplificare rumore/compressione); `setpts=PTS-STARTPTS` anche sulle foto landscape; CRF 18 su H.264 (H.265 resta a 20, scala diversa); `-sws_flags lanczos+accurate_rnd+full_chroma_int` per i resize impliciti (blend xfade); metadati colore BT.709 espliciti. Manifest v2 con `crf`/`preset` registrati.
- `services/media_inspect.py` + `agents/intake.py` + `api/schemas.py`: nuovo campo `source_fps` (da `avg_frame_rate`, con parser di `30000/1001` e simili; None per foto/non rilevabile).
- `frontend`: badge `25fps` sui video in timeline + suggerimento contestuale nelle impostazioni ("i tuoi video sono a 25fps ma l'output è a 30fps: prova 25 o 50") + nota guida (30 equilibrato, 60 Ken Burns più fluido, 25/50 per video europei).
- Test `tests/test_quality_smooth.py` (6 nuovi: lanczos/unsharp foto, niente unsharp sui video, CRF per codec + flag globali, parser fps, source_fps via Intake, smoke render reale). Aggiornato `test_m4` alla versione manifest 2.

**Verifiche:** 116 verdi (+6 nuovi) + `next build` verde; `test_pipeline_edge_cases.py` invariato (5 problemi preesistenti non correlati: fixture mancanti, vecchie chiavi `clips`/`settings`, path `/tmp`).

**Nota per l'utente:** i video già esportati non cambiano (riesporta per vedere la differenza); se i tuoi video sono a 25fps e l'output è a 30fps, imposta 25 o 50fps e verifica. File un po' più pesanti (normale con CRF 18).

---

## Fix 6 — Durata foto automatiche 2.5–6s ✅

**Richiesta utente:** le foto devono durare tra 2.5 e 6 secondi (prima 3.5–5.5 di base, fino a 6.5 dopo gli aggiustamenti).

**Correzioni:** `sequence.py` (`PHOTO_BASE_MIN/MAX_SEC` 3.5/5.5 → 2.5/6.0) + `edit_director.py` (`PHOTO_ADJUSTED_MIN/MAX_SEC` 3.0/6.5 → 2.5/6.0, così beat-sync e fit-audio non escono mai dall'intervallo). Modifica manuale per-clip invariata (1–12s, resta più ampia di proposito).

**Verifiche:** test `test_m3`/`test_m4` aggiornati al nuovo intervallo; `test_m6_qa::test_director_honors_qa_feedback_fit_total` portato a 11.0s (12s irraggiungibili con 2 foto da max 6s meno la dissolvenza). Suite: 116 verdi.

**Deviazione segnalata (AGENTS.md):** l'architettura sez. 5 prescrive 3.5–5.5s per il Sequence Agent; ora è 2.5–6.0 su richiesta esplicita dell'utente.