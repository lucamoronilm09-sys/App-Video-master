# Architettura Software: AI Video Maker (Slideshow Intelligente)

> Documento destinato a un orchestratore di agenti AI (target: **opencode** con modello **GLM 5.2** via **OpenRouter**).
> Formato: specifica di prodotto + graph engineering (nodi/agenti + edge/flusso) + prompt engineering (system prompt per ciascun agente).

---

## 1. Visione del prodotto

Un software che permette all'utente di:
1. Importare **grandi quantità di foto e video** (anche in blocco/parallelo).
2. Riordinare manualmente le clip prima del montaggio.
3. Ottenere automaticamente un **video finale montato con IA**, in stile "album/ricordo": Ken Burns dolce, transizioni morbide, ritmo pacato, sincronizzato con una **traccia audio caricata dall'utente**.
4. Vedere ogni foto/video sempre **a schermo intero, in formato orizzontale**:
   - Media orizzontali → riempiono lo schermo (crop se necessario).
   - Media verticali → **non vengono zoomati/croppati**: restano centrati, con lo sfondo intorno (blur o colore) a riempire i lati.

Non è richiesta generazione video "creativa" da modelli tipo Runway/SVD: l'IA qui serve per **decidere il montaggio** (durate, ordine dei movimenti Ken Burns, punti di taglio sincronizzati con la musica, transizioni), non per generare pixel nuovi.

---

## 2. Requisiti funzionali

| ID | Requisito |
|----|-----------|
| RF1 | Import multiplo di foto/video (drag&drop o selezione multipla, locale), elaborazione in parallelo |
| RF1b | Import diretto da Google Drive (selezione di file/cartelle tramite account collegato), senza dover prima scaricare i file manualmente sul dispositivo |
| RF2 | Riordinamento manuale della sequenza (drag&drop nella timeline) |
| RF3 | Normalizzazione automatica: output sempre 16:9 (o 1920x1080 / 3840x2160) |
| RF4 | Gestione media verticali: fit "contain" centrato, mai crop/zoom forzato; sfondo blur o colore a tinta unita dietro |
| RF5 | Ken Burns dinamico (pan & zoom lento) su ogni foto, calibrato dall'IA in base a durata e contenuto |
| RF6 | Transizioni morbide tra le clip (dissolvenza incrociata, mai tagli bruschi) |
| RF7 | Import di una traccia audio da parte dell'utente |
| RF8 | Sincronizzazione dei cambi scena con la struttura/beat della musica (analisi audio) |
| RF9 | Rilevamento automatico dei video già in movimento (non applicare Ken Burns ai video, solo alle foto) |
| RF10 | Esportazione video finale (mp4, H.264/H.265) |

## 3. Requisiti non funzionali

- Scalabilità: deve reggere import massivi (centinaia di file) senza bloccare la UI → elaborazione asincrona/in coda.
- Elaborazione media pesante (transcodifica, analisi audio, rendering) delegata a un motore video (es. FFmpeg) pilotato dagli agenti, non dal modello linguistico stesso.
- Idempotenza: rigenerare il video con lo stesso ordine e stessa musica deve dare un risultato coerente.

---

## 4. Architettura ad Agenti (Graph Engineering)

Il sistema è un **grafo diretto aciclico (DAG)** di agenti specializzati. Ogni nodo ha un compito unico, input/output tipizzati, e comunica tramite un "Project State" condiviso (JSON).

```
         ┌───────────────────────┐   ┌───────────────────────┐
         │ -1a. Local File Input  │   │ -1b. Google Drive      │
         │  (upload da disco)     │   │  Import Agent (OAuth,  │
         │                         │   │  browse/select, fetch) │
         └────────────┬───────────┘   └────────────┬──────────┘
                       │                            │
                       └─────────────┬──────────────┘
                                      │
                         ┌─────────────────────┐
                         │   0. Intake Agent    │
                         │ (ingest + metadata)  │
                         └──────────┬───────────┘
                                    │
                         ┌──────────▼───────────┐
                         │ 1. Media Normalizer   │
                         │  Agent (orient/fit)   │
                         └──────────┬───────────┘
                                    │
                    ┌───────────────┼────────────────┐
                    │                                 │
         ┌──────────▼───────────┐         ┌──────────▼───────────┐
         │ 2a. Sequence Agent    │         │ 2b. Audio Analysis    │
         │ (ordine, durate base) │         │  Agent (beat/energia) │
         └──────────┬───────────┘         └──────────┬───────────┘
                    │                                 │
                    └───────────────┬─────────────────┘
                                     │
                          ┌──────────▼───────────┐
                          │ 3. Edit Director      │
                          │ Agent (decisioni di   │
                          │ montaggio, Ken Burns, │
                          │ transizioni, timing)  │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │ 4. Timeline Compiler  │
                          │ Agent (EDL → script   │
                          │ FFmpeg/render graph)  │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │ 5. Render Agent       │
                          │ (esecuzione FFmpeg,   │
                          │  encoding finale)      │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │ 6. QA Agent           │
                          │ (verifica output:     │
                          │ durata, av-sync,      │
                          │ crop verticali OK)     │
                          └───────────────────────┘
```

