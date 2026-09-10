# AI Video Maker — v1.1.0

Slideshow automatico in stile "album/ricordo": foto e video (locali o da Google Drive) diventano un mp4 16:9 montato con Ken Burns, analisi Vision delle foto e sincronizzazione musicale.

Architettura ad agenti + specifica completa: **`architettura-video-maker-ia.md`**.
Stato avanzamento: **`PROGRESS.md`**.

## Requisiti (Windows)

- Python 3.11+, Node.js 22+, FFmpeg — tutti nel PATH
- `pip install -r backend/requirements.txt`
- Per il Vision AI locale è consigliato **Ollama** con almeno un modello vision-capable installato. Il backend lo rileva automaticamente.

## Uso normale

```bat
setup.bat
avvia.bat
ferma.bat
```

Poi apri http://localhost:3000 → Nuovo progetto → carica foto/video (+ audio) → riordina → Genera montaggio → Esporta.

## Come viene scelta la durata delle foto

La pipeline ora separa nettamente due passaggi:

1. **Sequence** analizza le immagini. Salva il profilo Vision quando è disponibile e calcola anche segnali tecnici locali (nitidezza, contrasto, dettaglio, colore e volti).
2. **Edit Director** riceve sia il profilo della foto sia l'analisi della musica. La durata finale viene quindi scelta considerando importanza, persone, emozione, chiarezza del soggetto, interesse visivo, qualità tecnica, energia musicale e pacing consigliato dal modello.
3. Quando la musica espone una beat grid, i cambi foto vengono allineati ai beat. La fine della timeline viene chiusa sulla durata della colonna sonora quando è fisicamente possibile.

Prima che sia disponibile la musica, `duration_sec` è solo una durata provvisoria; dopo **Genera montaggio** viene sostituita dalla durata `ai+music` e viene registrata come `duration_source="ai_music"`.

## Vision AI

Il comportamento predefinito è `VISION_PROVIDER=auto`:

- prova Ollama su `http://127.0.0.1:11434` e sceglie automaticamente un modello il cui nome indica capacità vision (`vl`, `vision`, `llava`, `gemma3`, ecc.);
- se non trova un modello locale, prova un endpoint OpenAI-compatible solo quando configurato;
- in assenza di un provider, usa il fallback Pillow/OpenCV senza bloccare la generazione del video.

Configurazione per endpoint OpenAI-compatible:

```powershell
$env:VISION_PROVIDER="openai"
$env:VISION_BASE_URL="https://tuo-endpoint/v1"
$env:VISION_MODEL="tuo-modello-vision"
$env:VISION_API_KEY="..."
```

Per forzare il fallback locale:

```powershell
$env:VISION_PROVIDER="disabled"
```

## Audio analysis

Il backend estrae durata, BPM, energia, `beat_times_sec`, `downbeat_times_sec` e mantiene `beat_markers_sec` come alias compatibile con il formato precedente.

## Avvio manuale (sviluppo)

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

cd frontend
npm run dev
```

Le operazioni lunghe (render, import Drive) girano in background con coda persistente in `data/jobs/`, progress live via SSE e polling REST.

## Google Drive (opzionale)

1. Google Cloud Console: abilita Drive API, crea ID client OAuth "App web" con redirect `http://127.0.0.1:8000/api/drive/callback`
2. Nella pagina progetto, sezione Google Drive: incolla client_id/secret → Connetti → sfoglia e importa.

## Test

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
cd ..\frontend
npm run build
```

## Struttura

```
├── architettura-video-maker-ia.md
├── PROGRESS.md
├── backend/
│   ├── app/
│   │   ├── agents/                  # pipeline di montaggio
│   │   ├── api/routes.py            # REST
│   │   ├── api/drive.py             # Google Drive
│   │   ├── services/                # media, audio, vision, Drive
│   │   ├── pipeline/orchestrator.py # DAG + QA
│   │   └── config.py
│   └── tests/
├── frontend/src/
└── data/projects/<id>/              # state.json + media/audio/output/thumbs
```
