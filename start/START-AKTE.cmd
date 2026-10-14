@echo off
rem Die Akte starten (Windows). Doppelklick reicht. Die Arbeit macht start\akte.ps1.
rem Einzige Pruefung hier: Wer aus der ZIP heraus startet, hat akte.ps1 nicht neben dieser Datei.
rem -Fenster heisst fuer akte.ps1: am Ende auf Enter warten, wenn Ein- und Ausgabe ein echtes Fenster sind.
rem Den Einrichtungscode zeigt keine Konsole; akte.ps1 oeffnet den Browser mit dem Code in der Adresse.
if not exist "%~dp0akte.ps1" goto nicht_entpackt
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0akte.ps1" start -Fenster %*
exit /b %ERRORLEVEL%

:nicht_entpackt
"%SystemRoot%\System32\chcp.com" 65001 >nul
echo.
echo Bitte zuerst entpacken: Rechtsklick auf die ZIP-Datei, dann „Alle extrahieren“.
echo Danach im entpackten Ordner „start“ öffnen und START-AKTE doppelklicken.
echo.
pause
exit /b 2
