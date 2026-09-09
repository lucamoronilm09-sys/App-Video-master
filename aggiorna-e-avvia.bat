@echo off
setlocal
cd /d %~dp0
echo Sincronizzazione repository...
git fetch origin main
if errorlevel 1 (
  echo ERRORE: impossibile raggiungere GitHub.
  pause
  exit /b 1
)
git diff --quiet
if errorlevel 1 (
  echo ERRORE: hai modifiche locali non salvate. Non le sovrascrivo.
  echo Esegui git status per controllare.
  pause
  exit /b 1
)
git reset --hard origin/main
if errorlevel 1 (
  echo ERRORE: impossibile sincronizzare il repository.
  pause
  exit /b 1
)
echo Repository aggiornato.
call "%~dp0avvia.bat"
