@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title AI Video Maker - Aggiorna e avvia

rem ================================================================
rem AI VIDEO MAKER - ONE CLICK WINDOWS STARTER
rem Controlla/installa prerequisiti, aggiorna GitHub, installa deps,
rem ricrea il build e avvia backend + frontend.
rem ================================================================

echo.
echo ================================================================
echo        AI VIDEO MAKER - AGGIORNA E AVVIA
 echo ================================================================
echo.

rem ---- 0. Controllo Windows/winget --------------------------------
where powershell.exe >nul 2>&1
if errorlevel 1 goto FAIL
where winget.exe >nul 2>&1
if errorlevel 1 (
  echo ERRORE: winget non e' disponibile.
  echo Installa/Aggiorna "App Installer" dal Microsoft Store e riprova.
  goto FAIL
)

rem ---- 1. Prerequisiti ---------------------------------------------
echo [1/6] Controllo prerequisiti...

where git.exe >nul 2>&1
if errorlevel 1 (
  echo Git non trovato. Installazione automatica...
  winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto DEP_FAIL
  call :refresh_path
  where git.exe >nul 2>&1
  if errorlevel 1 (
    echo ERRORE: Git e' stato installato ma non e' ancora nel PATH.
    echo Chiudi questa finestra e riesegui aggiorna-e-avvia.bat.
    goto FAIL
  )
)

python --version >nul 2>&1
if errorlevel 1 (
  echo Python non trovato. Installazione automatica Python 3.12...
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto DEP_FAIL
  call :refresh_path
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
  echo ERRORE: serve Python 3.11 o superiore.
  goto FAIL
)

node --version >nul 2>&1
if errorlevel 1 (
  echo Node.js non trovato. Installazione automatica...
  winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto DEP_FAIL
  call :refresh_path
)
node -e "process.exit(parseInt(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)" >nul 2>&1
if errorlevel 1 (
  echo Node.js presente ma troppo vecchio: serve Node 22+.
  echo Aggiornamento automatico...
  winget upgrade --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto DEP_FAIL
  call :refresh_path
  node -e "process.exit(parseInt(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)" >nul 2>&1
  if errorlevel 1 goto FAIL
)

ffmpeg -version >nul 2>&1
if errorlevel 1 (
  echo FFmpeg non trovato. Installazione automatica...
  winget install --id Gyan.FFmpeg.Shared -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo Primo pacchetto FFmpeg non disponibile: provo Gyan.FFmpeg...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    if errorlevel 1 goto DEP_FAIL
  )
  call :refresh_path
)
ffmpeg -version >nul 2>&1
if errorlevel 1 goto FAIL
ffprobe -version >nul 2>&1
if errorlevel 1 goto FAIL

echo     Git:     OK
git --version
echo     Python:  OK
python --version
echo     Node:    OK
node --version
echo     FFmpeg:  OK
ffmpeg -version 2>&1 | findstr /c:"ffmpeg version"
echo.

rem ---- 2. Sincronizzazione repository ------------------------------
echo [2/6] Sincronizzazione con GitHub...
if not exist ".git" (
  echo ERRORE: questa cartella non e' un repository Git.
  echo Clona il repository App-Video-master e riesegui questo file.
  goto FAIL
)

git fetch origin main
if errorlevel 1 (
  echo ERRORE: impossibile raggiungere GitHub.
  echo Controlla la connessione Internet e riprova.
  goto FAIL
)

rem Salva temporaneamente eventuali modifiche locali per non perderle.
git diff --quiet
set DIRTY=%errorlevel%
git diff --cached --quiet
set CACHED_DIRTY=%errorlevel%
git ls-files --others --exclude-standard | findstr . >nul
set UNTRACKED=%errorlevel%

