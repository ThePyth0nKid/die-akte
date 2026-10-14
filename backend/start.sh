#!/bin/sh
# Start im Container: Datenbank auf Stand bringen, Cache-Tabelle anlegen, dann Gunicorn.
set -e
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py flushexpiredtokens

# Hintergrund-Arbeit (akte/hintergrund.py): Im Thread-Betrieb (Standard ohne Redis) gibt es genau EINEN Worker-Prozess
# mit mehr Threads, damit es genau eine Warteschlange der Beweissicherung gibt und das Nachholen beim Start
# (gunicorn.conf.py) nur einmal läuft. Mit Celery (Redis) bleiben es mehrere Worker.
MODUS=$(python -c 'from aktesite.settings import AKTE_HINTERGRUND; print(AKTE_HINTERGRUND)')
if [ "$MODUS" = "thread" ]; then
    if [ "${AKTE_WORKER:-1}" != "1" ]; then
        echo "Hinweis: Im Thread-Betrieb läuft genau ein Gunicorn-Worker; AKTE_WORKER=${AKTE_WORKER} gilt nur mit Celery."
    fi
    WORKER=1
    THREADS="${AKTE_THREADS:-8}"
else
    WORKER="${AKTE_WORKER:-2}"
    THREADS="${AKTE_THREADS:-4}"
fi

# --keep-alive länger als beim Client (Node/undici hält 4 s): sonst schließt Gunicorn eine Verbindung, die der
# Web-Proxy gerade wiederverwendet, und die Anfrage endet mit „other side closed“ (500 in der Oberfläche).
exec gunicorn aktesite.wsgi:application --bind 0.0.0.0:8000 --workers "$WORKER" --threads "$THREADS" \
    --timeout 180 --keep-alive 75
