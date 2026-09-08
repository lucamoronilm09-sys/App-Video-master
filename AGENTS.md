# Il tuo progetto: AI Video Maker

Specifica completa: `architettura-video-maker-ia.md` (leggi prima di modificare la pipeline o i vincoli di stile).
Stato milestone: `PROGRESS.md`.

## Stack
- Backend: Python 3.11, FastAPI, ffmpeg (via CLI), librosa (da M4)
- Frontend: Next.js 15, TypeScript, Tailwind CSS 4

## Convenzioni di lavoro
- **Un modulo per agente** in `backend/app/agents/`, firma `async run(project_state: dict) -> dict`.
  Ogni agente legge/scrive solo i campi dello state che gli competono (vedi grafo in architettura sez. 4).
- **Project State JSON** è l'unico canale tra agenti: niente chiamate incrociate agente→agente.
- Milestone incrementali: aggiorna `PROGRESS.md` a fine milestone con "(✓ cosa funziona / cosa manca / decisioni prese)".
- Test `pytest` prima di dichiarare una milestone completata; build `next build` per il frontend.
- Non modificare i vincoli di stile dell'architettura (verticali mai croppati, solo crossfade, Ken Burns dolce ≤1.15x, solo audio utente) senza segnalarlo.

## Errori
- Un errore in un file va in `state["errors"]` (dict `{stage, message}`) e non blocca gli altri file.
- Un errore di pipeline (stage fallito) va in `pipeline_log` con `status: "failed"` e interrompe il flusso downstream.
