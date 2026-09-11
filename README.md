# AI Video Maker — v1.1.0

Slideshow automatico in stile "album/ricordo": foto e video (locali o da Google Drive) diventano un mp4 16:9 montato con Ken Burns, analisi Vision delle foto e sincronizzazione musicale.

Architettura ad agenti + specifica completa: **`architettura-video-maker-ia.md`**.
Stato avanzamento: **`PROGRESS.md`**.

## Requisiti

### Opzione 1: Docker (consigliato)

- Docker Desktop installato
- Docker Compose (incluso in Docker Desktop)

### Opzione 2: Installazione locale (Windows)

- Python 3.12+, Node.js 22+, FFmpeg — tutti nel PATH
- Per il Vision AI locale è consigliato **Ollama** con almeno un modello vision-capable installato. Il backend lo rileva automaticamente.

## Gestione dipendenze backend

Il progetto utilizza **pip-tools** per gestire le dipendenze Python in modo riproducibile:

- `backend/requirements.in`: dipendenze principali con versioni minime (gestite manualmente)
- `backend/requirements.txt`: dipendenze con versioni bloccate (generato automaticamente)

### Installazione dipendenze

```bash
pip install -r backend/requirements.txt
```

### Aggiornare le dipendenze

Per aggiungere una nuova dipendenza, modificala in `requirements.in` e rigenera il file bloccato:

```bash
cd backend
pip-compile requirements.in --output-file requirements.txt
```

Per aggiornare tutte le dipendenze alle ultime versioni compatibili:

```bash
cd backend
pip-compile requirements.in --output-file requirements.txt --upgrade
```

## Avvio con Docker (consigliato)

Il progetto può essere avviato facilmente utilizzando Docker e Docker Compose.

### Prerequisiti

- Docker Desktop installato
- Docker Compose (incluso in Docker Desktop)

### Primo avvio

1. Copia il file di esempio per le variabili d'ambiente:

```bash
cp .env.example .env
```

2. Avvia tutti i servizi:

```bash
docker-compose up --build
```

3. Apri il browser su http://localhost:3000

### Comandi utili

```bash
# Avvia in background (detached mode)
docker-compose up -d --build

# Ferma tutti i servizi
docker-compose down

# Ferma e rimuovi volumi (attenzione: cancella i dati!)
docker-compose down -v

# Visualizza i log
docker-compose logs -f

# Visualizza i log del solo backend
docker-compose logs -f backend

# Riavvia un singolo servizio
docker-compose restart backend

# Esegui comandi all'interno dei container
docker-compose exec backend bash
docker-compose exec frontend sh

# Ricostruisci un singolo servizio
docker-compose build --no-cache backend
```

### Sviluppo con hot-reload

La configurazione Docker include volumi che montano il codice sorgente nei container, permettendo l'hot-reload durante lo sviluppo:

- Le modifiche al backend Python vengono rilevate automaticamente da uvicorn con `--reload`
- Le modifiche al frontend Next.js vengono rilevate automaticamente da `next dev`

### Dati persistenti

I dati dei progetti sono salvati nella directory `./data` che è montata come volume nel container backend. I dati persistono anche dopo lo stop dei container.

## Uso normale (senza Docker)

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

## Test e Coverage

### Esecuzione test con coverage

Per eseguire i test del backend con report di coverage:

```bash
cd backend
pytest --cov=app --cov-report=term --cov-fail-under=70
```

### Generare report HTML

Per generare un report HTML dettagliato del coverage:

```bash
cd backend
pytest --cov=app --cov-report=html
# Apri il file htmlcov/index.html nel browser
```

### Opzioni di coverage

- `--cov=app`: misura il coverage sul pacchetto `app`
- `--cov-report=term`: mostra il report nel terminale
- `--cov-report=html`: genera report HTML nella cartella `htmlcov/`
- `--cov-fail-under=50`: fallisce se il coverage è inferiore al 50% (soglia minima consigliata)

La configurazione `.coveragerc` esclude automaticamente test, cache e codice boilerplate.

**Nota:** La soglia di coverage del 50% è un minimo accettabile per progetti in evoluzione. Si consiglia di aumentare gradualmente la copertura dei test. Alcuni test possono richiedere molto tempo; esegui solo i test necessari durante lo sviluppo.

## Test (comandi rapidi)

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
