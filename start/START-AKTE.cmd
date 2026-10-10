@echo off
rem Die Akte starten (Windows). Doppelklick genügt. Braucht Docker Desktop.
setlocal
cd /d "%~dp0.."
set PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker fehlt. Bitte Docker Desktop installieren: https://www.docker.com/products/docker-desktop/
  pause
  exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop laeuft nicht. Bitte starten und dann diese Datei noch einmal oeffnen.
  pause
  exit /b 1
)

set ERSTER_START=0
if not exist ".env" (
  set ERSTER_START=1
  "%PS%" -NoProfile -Command "$b = New-Object byte[] 48; (New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($b); $s = [Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_'); (Get-Content .env.example) -replace '^DJANGO_SECRET_KEY=$', ('DJANGO_SECRET_KEY=' + $s) | Set-Content -Encoding ascii .env"
  echo .env angelegt (mit neuem geheimen Schluessel).
)

echo Die Akte wird gebaut und gestartet. Beim ersten Mal dauert das einige Minuten.
docker compose up -d --build
if errorlevel 1 (
  echo Start fehlgeschlagen. Ausgabe oben lesen.
  pause
  exit /b 1
)

if "%ERSTER_START%"=="1" (
  echo.
  echo Jetzt das erste Konto fuer die Redaktion anlegen:
  docker compose exec api python manage.py akte_einrichten
)

for /f "tokens=2 delims==" %%p in ('findstr /b "AKTE_PORT=" .env') do set PORT=%%p
if "%PORT%"=="" set PORT=8080
start "" "http://localhost:%PORT%/akte"
echo Die Akte laeuft: http://localhost:%PORT%/akte   (Stoppen: start\STOP-AKTE.cmd)
pause