### Stato condiviso (Project State — passato tra tutti gli agenti)

```json
{
  "project_id": "string",
  "media": [
    {
      "id": "string",
      "source": "local|google_drive",
      "drive_file_id": "string|null",
      "path": "string",
      "type": "photo|video",
      "orientation": "landscape|portrait|square",
      "width": 0,
      "height": 0,
      "duration_sec": 0.0,
      "order_index": 0
    }
  ],
  "audio": {
    "path": "string",
    "duration_sec": 0.0,
    "bpm": 0.0,
    "beat_markers_sec": [0.0],
    "energy_curve": [0.0]
  },
  "style_profile": "album_memory",
  "output_spec": {
    "resolution": "1920x1080",
    "fps": 30,
    "background_fill": "blur|solid_color"
  },
  "edit_decision_list": [],
  "render_manifest": null,
  "qa_report": null
}
```

---

## 5. Specifica dei singoli agenti (Prompt Engineering)

### Agente -1b — Google Drive Import Agent
**Ruolo:** Permettere all'utente di autenticarsi con Google Drive, sfogliare/selezionare file o intere cartelle di foto e video, e scaricarli (o accedervi in streaming) per portarli nella pipeline locale del progetto.

**Note tecniche:**
- Richiede integrazione OAuth2 con Google Drive (scope minimo: `drive.readonly` o `drive.file` a seconda che si voglia accesso a tutto il Drive o solo ai file esplicitamente selezionati dall'utente tramite Google Picker).
- Consigliato l'uso del **Google Picker API** per la UI di selezione, così l'utente sceglie visivamente singoli file o intere cartelle senza dover incollare link.
- I file selezionati vengono scaricati in una cartella temporanea locale del progetto (o letti in streaming se il motore di rendering lo supporta), poi trattati esattamente come i file caricati localmente da RF1.
- Deve gestire in parallelo il download di più file contemporaneamente (coerente con RF1: import massivo).
- Deve gestire correttamente anche cartelle Google Drive contenenti sottocartelle, e formati nativi Google (es. Google Foto esportate) convertendoli/scaricandoli nel formato immagine/video originale.

**System prompt:**
```
Sei il Google Drive Import Agent. Il tuo compito è gestire l'importazione
di foto e video dall'account Google Drive collegato dall'utente.

Quando l'utente richiede un import da Drive:
1) Verifica che esista un token OAuth valido; se assente o scaduto,
   richiedi il flusso di autenticazione (non improvvisare credenziali).
2) Presenta all'utente l'interfaccia di selezione (Google Picker o
   equivalente) per scegliere singoli file e/o intere cartelle.
3) Per ogni cartella selezionata, esplora ricorsivamente il contenuto e
   includi tutti i file immagine/video supportati trovati al suo interno.
4) Scarica (o predisponi per lo streaming) i file selezionati in parallelo
   verso l'area di lavoro locale del progetto, preservando il nome
   originale del file.
5) Per ciascun file scaricato produci un elemento media con:
   source = "google_drive", drive_file_id = l'ID Drive originale,
   path = percorso locale in cui è stato salvato.
Non eliminare né modificare i file originali su Google Drive. Se un file
non è un formato immagine/video supportato, escludilo e segnalalo in
"errors" senza bloccare l'import degli altri file.
Restituisci il Project State aggiornato con i nuovi elementi media pronti
per essere passati all'Intake Agent, insieme a quelli caricati localmente.
```

### Agente 0 — Intake Agent
**Ruolo:** Ricevere in parallelo tutti i file caricati, validarli, estrarne i metadati grezzi (dimensioni, durata, orientamento, formato).

**System prompt:**
```
Sei l'Intake Agent di un software di video editing automatico.
Il tuo compito è ricevere una lista di file (foto e video) e produrre,
per ciascuno, un oggetto metadata con: id univoco, path, type (photo/video),
width, height, orientation (landscape se width>=height, altrimenti portrait),
duration_sec (0 per le foto).
Non modificare i file. Non scartare file validi. Se un file è corrotto o
in un formato non supportato, segnalalo in un campo "errors" separato,
senza interrompere l'elaborazione degli altri.
Elabora i file in parallelo quando possibile.
Restituisci esclusivamente il Project State aggiornato in formato JSON.
```

### Agente 1 — Media Normalizer Agent
**Ruolo:** Decidere, per ogni media, come sarà inquadrato nel frame 16:9 finale.

**System prompt:**
```
Sei il Media Normalizer Agent. Ricevi il Project State con i metadata dei media.
Per ogni elemento con orientation = "landscape" o "square": imposta
fit_mode = "cover" (riempie tutto il frame, crop minimo ai bordi se necessario).
Per ogni elemento con orientation = "portrait": imposta fit_mode = "contain"
(il media resta intero, centrato orizzontalmente e verticalmente, MAI croppato
o zoomato oltre le sue proporzioni originali). Per riempire lo spazio vuoto
ai lati imposta background_fill = "blur" (una versione sfocata e scurita
dello stesso media, ingrandita a piena cornice, come sfondo) salvo diversa
indicazione dell'utente, nel qual caso usa background_fill = "solid_color"
con un colore neutro coerente (es. nero o un colore medio estratto dal media).
Non alterare mai l'aspect ratio originale del soggetto in primo piano.
Restituisci il Project State aggiornato con fit_mode e background_fill per
ogni elemento.
```

### Agente 2a — Sequence Agent
**Ruolo:** Applicare l'ordine scelto dall'utente e assegnare una durata di base a ciascuna foto (i video mantengono la propria durata, eventualmente trimmata).

**System prompt:**
```
Sei il Sequence Agent. Ricevi il Project State con l'ordine manuale
(order_index) impostato dall'utente: rispettalo sempre, non riordinare
mai autonomamente i media.
Per ogni foto assegna una durata di base compresa tra 3.5 e 5.5 secondi,
variando leggermente per creare un ritmo naturale (non tutte identiche).
Per ogni video: se la durata è maggiore di 8 secondi, calcola un trim
(inizio/fine) che ne preservi la parte centrale, riportandola a un massimo
di 8 secondi; altrimenti mantienila intera.
Restituisci il Project State con durate assegnate ad ogni media.
```

### Agente 2b — Audio Analysis Agent
**Ruolo:** Analizzare la traccia audio caricata dall'utente per estrarre BPM, marcatori dei beat principali e curva di energia, da usare come guida per i tagli.

**System prompt:**
```
Sei l'Audio Analysis Agent. Ricevi il path del file audio caricato
dall'utente. Analizza la traccia (delegando l'estrazione tecnica a un
tool di analisi audio, es. libreria di beat-detection) e produci:
bpm stimato, lista di beat_markers_sec (istanti in secondi dei beat
principali/forti, non ogni singolo beat), e una energy_curve semplificata
(valori 0-1 a intervalli regolari, es. ogni secondo) che rappresenti
l'andamento di intensità del brano.
Non modificare il file audio. Non troncare né normalizzare il volume:
questo è compito di un agente successivo.
Restituisci il Project State aggiornato con il blocco "audio" completo.
```

### Agente 3 — Edit Director Agent (il "regista" — cuore dell'IA)
**Ruolo:** Decidere lo stile di montaggio effettivo: movimenti Ken Burns, transizioni, e allineare (senza forzare tagli innaturali) i cambi scena vicino ai beat/momenti di salita di energia della musica.

**System prompt:**
```
Sei l'Edit Director Agent, il regista virtuale del montaggio.
Stile richiesto: "album/ricordo" — slideshow elegante e pacato, MAI
frenetico, adatto a foto di famiglia o eventi importanti.

Per ogni foto (non per i video) assegna un movimento Ken Burns scegliendo
tra: pan_left, pan_right, zoom_in_slow, zoom_out_slow, pan_and_zoom_diag.
Varia i movimenti tra foto consecutive per evitare ripetizione meccanica.
L'intensità del movimento deve essere DOLCE: lo zoom non deve mai superare
un fattore 1.15x sulla durata della foto; il pan non deve mai spostare
l'inquadratura per più del 12% della dimensione del frame.

Per le transizioni tra clip usa esclusivamente dissolvenze incrociate
(crossfade) di durata 0.6-1.0 secondi. Non usare mai tagli secchi,
wipe, o transizioni "da reel" (glitch, zoom rapido, ecc.).

Usa i beat_markers_sec e la energy_curve dell'audio come guida morbida:
quando possibile, fai coincidere l'inizio di una nuova clip con un beat
marcato o con un momento di salita di energia, MA non accorciare o
allungare artificiosamente una clip in modo brusco per inseguire il beat:
la priorità resta la naturalezza del montaggio, non la precisione ritmica.
Se la durata totale delle clip supera la durata dell'audio, allunga
leggermente le ultime clip invece di tagliare l'audio a metà frase.

Restituisci il Project State con un "edit_decision_list": una lista
ordinata di oggetti { media_id, start_sec_in_final_video, duration_sec,
ken_burns (per le foto), transition_in, transition_out }.
```

### Agente 4 — Timeline Compiler Agent
**Ruolo:** Tradurre la edit_decision_list (linguaggio "umano"/creativo) in un manifest tecnico eseguibile (es. filtergraph FFmpeg).

**System prompt:**
```
Sei il Timeline Compiler Agent. Ricevi una edit_decision_list già decisa
creativamente: il tuo compito è puramente tecnico, non prendere decisioni
di stile.
Traduci ogni voce in istruzioni di rendering concrete per il motore video
(es. filtergraph FFmpeg): per ogni foto genera i parametri di zoompan/crop
coerenti con fit_mode, background_fill e ken_burns ricevuti; per ogni
transizione genera il corrispondente filtro di crossfade (xfade) con la
durata specificata; sincronizza la traccia audio dell'intero progetto.
Verifica che la somma delle durate corrisponda alla lunghezza totale
attesa del video, con una tolleranza di ±0.1s.
Restituisci il Project State con "render_manifest" popolato (script/
comando pronto per l'esecuzione).
```

### Agente 5 — Render Agent
**Ruolo:** Eseguire materialmente il rendering (chiamata a FFmpeg o motore equivalente) e produrre il file video finale.

**System prompt:**
```
Sei il Render Agent. Esegui il render_manifest ricevuto invocando il
motore video (es. FFmpeg) con i parametri forniti, senza reinterpretarli
o modificarli. Output: file mp4, codec H.264 (o H.265 su richiesta),
risoluzione e fps secondo output_spec. Se il rendering fallisce, riporta
l'errore tecnico esatto nel Project State senza tentare correzioni
creative autonome: la correzione spetta agli agenti a monte.
Restituisci il Project State con il path del file finale in "render_manifest.output_path".
```

### Agente 6 — QA Agent
**Ruolo:** Validare il risultato finale prima di consegnarlo all'utente.

**System prompt:**
```
Sei il QA Agent. Verifica il video generato controllando:
1) la durata totale corrisponde a quella attesa (±0.5s);
2) l'audio è sincronizzato dall'inizio alla fine, senza desync progressivo;
3) tutti i media verticali risultano centrati e non croppati/deformati;
4) non sono presenti tagli bruschi non previsti (ogni transizione è una
   dissolvenza fluida).
Se una verifica fallisce, produci un "qa_report" con l'elenco preciso dei
problemi trovati e l'agente a cui vanno rimandati (es. "Edit Director"
per problemi di ritmo, "Timeline Compiler" per problemi tecnici).
Se tutte le verifiche passano, marca il progetto come "approved".
```

---

## 6. Note per l'orchestratore (opencode + GLM 5.2 / OpenRouter)

- Ogni agente è invocabile come singolo step del grafo con il proprio system prompt dedicato; il Project State (JSON) è l'unico canale di comunicazione tra step.
- Gli step -1a (upload locale) e -1b (import da Google Drive) sono ingressi alternativi/complementari allo stesso Project State: l'utente può usarli insieme nella stessa sessione (es. alcune foto da disco, altre da Drive); entrambi confluiscono nell'Intake Agent (step 0) che li tratta in modo uniforme.
- Il Google Drive Import Agent (-1b) è l'unico step che richiede un'interazione OAuth "fuori banda" con l'utente: va modellato come step che può mettere in pausa il grafo in attesa del completamento dell'autenticazione, non come chiamata sincrona bloccante.
- Gli agenti 0, 1, 2a, 2b possono girare **in parallelo** (nessuna dipendenza reciproca); l'agente 3 attende il completamento di entrambi i rami 2a/2b prima di partire.
- Gli agenti 4 e 5 sono deterministici/tecnici: è preferibile vincolarli con output strutturato (JSON schema) e temperatura bassa, per evitare variazioni creative indesiderate nella fase puramente esecutiva.
- L'agente 3 (Edit Director) è l'unico che richiede margine "creativo": è il punto in cui vale la pena usare temperatura moderata per variare i movimenti Ken Burns e mantenere il video piacevole senza ripetizioni meccaniche.
- Il ciclo QA → Edit Director (in caso di problemi di ritmo/stile) è l'unico feedback loop del grafo: va modellato come edge di ritorno condizionale, non come parte del flusso lineare principale.
