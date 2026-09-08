#!/bin/bash
# Setup AI Video Maker (macOS/Linux): controlla prerequisiti, venv+pip, npm, build.
set -e

cd "$(dirname "$0")"

echo "[1/4] Prerequisiti..."
if ! command -v python3 &> /dev/null; then
    echo "MANCA Python 3.11+ nel PATH. Installalo e riprova."
    exit 1
fi
python3 --version | grep -qE "Python 3\.(1[1-9]|[2-9][0-9])" || { echo "Serve Python 3.11 o superiore."; exit 1; }
if ! command -v node &> /dev/null; then
    echo "MANCA Node.js 22+ nel PATH. Installalo da nodejs.org e riprova."
    exit 1
fi
if ! command -v ffmpeg &> /dev/null; then
    echo "MANCA FFmpeg nel PATH. Installalo e riprova."
    exit 1
fi
python3 --version && node --version && ffmpeg -version | head -n1

echo "[2/4] Backend: venv + dipendenze..."
if [ ! -d "backend/.venv" ]; then
    python3 -m venv backend/.venv
fi
backend/.venv/bin/pip install -r backend/requirements.txt

echo "[3/4] Frontend: dipendenze..."
cd frontend
npm install

echo "[4/4] Frontend: build produzione..."
npm run build
cd ..

echo ""
echo "Setup OK. Avvia tutto con ./avvia.sh (ferma con ./ferma.sh)."
