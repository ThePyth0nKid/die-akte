#!/bin/sh
# Start im Container: Datenbank auf Stand bringen, Cache-Tabelle anlegen, dann Gunicorn.
set -e
python manage.py migrate --noinput
python manage.py createcachetable
exec gunicorn aktesite.wsgi:application --bind 0.0.0.0:8000 --workers "${AKTE_WORKER:-2}" --threads 4 --timeout 180
