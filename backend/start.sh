#!/bin/sh
# Start im Container: Datenbank auf Stand bringen, Cache-Tabelle anlegen, dann Gunicorn.
set -e
python manage.py migrate --noinput
python manage.py createcachetable
# --keep-alive länger als beim Client (Node/undici hält 4 s): sonst schließt Gunicorn eine Verbindung, die der
# Web-Proxy gerade wiederverwendet, und die Anfrage endet mit „other side closed“ (500 in der Oberfläche).
exec gunicorn aktesite.wsgi:application --bind 0.0.0.0:8000 --workers "${AKTE_WORKER:-2}" --threads 4 --timeout 180 --keep-alive 75
