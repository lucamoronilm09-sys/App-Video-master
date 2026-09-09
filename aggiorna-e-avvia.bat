@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title AI Video Maker - Aggiorna e avvia

echo.
echo ================================================================
echo        AI VIDEO MAKER - AGGIORNA E AVVIA
echo ================================================================
echo.

rem [0] Strumenti Windows necessari per l'automazione.
where powershell.exe >nul 2>&1
if errorlevel 1 goto FAIL
where winget.exe >nul 2>&1
if errorlevel 1 (
  echo ERRORE: winget non e' disponibile.
  echo Aggiorna/installare "App Installer" di Microsoft e riprova.
  goto FAIL
)

rem [1/6] Prerequisiti: se mancano vengono installati con winget.
echo [1/6] Controllo prerequisiti...

where git.exe >nul 2>&1
if errorlevel 1 (
  echo Git non trovato. Installazione automatica...
  winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto DEP_FAIL
  call :refresh_path
)
where git.exe >nul 2>&1
if errorlevel 1 goto FAIL

python --version >nul 2>&1
if errorlevel 1 (
  echo Python non trovato. Installazione automatica Python 3.12...
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto DEP_FAIL
  call :refresh_path
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
  echo Python presente ma troppo vecchio. Aggiornamento automatico...
  winget upgrade --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto DEP_FAIL
  call :refresh_path
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
  if errorlevel 1 goto FAIL
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
  echo Node.js presente ma troppo vecchio. Aggiornamento automatico...
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
    echo Provo il pacchetto FFmpeg alternativo...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    if errorlevel 1 goto DEP_FAIL
  )
  call :refresh_path
)
ffmpeg -version >nul 2>&1
if errorlevel 1 goto FAIL
ffprobe -version >nul 2>&1
if errorlevel 1 goto FAIL

echo     Git:     OK & git --version
echo     Python:  OK & python --version
echo     Node:    OK & node --version
echo     FFmpeg:  OK
ffmpeg -version 2>&1 | findstr /c:"ffmpeg version"
echo.

rem [2/6] Git: aggiorna senza cancellare il lavoro locale.
echo [2/6] Sincronizzazione con GitHub...
if not exist ".git" (
  echo ERRORE: questa cartella non e' un repository Git.
  echo Usa una copia clonata di App-Video-master.
  goto FAIL
)

git fetch origin main
if errorlevel 1 (
  echo ERRORE: impossibile raggiungere GitHub.
  goto GIT_FAIL
)

rem Se esiste qualunque modifica locale, viene messa temporaneamente nello stash.
git status --porcelain > "%TEMP%\aivideo_git_status.txt"
set "HAS_LOCAL=0"
for /f "usebackq delims=" %%A in ("%TEMP%\aivideo_git_status.txt") do set "HAS_LOCAL=1"
del "%TEMP%\aivideo_git_status.txt" >nul 2>&1

if "!HAS_LOCAL!"=="1" (
  echo Modifiche locali rilevate: le salvo temporaneamente per l'aggiornamento.
  git stash push -u -m "AI Video Maker auto-update %date% %time%"
  if errorlevel 1 goto GIT_FAIL
  set "STASHED=1"
) else (
  set "STASHED=0"
)

git pull --ff-only origin main
if errorlevel 1 (
  echo Il branch locale non puo' essere aggiornato con fast-forward.
  echo Provo il rebase automatico dei commit locali...
  git pull --rebase origin main
  if errorlevel 1 goto GIT_FAIL
)

if "!STASHED!"=="1" (
  echo Ripristino le modifiche locali...
  git stash pop
  if errorlevel 1 (
    echo ATTENZIONE: il ripristino locale ha prodotto conflitti.
    echo Il codice aggiornato da GitHub resta disponibile.
    echo Controlla con: git status
  )
)
echo Repository aggiornato.
echo.

rem [3/6] Backend: venv e dipendenze.
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

rem [4/6] Frontend: dipendenze.
echo [4/6] Dipendenze frontend...
if not exist "frontend\package.json" goto FAIL
cd /d "%~dp0frontend"
call npm install
if errorlevel 1 (
  echo npm install fallito. Provo una reinstallazione pulita con npm ci...
  call npm ci
  if errorlevel 1 goto DEP_FAIL
)
cd /d "%~dp0"
echo Frontend dipendenze OK.
echo.

rem [5/6] Build sempre pulito.
echo [5/6] Ricostruzione completa del frontend...
if exist "frontend\.next" rmdir /s /q "frontend\.next"
if exist "frontend\.next" goto DEP_FAIL
cd /d "%~dp0frontend"
call npm run build
if errorlevel 1 (
  cd /d "%~dp0"
  echo ERRORE: il build Next.js e' fallito. Avvio bloccato.
  goto FAIL
)
cd /d "%~dp0"
echo Build OK.
echo.

rem [6/6] Avvio.
echo [6/6] Avvio AI Video Maker...
call "%~dp0avvia.bat"
set "EXITCODE=%errorlevel%"
if not "%EXITCODE%"=="0" goto FAIL
exit /b 0

:refresh_path
rem Ricarica PATH di macchina + utente dopo una installazione winget.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$m=[Environment]::GetEnvironmentVariable('Path','Machine');$u=[Environment]::GetEnvironmentVariable('Path','User');[Console]::Write($m+';'+$u)"`) do set "PATH=%%P"
exit /b 0

:DEP_FAIL
echo.
echo ================================================================
echo ERRORE NELL'INSTALLAZIONE/CONFIGURAZIONE
 echo ================================================================
echo Controlla la connessione Internet e i messaggi precedenti.
goto FAIL

:GIT_FAIL
echo.
echo ================================================================
echo ERRORE DI SINCRONIZZAZIONE GIT
 echo ================================================================
echo Nessun file locale viene cancellato automaticamente.
goto FAIL

:FAIL
echo.
echo ================================================================
echo OPERAZIONE NON COMPLETATA
 echo ================================================================
echo L'avvio viene bloccato per evitare di usare un'installazione incompleta.
echo.
pause
exit /b 1
