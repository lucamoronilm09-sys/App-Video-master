# AI Video Maker — v1.0.0

Slideshow automatico in stile "album/ricordo": foto e video (locali o da Google Drive) diventano un mp4 16:9 montato — Ken Burns dolce, solo dissolvenze incrociate, sincronizzato con la tua musica. Verticali mai croppati.

Architettura ad agenti + specifica completa: **`architettura-video-maker-ia.md`**.
Stato avanzamento: **`PROGRESS.md`** (M0–M8 + polish + coda job + packaging, suite 72/72).

## Requisiti (Windows)

- Python 3.11+, Node.js 22+, FFmpeg — tutti nel PATH
- `pip install -r backend/requirements.txt` (include numpy, pillow-heif, client Google Drive)

## Uso normale: 3 file

```bat
setup.bat   Archivio una tantum: controlla i prerequisiti, crea il venv,
            installa dipendenze Python/npm, build produzione frontend.

avvia.bat   Avvia backend :8000 + frontend :3000 e apre il browser.
            (avvia.bat --no-browser per uso headless)

ferma.bat   Ferma tutto (anche render ffmpeg orfani).
```

Poi apri http://localhost:3000 → Nuovo progetto → carica foto/video (+ audio) → riordina → Genera montaggio → Esporta → play/download.

## Avvio manuale (sviluppo)

```powershell
# Backend (porta 8000)
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Frontend dev (porta 3000)
cd frontend
npm run dev
```

Le operazioni lunghe (render, import Drive) girano in background: coda persistente
in `data/jobs/` (sopravvive al riavvio), un job alla volta, progress live via SSE
(`GET /projects/{id}/events`, snapshot con `jobs`) e `GET /jobs/{id}` per il poll.
Variante sincrona (vecchio comportamento) senza `?background=true`.

## Google Drive (opzionale)

1. Google Cloud Console: abilita Drive API, crea ID client OAuth "App web" con redirect `http://127.0.0.1:8000/api/drive/callback`
2. Nella pagina progetto, sezione Google Drive: incolla client_id/secret → Connetti → sfoglia e importa (cartelle ricorsive)

## Test

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
cd ..\frontend
npm run build
```

## Struttura

```
├── architettura-video-maker-ia.md   # specifica di prodotto + grafo agenti
├── PROGRESS.md                      # stato milestone
├── backend/
│   ├── app/
│   │   ├── agents/                  # un modulo per agente (firma async run(state)->state)
│   │   ├── api/routes.py            # REST: media, audio, edit, render, SSE, thumb
│   │   ├── api/drive.py             # REST: OAuth Drive + browse/import
│   │   ├── services/                # inspect media, feature audio, client Drive
│   │   ├── pipeline/orchestrator.py # esecutore DAG + loop QA (asyncio)
│   │   └── config.py
│   └── tests/                       # pytest (69 test, ffmpeg reale, Drive mockato)
├── frontend/src/                    # Next.js 15 + TS + Tailwind (timeline DnD, SSE, player)
└── data/projects/<id>/              # state.json + media/audio/output/thumbs (gitignored)
```