if "%DIRTY%"=="1" if "%CACHED_DIRTY%"=="1" (
  echo Modifiche locali rilevate: salvo temporaneamente...
  git stash push -u -m "AI Video Maker auto-update %date% %time%"
  if errorlevel 1 goto GIT_FAIL
  set STASHED=1
) else if "%DIRTY%"=="1" (
  echo Modifiche locali rilevate: salvo temporaneamente...
  git stash push -u -m "AI Video Maker auto-update %date% %time%"
  if errorlevel 1 goto GIT_FAIL
  set STASHED=1
) else if "%UNTRACKED%"=="0" (
  set STASHED=0
) else (
  echo File locali non tracciati rilevati: salvo temporaneamente...
  git stash push -u -m "AI Video Maker auto-update %date% %time%"
  if errorlevel 1 goto GIT_FAIL
  set STASHED=1
)

git pull --ff-only origin main
if errorlevel 1 (
  echo Fast-forward non possibile. Provo ad aggiornare il branch senza perdere il lavoro locale...
  git pull --rebase origin main
  if errorlevel 1 goto GIT_FAIL
)

if "%STASHED%"=="1" (
  echo Ripristino eventuali modifiche locali...
  git stash pop
  if errorlevel 1 (
    echo ATTENZIONE: ci sono conflitti nelle modifiche locali.
    echo Il codice aggiornato da GitHub e' comunque disponibile.
    echo Controlla con: git status
  )
)
echo Repository aggiornato.
echo.

rem ---- 3. Ambiente Python -----------------------------------------
echo [3/6] Ambiente Python e dipendenze backend...
if not exist "backend\.venv\Scripts\python.exe" (
  echo Creo backend\.venv ...
  python -m venv backend\.venv
  if errorlevel 1 goto DEP_FAIL
)

backend\.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto DEP_FAIL
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto DEP_FAIL

echo Backend dipendenze OK.
echo.

rem ---- 4. Frontend -------------------------------------------------
echo [4/6] Dipendenze frontend...
if not exist "frontend\package.json" (
  echo ERRORE: frontend\package.json non trovato.
  goto FAIL
)
cd /d "%~dp0frontend"
call npm install
if errorlevel 1 (
  echo npm install fallito. Provo npm ci...
  call npm ci
  if errorlevel 1 goto DEP_FAIL
)
cd /d "%~dp0"
echo Frontend dipendenze OK.
echo.

rem ---- 5. Build pulito ---------------------------------------------
echo [5/6] Ricostruzione completa del frontend...
if exist "frontend\.next" rmdir /s /q "frontend\.next"
if exist "frontend\.next" goto DEP_FAIL
cd /d "%~dp0frontend"
call npm run build
if errorlevel 1 (
  cd /d "%~dp0"
  echo.
  echo ERRORE: il build Next.js e' fallito.
  echo Controlla il messaggio sopra: l'avvio viene bloccato apposta.
  goto FAIL
)
cd /d "%~dp0"
echo Build OK.
echo.

rem ---- 6. Avvio ----------------------------------------------------
echo [6/6] Avvio AI Video Maker...
call "%~dp0avvia.bat"
set EXITCODE=%errorlevel%
if not "%EXITCODE%"=="0" goto FAIL
exit /b 0

:refresh_path
rem Aggiorna il PATH della sessione corrente leggendo quello di sistema/utente.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User'); $env:Path"`) do set "PATH=%%P"
exit /b 0

:DEP_FAIL
echo.
echo ERRORE: installazione/configurazione delle dipendenze fallita.
echo Verifica la connessione Internet e riprova.
goto FAIL

:GIT_FAIL
echo.
echo ERRORE: sincronizzazione Git non riuscita.
echo Nessun file locale viene cancellato automaticamente.
goto FAIL

:FAIL
echo.
echo ================================================================
echo OPERAZIONE NON COMPLETATA
 echo ================================================================
echo Il programma NON e' stato avviato per evitare di usare una versione incompleta.
echo Riprova dopo aver corretto l'errore mostrato sopra.
echo.
pause
exit /b 1
