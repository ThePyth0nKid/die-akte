#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Prüft gegen eine laufende Akte (docker compose up), dass der Eingang (Caddy) nur die Namen aus AKTE_HOSTS bedient
# und Django dieselben Namen annimmt; danach dasselbe mit einer eigenen Domain aus der Umgebung (AKTE_HOSTS und
# DJANGO_ALLOWED_HOSTS überschreiben). Startet dafür die Akte einmal neu.
#
# NUR IN DER CI (Job stack-hostfilter in .github/workflows/ci.yml): Der Lauf baut und startet Container, die auf einem
# Port lauschen. Lokal bricht das Skript ab, außer mit HOSTFILTER_LOKAL=1.
set -euo pipefail

if [ "${CI:-}" != "true" ] && [ "${HOSTFILTER_LOKAL:-}" != "1" ]; then
  echo "Nur für die CI gedacht (startet Container). Lokal mit HOSTFILTER_LOKAL=1." >&2
  exit 2
fi

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
BASIS="http://127.0.0.1:${AKTE_PORT:-8080}"
API="/api/v1/auth/einrichtung/"
ANTWORT="$(mktemp)"
trap 'rm -f "$ANTWORT"' EXIT
fehler=0
geprueft=0

status_fuer() { # $1 Host-Kopf, $2 Pfad → HTTP-Status
  curl -s -o "$ANTWORT" -w '%{http_code}' -H "Host: $1" "$BASIS$2" || true
}

erwarte() { # $1 Host-Kopf, $2 erwartete Status (z. B. "200" oder "421|400"), $3 Pfad (Standard: API)
  local pfad="${3:-$API}" ist
  ist="$(status_fuer "$1" "$pfad")"
  geprueft=$((geprueft + 1))
  case "|$2|" in
    *"|$ist|"*) echo "ok      Host '$1' $pfad -> $ist" ;;
    *)
      fehler=$((fehler + 1))
      echo "FEHLER  Host '$1' $pfad -> $ist (erwartet $2)"
      head -c 300 "$ANTWORT" | sed 's/^/        /'
      echo
      ;;
  esac
}

erwarte_text() { # $1 Host-Kopf, $2 Teil der Antwort
  status_fuer "$1" "$API" >/dev/null
  geprueft=$((geprueft + 1))
  if grep -qF "$2" "$ANTWORT"; then
    echo "ok      Host '$1': Antwort nennt $2"
  else
    fehler=$((fehler + 1))
    echo "FEHLER  Host '$1': Antwort nennt $2 nicht"
  fi
}

echo "== Standard (AKTE_HOSTS nicht gesetzt)"
erwarte "localhost:8080" 200
erwarte "localhost:8080" "200|307|308" "/akte"
erwarte "LOCALHOST" 200
erwarte "127.0.0.1:8080" 200
erwarte "[::1]:8080" 200
# Kein Name mit Punkt am Ende: Caddy vergleicht den Namen wörtlich (Django würde den Punkt entfernen).
erwarte "localhost." 421
erwarte "evil.localhost" 421
erwarte "evil.example" 421
erwarte "evil.example" 421 "/akte"
# Leerer Host-Kopf: Caddy 421, oder der Server lehnt die Anfrage schon vorher ab (400).
erwarte "" "421|400"
erwarte_text "evil.example" "AKTE_HOSTS"

echo "== Eigene Domain aus der Umgebung (AKTE_HOSTS, DJANGO_ALLOWED_HOSTS)"
AKTE_HOSTS="akte.example.org localhost" DJANGO_ALLOWED_HOSTS="akte.example.org,localhost" \
  docker compose up -d --wait >/dev/null
erwarte "akte.example.org" 200
erwarte "akte.example.org:8080" 200
erwarte "localhost:8080" 200
erwarte "127.0.0.1:8080" 421
erwarte "evil.example" 421

echo
if [ "$fehler" -gt 0 ]; then
  echo "$fehler von $geprueft Prüfungen fehlgeschlagen."
  exit 1
fi
echo "Alle $geprueft Prüfungen bestanden."
