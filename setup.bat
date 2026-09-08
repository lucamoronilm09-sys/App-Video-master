@echo off
rem Setup AI Video Maker (Windows): controlla prerequisiti, venv+pip, npm, build.
setlocal
cd /d %~dp0

echo [1/4] Prerequisiti...
where python >nul 2>&1
if errorlevel 1 ( echo MANCA Python 3.11+ nel PATH. Installalo da python.org e riprova. & exit /b 1 )
python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
if errorlevel 1 ( echo Serve Python 3.11 o superiore. & exit /b 1 )
where node >nul 2>&1
if errorlevel 1 ( echo MANCA Node.js 22+ nel PATH. Installalo da nodejs.org e riprova. & exit /b 1 )
where ffmpeg >nul 2>&1
if errorlevel 1 ( echo MANCA FFmpeg nel PATH. Installalo ^(gyan.dev build^) e riprova. & exit /b 1 )
python --version & node --version & ffmpeg -version 2>&1 | findstr /c:"ffmpeg version"

echo [2/4] Backend: venv + dipendenze...
if not exist backend\.venv\Scripts\python.exe (
  python -m venv backend\.venv
  if errorlevel 1 ( echo Creazione venv fallita. & exit /b 1 )
)
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 ( echo pip install fallito. & exit /b 1 )

echo [3/4] Frontend: dipendenze...
cd frontend
call npm install
if errorlevel 1 ( echo npm install fallito. & exit /b 1 )

echo [4/4] Frontend: build produzione...
call npm run build
if errorlevel 1 ( echo next build fallito. & exit /b 1 )
cd ..

echo.
echo Setup OK. Avvia tutto con avvia.bat ^(ferma con ferma.bat^).
