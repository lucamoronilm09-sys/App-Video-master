# Guida alla Configurazione degli Ambienti - AI Video Maker

Questo documento descrive come utilizzare le diverse configurazioni ambientali del progetto.

## Panoramica

Il progetto supporta quattro ambienti distinti:

| Ambiente   | Scopo                                      | Comandi Docker                                     |
|------------|--------------------------------------------|----------------------------------------------------|
| development| Sviluppo locale con hot-reload             | `docker compose up`                                |
| testing    | Test automatizzati e CI/CD                 | `docker compose -f docker-compose.test.yml up`     |
| staging    | Pre-produzione, QA, test pre-deploy        | `docker compose -f docker-compose.staging.yml up`  |
| production | Deploy in produzione                       | `docker compose -f docker-compose.prod.yml up -d`  |

## File di Configurazione

### docker-compose.yml (Base - Development)
Configurazione di default per lo sviluppo locale:
- Mount del codice sorgente per hot-reload
- Logging DEBUG
- Healthcheck rapidi (10s)
- Comando `--reload` per uvicorn

### docker-compose.test.yml
Override per ambiente di testing:
- Volumi temporanei non persistenti
- Isolamento completo
- URL API interne per test end-to-end

### docker-compose.staging.yml
Override per ambiente di staging:
- Simula production con logging DEBUG
- Volumi persistenti separati
- Resource limits ridotti
- Utile per QA e test pre-deploy

### docker-compose.prod.yml
Override per ambiente di production:
- Nessuna mount del codice sorgente
- Ottimizzazioni performance
- Resource limits definiti
- Restart policy `always`
- Security hardening opzionale

## Variabili d'Ambiente

### File .env.example
Template documentato con tutte le variabili supportate:
- **NON committare mai** il file `.env` nel repository
- Copiare `.env.example` in `.env` e personalizzare
- Utilizzare `.env` diverso per ogni ambiente se necessario

### Variabili Principali

#### Backend
```bash
APP_ENV=development|testing|staging|production
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=DEBUG|INFO|WARNING|ERROR|CRITICAL
VISION_PROVIDER=auto|openai|ollama|disabled
DATA_DIR=/app/data
API_KEY=<opzionale>
CORS_ORIGINS=https://example.com
```

#### Frontend
```bash
NODE_ENV=development|production
NEXT_PUBLIC_API_URL=http://localhost:8000
BACKEND_URL=http://backend:8000
PORT=3000
```

## Comandi di Avvio

### Development (Locale)
```bash
# Con Docker Compose
docker compose up

# Oppure con script locali (senza Docker)
./setup.sh    # Solo prima volta
./avvia.sh    # Avvia backend + frontend
./ferma.sh    # Ferma tutto
```

### Testing
```bash
# Esegue test con volumi temporanei
docker compose -f docker-compose.yml -f docker-compose.test.yml up --abort-on-container-exit

# Per CI/CD
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d
# ... esegui test ...
docker compose down -v
```

### Staging
```bash
# Avvio in background
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d

# Log in tempo reale
docker compose -f docker-compose.yml -f docker-compose.staging.yml logs -f

# Stop
docker compose -f docker-compose.yml -f docker-compose.staging.yml down
```

### Production
```bash
# Avvio in background con rebuild
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Monitoraggio
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f frontend

# Stop
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

## Gestione dei Dati

### Development
- I dati sono salvati in `./data` (mount locale)
- Facilità di accesso e backup manuale
- Condiviso tra riavvii

### Testing
- Volumi temporanei (`test-data`)
- Dati eliminati al `down -v`
- Isolamento completo tra esecuzioni

### Staging
- Named volume: `app-staging-data`
- Persistente tra riavvii
- Separato da production

### Production
- Named volume: `app-data`
- Persistente e gestito da Docker
- Backup consigliato tramite volumi Docker

## Sicurezza

### Production Checklist
- [ ] Impostare `API_KEY` in `.env`
- [ ] Configurare `CORS_ORIGINS` per domini specifici
- [ ] Usare `LOG_LEVEL=INFO` o superiore
- [ ] Verificare resource limits appropriati
- [ ] Abilitare `read_only: true` se possibile (commentato nel file prod)
- [ ] Non esporre porte non necessarie
- [ ] Usare reti isolate per servizi interni

### Sviluppo
- CORS aperto per localhost
- Logging DEBUG abilitato
- API key opzionale
- Porte esposte per debugging

## Risoluzione Problemi

### Container non si avvia
```bash
# Controlla i log
docker compose logs backend
docker compose logs frontend

# Verifica configurazione
docker compose config

# Rebuild immagini
docker compose build --no-cache
```

### Problemi di rete/CORS
```bash
# Verifica environment variables
docker compose exec backend env | grep CORS
docker compose exec frontend env | grep API_URL

# Test connettività interna
docker compose exec frontend wget http://backend:8000/api/health
```

### Volumi e Dati
```bash
# Lista volumi
docker volume ls | grep app-video

# Ispeziona volume
docker volume inspect app-video_app-data

# Backup volume production
docker run --rm -v app-video_app-data:/data -v $(pwd):/backup alpine tar czf /backup/app-data-backup.tar.gz -C /data .
```

## Integrazione CI/CD

GitHub Actions utilizza la configurazione di testing automaticamente. Vedi `.github/workflows/ci.yml`.

Per pipeline custom:
```yaml
- name: Start test environment
  run: docker compose -f docker-compose.yml -f docker-compose.test.yml up -d

- name: Run tests
  run: ./run-tests.sh

- name: Cleanup
  run: docker compose -f docker-compose.yml -f docker-compose.test.yml down -v
```

## Note Importanti

1. **Mai committare `.env`**: Il file `.env` è nel `.gitignore`. Usa sempre `.env.example` come template.

2. **Multi-file Compose**: La configurazione usa l'approccio multi-file di Docker Compose. Il file base (`docker-compose.yml`) contiene la configurazione comune, mentre i file specifici (`dev`, `test`, `staging`, `prod`) applicano override.

3. **Named Volumes**: In production/staging, i named volumes sono gestiti da Docker e persistono anche dopo `down`. Usare `down -v` per rimuoverli.

4. **Resource Limits**: I limiti di CPU/memoria in production richiedono Docker Swarm o Kubernetes per essere applicati pienamente. In Compose standalone, usare `--cpus` e `--memory` nel comando `up`.

5. **Healthcheck**: Gli healthcheck sono configurati diversamente per ogni ambiente. In production sono più tolleranti (più retries, start_period più lungo).
