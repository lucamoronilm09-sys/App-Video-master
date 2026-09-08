#!/bin/bash
# Avvia AI Video Maker (macOS/Linux): backend :8000 + frontend :3000, poi apre il browser.
set -e

cd "$(dirname "$0")"

if [ ! -d "backend/.venv" ]; then
    echo "Venv mancante: esegui prima ./setup.sh"
    exit 1
fi

# Crea cartella per i PID
mkdir -p .pids

echo "[1/3] Backend su http://127.0.0.1:8000 ..."
cd backend
nohup ../backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > ../.pids/backend.log 2>&1 &
echo $! > ../.pids/backend.pid
cd ..

# Attendi che il backend sia pronto
tries=0
while [ $tries -lt 60 ]; do
    sleep 1
    tries=$((tries + 1))
    if curl -sf http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
        echo "Backend OK."
        break
    fi
    if [ $tries -ge 60 ]; then
        echo "Backend non partito entro 60s. Controlla .pids/backend.log"
        kill $(cat .pids/backend.pid) 2>/dev/null || true
        exit 1
    fi
done

echo "[2/3] Frontend su http://localhost:3000 ..."
if [ ! -d "frontend/.next" ]; then
    echo "Build produzione mancante, la creo..."
    cd frontend
    npm run build
    cd ..
fi

cd frontend
nohup npm run start -- -p 3000 > ../.pids/frontend.log 2>&1 &
echo $! > ../.pids/frontend.pid
cd ..

echo "[3/3] Apro il browser..."
sleep 2
if [ "$1" != "--no-browser" ]; then
    # macOS usa open, Linux usa xdg-open
    if command -v open &> /dev/null; then
        open http://localhost:3000 2>/dev/null || true
    elif command -v xdg-open &> /dev/null; then
        xdg-open http://localhost:3000 2>/dev/null || true
    fi
fi

echo "Fatto. Ferma tutto con ./ferma.sh."
