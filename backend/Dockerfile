# Backend FastAPI - Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Installa dipendenze di sistema necessarie
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Installa pip-tools per la gestione delle dipendenze
RUN pip install --no-cache-dir pip-tools

# Copia i file delle dipendenze
COPY requirements.txt requirements.in ./

# Installa le dipendenze Python dal requirements.txt (versioni bloccate)
RUN pip install --no-cache-dir -r requirements.txt

# Copia il resto del codice
COPY . .

# Esponi la porta
EXPOSE 8000

# Variabili d'ambiente
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000

# Comando per avviare l'applicazione con hot-reload in sviluppo
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
