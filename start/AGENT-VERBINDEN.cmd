@echo off
rem Claude Code mit der Akte verbinden (Windows). Doppelklick reicht. Die Arbeit macht start\akte.ps1.
if not exist "%~dp0akte.ps1" goto nicht_entpackt
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0akte.ps1" agent -Fenster %*
exit /b %ERRORLEVEL%

:nicht_entpackt
"%SystemRoot%\System32\chcp.com" 65001 >nul
echo.
echo Bitte zuerst entpacken: Rechtsklick auf die ZIP-Datei, dann „Alle extrahieren“.
echo Danach im entpackten Ordner „start“ öffnen und AGENT-VERBINDEN doppelklicken.
echo.
pause
exit /b 2
