#!/bin/sh
# Die Akte starten (macOS: Doppelklick; Linux: ./start/start-akte.command). Braucht Docker.
set -e
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker fehlt. Bitte Docker Desktop installieren: https://www.docker.com/products/docker-desktop/"
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker läuft nicht. Bitte Docker Desktop starten und dann noch einmal."
  exit 1
fi

erster_start=0
if [ ! -f .env ]; then
  erster_start=1
  geheim=$(LC_ALL=C tr -dc 'A-Za-z0-9_-' </dev/urandom | head -c 64)
  sed "s/^DJANGO_SECRET_KEY=\$/DJANGO_SECRET_KEY=$geheim/" .env.example > .env
  chmod 600 .env
  echo ".env angelegt (mit neuem geheimen Schlüssel)."
fi

echo "Die Akte wird gebaut und gestartet. Beim ersten Mal dauert das einige Minuten."
docker compose up -d --build

if [ "$erster_start" = "1" ]; then
  echo
  echo "Jetzt das erste Konto für die Redaktion anlegen:"
  docker compose exec api python manage.py akte_einrichten
fi

port=$(grep -E '^AKTE_PORT=' .env | cut -d= -f2)
port=${port:-8080}
url="http://localhost:$port/akte"
if command -v open >/dev/null 2>&1; then open "$url"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$url"; fi
echo "Die Akte läuft: $url   (Stoppen: docker compose stop)"
