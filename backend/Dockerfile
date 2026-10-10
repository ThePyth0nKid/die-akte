# Die Akte – Backend (Django, Gunicorn). Bau-Kontext ist die Wurzel des Repos (wegen beweis/).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AKTE_DATEN=/daten

WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
COPY beweis /tmp/beweis
RUN pip install -r /tmp/requirements.txt /tmp/beweis

COPY backend/ .
RUN useradd --create-home --uid 1000 akte \
    && mkdir -p /daten \
    && chown -R akte:akte /daten /app
USER akte

# Nur für den Bau: collectstatic braucht einen Schlüssel, signiert aber nichts. Im Betrieb kommt er aus .env.
RUN DJANGO_SECRET_KEY=nur-zum-bauen-collectstatic-signiert-nichts-0123456789 python manage.py collectstatic --noinput

EXPOSE 8000
ENTRYPOINT ["sh", "/app/start.sh"]
