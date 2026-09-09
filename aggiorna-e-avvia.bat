@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title AI Video Maker - Aggiorna e avvia

echo.
echo ================================================================
echo        AI VIDEO MAKER - AGGIORNA E AVVIA
 echo ================================================================
echo.

rem ================================================================
rem 1. PREREQUISITI - installa solo cio' che manca.
rem ================================================================
echo [1/5] Controllo prerequisiti...
where powershell.exe >nul 2>&1 || goto FAIL
where winget.exe >nul 2>&1 || (
  echo ERRORE: winget non e' disponibile. Installa/Aggiorna App Installer.
  goto FAIL
)

where git.exe >nul 2>&1 || (
  echo Git non trovato: installazione automatica...
  winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements || goto DEP_FAIL
  call :refresh_path
)
where git.exe >nul 2>&1 || goto FAIL

python --version >nul 2>&1 || (
  echo Python non trovato: installazione automatica Python 3.12...
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements || goto DEP_FAIL
  call :refresh_path
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 || (
  echo Python troppo vecchio: aggiornamento...
  winget upgrade --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements || goto DEP_FAIL
  call :refresh_path
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 || goto FAIL

node --version >nul 2>&1 || (
  echo Node.js non trovato: installazione automatica...
  winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements || goto DEP_FAIL
  call :refresh_path
)
node -e "process.exit(parseInt(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)" >nul 2>&1 || (
  echo Node.js troppo vecchio: aggiornamento...
  winget upgrade --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements || goto DEP_FAIL
  call :refresh_path
)
node -e "process.exit(parseInt(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)" >nul 2>&1 || goto FAIL

ffmpeg -version >nul 2>&1 || (
  echo FFmpeg non trovato: installazione automatica...
  winget install --id Gyan.FFmpeg.Shared -e --accept-source-agreements --accept-package-agreements || (
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements || goto DEP_FAIL
  )
  call :refresh_path
)
ffmpeg -version >nul 2>&1 || goto FAIL
ffprobe -version >nul 2>&1 || goto FAIL

echo Prerequisiti OK.
echo.

rem ================================================================
rem 2. GIT - aggiorna SOLO se GitHub contiene nuovi commit.
rem ================================================================
echo [2/5] Controllo aggiornamenti GitHub...
if not exist ".git" (
  echo ERRORE: questa cartella non e' un repository Git.
  goto FAIL
)

git fetch origin main || goto GIT_FAIL
for /f "delims=" %%A in ('git rev-parse HEAD') do set "LOCAL_HEAD=%%A"
for /f "delims=" %%A in ('git rev-parse origin/main') do set "REMOTE_HEAD=%%A"

if /I "!LOCAL_HEAD!"=="!REMOTE_HEAD!" (
  echo Repository gia' aggiornato: nessun download necessario.
) else (
  echo Nuova versione trovata su GitHub.
  git status --porcelain > "%TEMP%\aivideo_git_status.txt"
  set "HAS_LOCAL=0"
  for /f "usebackq delims=" %%A in ("%TEMP%\aivideo_git_status.txt") do set "HAS_LOCAL=1"
  del "%TEMP%\aivideo_git_status.txt" >nul 2>&1

  if "!HAS_LOCAL!"=="1" (
    echo Salvo temporaneamente le modifiche locali...
    git stash push -u -m "AI Video Maker auto-update %date% %time%" || goto GIT_FAIL
    set "STASHED=1"
  ) else set "STASHED=0"

  git pull --ff-only origin main || (
    echo Fast-forward non possibile. Provo rebase...
    git pull --rebase origin main || goto GIT_FAIL
  )

  if "!STASHED!"=="1" (
    echo Ripristino modifiche locali...
    git stash pop
    if errorlevel 1 echo ATTENZIONE: possibile conflitto nel ripristino locale. Controlla git status.
  )
  set "UPDATED=1"
  echo Repository aggiornato.
)
echo.

rem ================================================================
rem 3. DIPENDENZE BACKEND - pip install solo se requirements e' cambiato
rem    oppure se il venv non esiste.
rem ================================================================
echo [3/5] Controllo dipendenze backend...
if not exist "backend\.venv\Scripts\python.exe" (
  echo Creo ambiente virtuale...
  python -m venv backend\.venv || goto DEP_FAIL
  set "PY_DEPS_NEEDED=1"
) else set "PY_DEPS_NEEDED=0"

if exist "backend\requirements.txt" if not exist "backend\.venv\.requirements.sha256" set "PY_DEPS_NEEDED=1"
if exist "backend\requirements.txt" (
  for /f "delims=" %%A in ('certutil -hashfile "backend\requirements.txt" SHA256 ^| findstr /r "^[0-9A-F][0-9A-F]"') do if not defined REQ_HASH set "REQ_HASH=%%A"
  if exist "backend\.venv\.requirements.sha256" (
    set /p OLD_REQ_HASH=<"backend\.venv\.requirements.sha256"
    if /I not "!REQ_HASH!"=="!OLD_REQ_HASH!" set "PY_DEPS_NEEDED=1"
  )
)

if "!PY_DEPS_NEEDED!"=="1" (
  echo Installo/aggiorno dipendenze Python...
  backend\.venv\Scripts\python.exe -m pip install --upgrade pip || goto DEP_FAIL
  backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt || goto DEP_FAIL
  >"backend\.venv\.requirements.sha256" echo !REQ_HASH!
) else echo Dipendenze Python gia' aggiornate.
echo.

rem ================================================================
rem 4. FRONTEND - npm install solo se package-lock/package.json cambia.
rem ================================================================
echo [4/5] Controllo dipendenze frontend...
if not exist "frontend\package.json" goto FAIL
set "NPM_NEEDED=0"
if not exist "frontend\node_modules" set "NPM_NEEDED=1"
if exist "frontend\package-lock.json" if not exist "frontend\node_modules\.package-lock.json" set "NPM_NEEDED=1"
if defined UPDATED set "NPM_NEEDED=1"

if "!NPM_NEEDED!"=="1" (
  cd /d "%~dp0frontend"
  call npm install || goto DEP_FAIL
  cd /d "%~dp0"
) else echo Dipendenze npm gia' installate.
echo.

rem ================================================================
rem 5. BUILD - solo se necessario.
rem    Il build viene fatto se: non esiste, e' arrivato codice nuovo,
rem    oppure package.json/lock sono cambiati.
rem ================================================================
echo [5/5] Controllo build frontend...
set "BUILD_NEEDED=0"
if not exist "frontend\.next" set "BUILD_NEEDED=1"
if defined UPDATED set "BUILD_NEEDED=1"
if "!NPM_NEEDED!"=="1" set "BUILD_NEEDED=1"

if "!BUILD_NEEDED!"=="1" (
  echo Creo il build di produzione...
  cd /d "%~dp0frontend"
  call npm run build
  if errorlevel 1 (
    cd /d "%~dp0"
    echo ERRORE: build Next.js fallito. Avvio bloccato.
    goto FAIL
  )
  cd /d "%~dp0"
  echo Build OK.
) else echo Build gia' aggiornato: salto npm run build.
echo.

echo ================================================================
echo Tutti i controlli sono OK. Avvio AI Video Maker...
echo ================================================================
call "%~dp0avvia.bat"
if errorlevel 1 goto FAIL
exit /b 0

:refresh_path
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$m=[Environment]::GetEnvironmentVariable('Path','Machine');$u=[Environment]::GetEnvironmentVariable('Path','User');[Console]::Write($m+';'+$u)"`) do set "PATH=%%P"
exit /b 0

:DEP_FAIL
echo.
echo ERRORE: installazione/configurazione dipendenze fallita.
goto FAIL

:GIT_FAIL
echo.
echo ERRORE: sincronizzazione GitHub fallita.
goto FAIL

:FAIL
echo.
echo ================================================================
echo OPERAZIONE NON COMPLETATA
 echo ================================================================
echo L'avvio e' stato bloccato per evitare un'installazione incompleta.
echo.
pause
exit /b 1
