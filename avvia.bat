@echo off
rem Avvia AI Video Maker: backend :8000 + frontend :3000, poi apre il browser.
rem Log dei processi in data\backend.log e data\frontend.log (diagnosi se crashano).
setlocal
cd /d %~dp0

if not exist backend\.venv\Scripts\python.exe (
  echo Venv mancante: esegui prima setup.bat
  pause
  exit /b 1
)
if not exist data mkdir data

echo [0/4] Pulizia eventuali processi precedenti (porte libere)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ferma.ps1"
rem attesa che le porte si liberino davvero
ping -n 4 127.0.0.1 >nul

echo [1/4] Backend su http://127.0.0.1:8000 ...
echo        (log live in data\backend.log e data\backend-err.log)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~dp0backend\.venv\Scripts\python.exe' -ArgumentList '-u','-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory '%~dp0backend' -RedirectStandardOutput '%~dp0data\backend.log' -RedirectStandardError '%~dp0data\backend-err.log' -WindowStyle Minimized"

set /a tries=0
:wait_backend
rem attesa 1s senza stdin (timeout.exe richiede una console)
ping -n 2 127.0.0.1 >nul
set /a tries+=1
curl.exe -sf http://127.0.0.1:8000/api/health >nul 2>&1
if not errorlevel 1 goto backend_ok
if %tries% GEQ 60 (
  echo Backend non partito entro 60s. Ultime righe dei log:
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content '%~dp0data\backend-err.log','%~dp0data\backend.log' -Tail 15 -ErrorAction SilentlyContinue"
  pause
  exit /b 1
)
goto wait_backend
:backend_ok
echo Backend OK.

echo [2/4] Frontend su http://localhost:3000 ...
if not exist frontend\.next (
  echo Build produzione mancante, la creo...
  cd frontend
  call npm run build
  if errorlevel 1 ( echo next build fallito. & pause & exit /b 1 )
  cd /d %~dp0
)
echo        (log live in data\frontend.log e data\frontend-err.log)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','npm run start -- -p 3000' -WorkingDirectory '%~dp0frontend' -RedirectStandardOutput '%~dp0data\frontend.log' -RedirectStandardError '%~dp0data\frontend-err.log' -WindowStyle Minimized"

set /a tries=0
:wait_frontend
ping -n 2 127.0.0.1 >nul
set /a tries+=1
curl.exe -sf http://localhost:3000/ >nul 2>&1
if not errorlevel 1 goto frontend_ok
if %tries% GEQ 30 (
  echo Frontend non partito entro 30s. Ultime righe dei log:
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content '%~dp0data\frontend-err.log','%~dp0data\frontend.log' -Tail 15 -ErrorAction SilentlyContinue"
  pause
  exit /b 1
)
goto wait_frontend
:frontend_ok
echo Frontend OK.

echo [3/4] Apro il browser...
if /i "%1"=="--no-browser" goto done
start http://localhost:3000
:done
echo [4/4] Fatto. Ferma tutto con ferma.bat.
echo        Se qualcosa si chiude da solo, leggi data\backend-err.log o data\frontend-err.log.
