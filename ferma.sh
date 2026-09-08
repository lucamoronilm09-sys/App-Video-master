#!/bin/bash
# Ferma AI Video Maker (macOS/Linux): uccide backend, frontend e ffmpeg orfani.

cd "$(dirname "$0")"

# Termina backend e frontend usando i PID salvati
if [ -f ".pids/backend.pid" ]; then
    pid=$(cat .pids/backend.pid)
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "Backend (PID $pid) terminato."
    fi
    rm -f .pids/backend.pid
fi

if [ -f ".pids/frontend.pid" ]; then
    pid=$(cat .pids/frontend.pid)
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "Frontend (PID $pid) terminato."
    fi
    rm -f .pids/frontend.pid
fi

# Kill eventuali processi ffmpeg orfani del progetto (output in data/projects)
# Usa pgrep per trovare processi con command-line contenente il path del progetto
root="$(pwd)"
if command -v pgrep &> /dev/null; then
    pids=$(pgrep -f "$root" 2>/dev/null | grep -v "^$$\$" || true)
    if [ -n "$pids" ]; then
        for pid in $pids; do
            # Evita di uccidere se stessi o processi di sistema
            cmdline=$(ps -p "$pid" -o comm= 2>/dev/null || echo "")
            if [[ "$cmdline" == *"ffmpeg"* ]]; then
                kill "$pid" 2>/dev/null || true
                echo "FFmpeg orfano (PID $pid) terminato."
            fi
        done
    fi
fi

# Pulisci la cartella dei log
rm -f .pids/*.log 2>/dev/null || true

echo "AI Video Maker fermato."
