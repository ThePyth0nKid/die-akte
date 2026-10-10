@echo off
rem Die Akte anhalten. Die Daten bleiben im Docker-Volume "akte-daten" erhalten.
cd /d "%~dp0.."
docker compose stop
pause
