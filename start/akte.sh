#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# shellcheck disable=SC1111  # Deutsche Anführungszeichen „…“ sind in Bash nur Text.
#
# Die Akte – Starter für macOS und Linux. Dieselben Befehle wie start/akte.ps1 unter Windows.
#
#   bash start/akte.sh [start]   Docker prüfen und starten, Akte bauen und starten, Browser öffnen
#   bash start/akte.sh stop      Akte anhalten; die Daten bleiben
#   bash start/akte.sh status    Zustand; mit --json als eine Zeile JSON für Agenten
#   bash start/akte.sh agent     Claude Code mit der Akte verbinden (uv, Token, claude mcp add)
#   bash start/akte.sh demo      Erfundene Demo-Akte „Freie Stadt Musterhafen“ laden
#
# Schalter: --still (keine Rückfragen; für Agenten) · --json (nur bei status) · --konto NAME · --ohne-browser
# (Die Windows-Schreibweise -Still, -Json, -Konto, -OhneBrowser geht auch; --fenster/-Fenster wird ignoriert.)
#
# Der Einrichtungscode für das erste Konto steht in keiner Konsole, auch nicht nach einem Doppelklick. start öffnet
# den Browser selbst, mit dem Code im Fragment der Adresse (#code=…; ein Fragment schickt der Browser an keinen
# Server), und die Seite trägt ihn ein. Geht kein Browser auf, bleibt der Notweg im Terminal (akte_einrichten fragt
# Name und Passwort und braucht keinen Code). Nach der Einrichtung löscht der Starter den Code aus .env. Eine Akte,
# die schon Daten hat, bekommt keinen neuen.
#
# Rückgabewerte: 0 fertig · 1 unerwarteter Fehler · 2 nicht entpackt · 3 Docker fehlt · 4 Docker läuft nicht ·
# 5 Port belegt · 6 Bau, Start oder Befehl fehlgeschlagen · 7 Claude Code fehlt · 8 uv fehlt · 9 erstes Konto fehlt
# oder Konto unklar · 10 Akte läuft nicht · 11 Akte-Baustein für den Agenten lädt nicht · 12 Token fehlt ·
# 13 claude mcp add fehlgeschlagen
#
# Umgebungsvariablen für Sonderfälle und Tests: AKTE_PORT, AKTE_DOCKER (Pfad zu docker), AKTE_DOCKER_WARTEN
# (Sekunden, Standard 180), AKTE_MCP_QUELLE, AKTE_OHNE_BROWSER=1. Nur für die Prüfskripte: AKTE_BROWSER (Programm
# statt des Standard-Browsers) wirkt nur zusammen mit AKTE_STARTER_TEST=1.
set -euo pipefail

AKTE_VERSION="0.2.0-rc.1"
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WURZEL="$(cd "$HIER/.." && pwd)"
START_ORDNER="$(pwd)"
ENV_DATEI="$WURZEL/.env"
MCP_QUELLE="${AKTE_MCP_QUELLE:-https://github.com/ThePyth0nKid/die-akte/archive/refs/tags/v$AKTE_VERSION.zip#subdirectory=mcp}"
AGENT_AUFRUF="bash \"$HIER/akte.sh\""
# uv lädt den Akte-Baustein für Claude. Feste Version des offiziellen Installers; die geladene Datei muss genau diese
# Prüfsumme haben, sonst läuft sie nicht (neue Version: Datei laden, sha256sum, beide Werte hier und in akte.ps1).
UV_VERSION="0.12.21"
UV_INSTALLER_URL="https://astral.sh/uv/$UV_VERSION/install.sh"
UV_INSTALLER_SHA256="0722d6c438395e39e1c27a86a79054d3b2820dd9399c7f8b0f6f84cd27ce36c3"
# Name des Daten-Volumes (Projekt „die-akte“ aus compose.yaml). Gibt es das, lief diese Akte schon einmal.
DATEN_VOLUME="die-akte_akte-daten"
DOCKER=""

befehl="start"
still=0
json=0
konto=""
ohne_browser=0
while [ $# -gt 0 ]; do
  case "$1" in
    start | stop | status | agent | demo) befehl="$1" ;;
    hilfe | help | -h | --help) befehl="hilfe" ;;
    --still | -Still | -still) still=1 ;;
    --json | -Json | -json) json=1 ;;
    --ohne-browser | -OhneBrowser) ohne_browser=1 ;;
    --fenster | -Fenster) ;; # früher: Code im Terminal zeigen; heute ohne Wirkung
    --konto | -Konto)
      if [ $# -ge 2 ]; then
        konto="$2"
        shift
      fi
      ;;
    *)
      echo "Unbekannt: $1 (Hilfe: bash start/akte.sh hilfe)" >&2
      exit 1
      ;;
  esac
  shift
done
if [ "${AKTE_OHNE_BROWSER:-}" = "1" ]; then ohne_browser=1; fi

# Ein Agent liest bei --json nur JSON: Bricht der Starter unerwartet ab, kommt auch das als JSON.
json_ausgegeben=0
# shellcheck disable=SC2317  # wird über trap aufgerufen
nach_ende() {
  local rc=$?
  if [ "$json" -eq 1 ] && [ "$json_ausgegeben" -eq 0 ] && [ "$rc" -ne 0 ]; then
    printf '{"fehler":"Unerwarteter Fehler (Rückgabe %s)."}\n' "$rc"
  fi
}
trap nach_ende EXIT

# ─── Ausgabe ─────────────────────────────────────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  GELB=$'\033[33m'
  GRUEN=$'\033[32m'
  ROT=$'\033[31m'
  AUS=$'\033[0m'
else
  GELB=""
  GRUEN=""
  ROT=""
  AUS=""
fi
sag() { if [ "$json" -eq 0 ]; then printf '%s\n' "$*"; fi; }
sag_farbe() {
  local farbe="$1"
  shift
  if [ "$json" -eq 0 ]; then printf '%s%s%s\n' "$farbe" "$*" "$AUS"; fi
}
ende() { exit "$1"; }

# ─── .env ────────────────────────────────────────────────────────────────────────────────────────────────────
env_wert() {
  if [ ! -f "$ENV_DATEI" ]; then
    printf ''
    return 0
  fi
  { grep -E "^[[:space:]]*${1}[[:space:]]*=" "$ENV_DATEI" || true; } | head -n 1 | cut -d= -f2- | tr -d '\r' |
    sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//"
}

setze_env_wert() {
  # Ersetzt NAME=… (sonst eine auskommentierte Zeile # NAME=…, sonst hängt sie an). Werte gehen über ENVIRON an awk,
  # nicht über -v: -v würde Backslashes im Wert als Escape-Folgen deuten.
  local name="$1" wert="$2" tmp muster=""
  tmp="$(mktemp "$WURZEL/.env.XXXXXX")"
  if [ -f "$ENV_DATEI" ]; then
    if grep -qE "^[[:space:]]*${name}[[:space:]]*=" "$ENV_DATEI"; then
      muster="^[[:space:]]*${name}[[:space:]]*="
    elif grep -qE "^[[:space:]]*#[[:space:]]*${name}[[:space:]]*=" "$ENV_DATEI"; then
      muster="^[[:space:]]*#[[:space:]]*${name}[[:space:]]*="
    fi
  fi
  if [ -n "$muster" ]; then
    AKTE_MUSTER="$muster" AKTE_ZEILE="$name=$wert" awk '
      BEGIN { m = ENVIRON["AKTE_MUSTER"]; z = ENVIRON["AKTE_ZEILE"]; fertig = 0 }
      { if (!fertig && $0 ~ m) { print z; fertig = 1 } else { print } }
    ' "$ENV_DATEI" >"$tmp"
  else
    if [ -f "$ENV_DATEI" ]; then cat "$ENV_DATEI" >"$tmp"; fi
    printf '%s=%s\n' "$name" "$wert" >>"$tmp"
  fi
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_DATEI"
}

zufall() { # $1 erlaubte Zeichen, $2 Länge → ZUFALL (nicht in $(…) aufrufen: ende muss den Starter beenden)
  # Erst eine feste Menge lesen, dann filtern. „tr </dev/urandom | head“ endet nur über SIGPIPE; ist es ignoriert
  # (vermutlich der Grund, warum die macOS-CI dort hing), liest das tr von macOS endlos weiter.
  local s="" runde=0
  while [ "${#s}" -lt "$2" ]; do
    runde=$((runde + 1))
    if [ "$runde" -gt 20 ]; then
      sag_farbe "$ROT" "Kein Zufall für den Schlüssel der Akte: /dev/urandom, head oder tr fehlt." >&2
      ende 1
    fi
    s="$s$(head -c 4096 /dev/urandom | LC_ALL=C tr -dc "$1" 2>/dev/null || true)"
  done
  ZUFALL="${s:0:$2}"
}

code_anzeige() {
  local c
  c="$(printf '%s' "$1" | tr -cd '[:alnum:]' | tr '[:lower:]' '[:upper:]')"
  if [ "${#c}" -eq 8 ]; then printf '%s-%s' "${c:0:4}" "${c:4:4}"; else printf '%s' "$c"; fi
}

akte_daten_da() { # 0 = das Daten-Volume gibt es: Diese Akte lief schon einmal und hat vielleicht schon Konten.
  "$DOCKER" volume inspect --format '{{.Name}}' "$DATEN_VOLUME" >/dev/null 2>&1
}

sichere_env_datei() {
  if [ ! -f "$ENV_DATEI" ]; then
    if [ -f "$WURZEL/.env.example" ]; then tr -d '\r' <"$WURZEL/.env.example" >"$ENV_DATEI"; else : >"$ENV_DATEI"; fi
    sag ".env angelegt (Einstellungen dieser Akte)."
  fi
  # Nur dein Konto darf .env lesen: Sie enthält den geheimen Schlüssel und den Einrichtungscode.
  chmod 600 "$ENV_DATEI" 2>/dev/null || true
  if [ -z "$(env_wert DJANGO_SECRET_KEY)" ]; then
    zufall 'A-Za-z0-9_-' 64
    setze_env_wert DJANGO_SECRET_KEY "$ZUFALL"
    sag "Neuer geheimer Schlüssel für diese Akte in .env gespeichert."
  fi
  # Einen Einrichtungscode bekommt nur eine Akte, die noch nie lief. Eine Akte mit Daten (neue Version, zweiter Start
  # nach der Einrichtung) bekommt keinen neuen: Dort gibt es schon ein Konto oder den Notweg im Terminal.
  if [ -z "$(env_wert AKTE_EINRICHTUNGSCODE)" ] && ! akte_daten_da; then
    zufall 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' 8
    setze_env_wert AKTE_EINRICHTUNGSCODE "$ZUFALL"
  fi
}

lies_port() {
  local p="${AKTE_PORT:-}"
  if [ -z "$p" ]; then p="$(env_wert AKTE_PORT)"; fi
  case "$p" in
    '' | *[!0-9]*) printf '8080' ;;
    *) printf '%s' "$p" ;;
  esac
}

# ─── Docker ──────────────────────────────────────────────────────────────────────────────────────────────────
finde_docker() {
  DOCKER=""
  if [ -n "${AKTE_DOCKER:-}" ]; then
    if [ -x "$AKTE_DOCKER" ]; then DOCKER="$AKTE_DOCKER"; fi
    return 0
  fi
  if command -v docker >/dev/null 2>&1; then
    DOCKER="$(command -v docker)"
    return 0
  fi
  local k
  for k in /usr/local/bin/docker /opt/homebrew/bin/docker "$HOME/.docker/bin/docker" \
    /Applications/Docker.app/Contents/Resources/bin/docker; do
    if [ -x "$k" ]; then
      DOCKER="$k"
      PATH="$(dirname "$k"):$PATH"
      export PATH
      return 0
    fi
  done
}

docker_zustand() {
  if [ -z "$DOCKER" ]; then
    printf 'fehlt'
    return 0
  fi
  if [ -n "$("$DOCKER" version --format '{{.Server.Version}}' 2>/dev/null || true)" ]; then printf 'laeuft'; else printf 'aus'; fi
}

akte_container() {
  if [ -z "$DOCKER" ]; then return 0; fi
  { "$DOCKER" ps --filter label=com.docker.compose.project=die-akte --filter status=running --format '{{.Names}}' 2>/dev/null || true; } |
    tr -d '\r' | sed -n -E 's/^die-akte-(api|web|proxy)-[0-9]+$/\1/p'
}

# Ohne „| grep -q“: Mit pipefail meldet eine Pipe sonst „Fehler“, wenn grep früh fertig ist und der Schreiber
# dadurch SIGPIPE bekommt.
akte_hat() { # $1 Dienst (api, web, proxy)
  local c
  c=" $(akte_container | tr '\n' ' ') "
  case "$c" in *" $1 "*) return 0 ;; esac
  return 1
}

akte_laeuft() {
  akte_hat api && akte_hat web && akte_hat proxy
}

meldung_docker_fehlt() {
  sag ""
  sag_farbe "$GELB" "Docker fehlt. Die Akte läuft in Docker, deshalb brauchst du es einmal."
  if [ "$(uname -s)" = "Darwin" ]; then
    sag "macOS: Docker Desktop laden: https://www.docker.com/products/docker-desktop/"
    sag "  (Apple-Chip M1/M2/M3/M4: „Apple Silicon“, ältere Macs: „Intel Chip“), installieren, einmal öffnen, Vertrag „Accept“."
  else
    sag "Linux: Docker Engine mit Compose installieren, z. B. Ubuntu/Debian: https://docs.docker.com/engine/install/"
    sag "  oder Docker Desktop für Linux: https://docs.docker.com/desktop/setup/install/linux/"
  fi
  sag "Docker Desktop ist für Privatleute, Bildung und kleine Firmen kostenlos."
  sag "Dann die Akte noch einmal starten."
}

warte_auf_docker() {
  if [ "$(docker_zustand)" = "laeuft" ]; then return 0; fi
  local meldung grenze beginn sek letzte=0
  meldung="$("$DOCKER" version 2>&1 >/dev/null || true)"
  if [[ "$meldung" == *"ermission denied"* ]]; then
    sag_farbe "$GELB" "Docker läuft, aber dein Konto darf es nicht benutzen."
    sag "Einmalig: sudo usermod -aG docker \$USER   – danach ab- und wieder anmelden."
    ende 4
  fi
  grenze="${AKTE_DOCKER_WARTEN:-180}"
  case "$grenze" in '' | *[!0-9]*) grenze=180 ;; esac
  if [ -z "${AKTE_DOCKER:-}" ]; then
    if [ "$(uname -s)" = "Darwin" ]; then
      sag "Docker Desktop läuft noch nicht. Ich starte es."
      open -a Docker >/dev/null 2>&1 || true
    elif command -v systemctl >/dev/null 2>&1; then
      systemctl --user start docker-desktop >/dev/null 2>&1 || true
      sag "Docker antwortet noch nicht. Läuft der Docker-Dienst? (z. B. sudo systemctl start docker)"
    fi
  else
    sag "Docker antwortet noch nicht."
  fi
  sag "Fragt ein Docker-Fenster nach dem Vertrag: „Accept“ klicken."
  sag "Ich warte bis zu $grenze Sekunden auf Docker …"
  beginn="$(date +%s)"
  while [ $(($(date +%s) - beginn)) -lt "$grenze" ]; do
    sleep 3
    if [ "$(docker_zustand)" = "laeuft" ]; then
      sag_farbe "$GRUEN" "Docker läuft."
      return 0
    fi
    sek=$(($(date +%s) - beginn))
    if [ $((sek - letzte)) -ge 15 ]; then
      sag "  … Docker startet noch ($sek Sekunden)"
      letzte=$sek
    fi
  done
  sag ""
  sag_farbe "$ROT" "Docker startet nicht."
  meldung="$("$DOCKER" version 2>&1 >/dev/null | tail -n 1 || true)"
  if [ -n "$meldung" ]; then sag "Docker meldet: $meldung"; fi
  sag "Öffne Docker Desktop und sieh nach, ob es etwas fragt. Dann die Akte noch einmal starten."
  ende 4
}

port_frei() { # 0 = frei
  if (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; then return 1; fi
  return 0
}

sichere_port() {
  local port p
  port="$(lies_port)"
  if port_frei "$port"; then
    printf '%s' "$port"
    return 0
  fi
  if akte_hat proxy; then
    printf '%s' "$port"
    return 0
  fi
  sag_farbe "$GELB" "Port $port ist belegt: Ein anderes Programm benutzt diese Adresse schon." >&2
  if [ -n "${AKTE_PORT:-}" ]; then
    sag "Die Umgebungsvariable AKTE_PORT=$AKTE_PORT legt den Port fest. Setz sie auf einen freien Port (z. B. 8081) oder entferne sie." >&2
    ende 5
  fi
  for ((p = port + 1; p <= port + 20; p++)); do
    if port_frei "$p"; then
      setze_env_wert AKTE_PORT "$p"
      sag "Die Akte nimmt stattdessen Port $p (gespeichert in .env als AKTE_PORT=$p)." >&2
      sag "War Claude schon mit der Akte verbunden: $AGENT_AUFRUF agent noch einmal ausführen." >&2
      printf '%s' "$p"
      return 0
    fi
  done
  sag "Zwischen $((port + 1)) und $((port + 20)) ist kein Port frei. Trag in .env bei AKTE_PORT einen freien Port ein." >&2
  ende 5
}

pruefe_entpackt() {
  if [ ! -f "$WURZEL/compose.yaml" ]; then
    sag_farbe "$GELB" "Bitte zuerst entpacken: Doppelklick auf die ZIP-Datei (macOS) bzw. unzip (Linux)."
    sag "(Neben dem Ordner „start“ fehlt die Datei compose.yaml: $WURZEL)"
    ende 2
  fi
}

pruefe_akte_laeuft() {
  finde_docker
  if [ -z "$DOCKER" ]; then
    meldung_docker_fehlt
    ende 3
  fi
  if [ "$(docker_zustand)" != "laeuft" ]; then
    sag_farbe "$GELB" "Docker läuft nicht, also auch die Akte nicht. Starte zuerst die Akte: $AGENT_AUFRUF start"
    ende 4
  fi
  if ! akte_laeuft; then
    sag_farbe "$GELB" "Die Akte läuft nicht. Starte sie zuerst: $AGENT_AUFRUF start"
    ende 10
  fi
}

http_hole() { # gibt "CODE<TAB>INHALT" aus oder nichts
  local url="$1" antwort
  if ! command -v curl >/dev/null 2>&1; then return 0; fi
  antwort="$(curl -s -m 5 -w '\n%{http_code}' "$url" 2>/dev/null || true)"
  if [ -z "$antwort" ]; then return 0; fi
  printf '%s\t%s' "$(printf '%s' "$antwort" | tail -n 1)" "$(printf '%s' "$antwort" | sed '$d')"
}

# ─── Einrichtung (erstes Konto) ──────────────────────────────────────────────────────────────────────────────
STAND_ERREICHBAR=0
STAND_OFFEN=0
STAND_GRUND=""
einrichtung_stand() { # $1 Port → STAND_ERREICHBAR, STAND_OFFEN, STAND_GRUND (nicht in $(…) aufrufen)
  # GET /api/v1/auth/einrichtung/ → {"offen": bool, "grund": "offen" | "kein_code" | "eingerichtet"}
  local r status inhalt
  local m_offen='"offen"[[:space:]]*:[[:space:]]*true'
  local m_grund='"grund"[[:space:]]*:[[:space:]]*"(offen|kein_code|eingerichtet)"'
  STAND_ERREICHBAR=0
  STAND_OFFEN=0
  STAND_GRUND=""
  r="$(http_hole "http://127.0.0.1:$1/api/v1/auth/einrichtung/")"
  if [ -z "$r" ]; then return 0; fi
  status="${r%%$'\t'*}"
  inhalt="${r#*$'\t'}"
  case "$status" in '' | *[!0-9]*) return 0 ;; esac
  if [ "$status" -lt 500 ]; then STAND_ERREICHBAR=1; fi
  if [ "$status" -ne 200 ]; then return 0; fi
  if [[ "$inhalt" =~ $m_offen ]]; then STAND_OFFEN=1; fi
  if [[ "$inhalt" =~ $m_grund ]]; then STAND_GRUND="${BASH_REMATCH[1]}"; fi
  if [ -z "$STAND_GRUND" ]; then
    # Eine Akte ohne „grund“ in der Antwort: aus den übrigen Angaben ableiten.
    if [ "$STAND_OFFEN" -eq 1 ]; then
      STAND_GRUND="offen"
    elif [ -n "$(env_wert AKTE_EINRICHTUNGSCODE)" ]; then
      STAND_GRUND="eingerichtet"
    else
      STAND_GRUND="kein_code"
    fi
  fi
}

entferne_verbrauchten_code() {
  # Das erste Konto steht: Der Code wird nie wieder gebraucht. Ohne Code in .env öffnet auch ein später deaktiviertes
  # Konto die Einrichtung nicht wieder (wirkt beim nächsten Start der Akte).
  if [ -z "$(env_wert AKTE_EINRICHTUNGSCODE)" ]; then return 0; fi
  setze_env_wert AKTE_EINRICHTUNGSCODE ""
  sag "Das erste Konto steht. Den Einrichtungscode habe ich aus .env gelöscht; er wird nicht mehr gebraucht."
}

meldung_notweg() {
  # Der Weg ohne Browser und ohne Code: akte_einrichten fragt Benutzername und Passwort im Terminal.
  sag "Das erste Konto legt ein Mensch dann im Terminal an. Er braucht dafür keinen Code; das Passwort bleibt beim"
  sag "Tippen unsichtbar:"
  sag "  cd \"$WURZEL\" && docker compose exec api python manage.py akte_einrichten"
}

meldung_kein_code() {
  sag_farbe "$GELB" "Es gibt noch kein Konto und keinen Einrichtungscode: Diese Akte hat Daten aus einem früheren Start."
  meldung_notweg
}

oeffne_browser() { # 0 = ein Browser wurde gestartet. Schreibt die Adresse nie aus: Sie kann den Einrichtungscode tragen.
  # AKTE_BROWSER (ein Programm statt des Standard-Browsers) gilt nur für die Prüfskripte (AKTE_STARTER_TEST=1).
  if [ "$ohne_browser" -eq 1 ]; then return 1; fi
  if [ -n "${AKTE_BROWSER:-}" ] && [ "${AKTE_STARTER_TEST:-}" = "1" ]; then
    "$AKTE_BROWSER" "$1" </dev/null >/dev/null 2>&1 &
    return 0
  fi
  if [ "$(uname -s)" = "Darwin" ] && command -v open >/dev/null 2>&1; then
    if open "$1" >/dev/null 2>&1; then return 0; fi
  elif command -v xdg-open >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    if xdg-open "$1" </dev/null >/dev/null 2>&1; then return 0; fi
  fi
  return 1
}

zeige_einrichtung() { # $1 Basis-Adresse
  # Der Code geht nur an den Browser (Fragment der Adresse), nie in eine Konsole.
  local seite="$1/akte/einrichten" code ziel im_browser=0
  code="$(code_anzeige "$(env_wert AKTE_EINRICHTUNGSCODE)")"
  sag_farbe "$GRUEN" "Die Akte läuft. Jetzt fehlt nur noch dein erstes Konto."
  ziel="$seite"
  if [ -n "$code" ]; then ziel="$seite#code=$code"; fi
  if oeffne_browser "$ziel"; then
    im_browser=1
    sag "Der Browser ist offen: wähl dort Name und Passwort."
    sag "Seite: $seite"
    if [ -n "$code" ]; then sag "Der Einrichtungscode ist dort schon eingetragen. Seite geschlossen? start noch einmal aufrufen."; fi
  else
    sag_farbe "$GELB" "Kein Browser ist aufgegangen. Seite: $seite"
  fi
  if [ -z "$code" ]; then sag_farbe "$GELB" "In .env steht kein Einrichtungscode mehr."; fi
  if [ -z "$code" ] || [ "$im_browser" -eq 0 ]; then meldung_notweg; fi
  sag "Passwort: mindestens 10 Zeichen. Das Passwort tippst nur du, nie ein Agent."
}

agent_verbunden() {
  # Wie Agent-Verbunden in akte.ps1: Eintrag „akte“ mit akte-mcp, und nennt AKTE_BASIS einen Port, ist es der jetzige.
  local datei="${CLAUDE_CONFIG_DIR:-$HOME}/.claude.json" flach treffer basis eintrag_port=""
  if [ ! -f "$datei" ]; then return 1; fi
  flach="$(tr -d '\n' <"$datei")"
  # grep -c und sed -n lesen bis zum Ende (kein SIGPIPE beim Schreiber wie bei grep -q oder head).
  treffer="$(printf '%s' "$flach" | grep -Ec '"akte"[[:space:]]*:[[:space:]]*\{[^{}]*"akte-mcp"' || true)"
  [ "${treffer:-0}" -gt 0 ] || return 1
  basis="$(printf '%s' "$flach" | grep -Eo '"akte"[[:space:]]*:[[:space:]]*\{[^{}]*(\{[^{}]*\}[^{}]*)*\}' \
    | grep -Eo '"AKTE_BASIS"[[:space:]]*:[[:space:]]*"[^"]*"' | sed -n '1p' || true)"
  basis="${basis%\"}"
  eintrag_port="$(printf '%s' "$basis" | sed -n 's/.*:\([0-9][0-9]*\)\/\{0,1\}$/\1/p')"
  if [ -n "$eintrag_port" ] && [ "$eintrag_port" != "$(lies_port)" ]; then return 1; fi
  return 0
}

# ─── Befehle ─────────────────────────────────────────────────────────────────────────────────────────────────
befehl_start() {
  pruefe_entpackt
  sag "Die Akte startet."
  finde_docker
  if [ -z "$DOCKER" ]; then
    meldung_docker_fehlt
    ende 3
  fi
  warte_auf_docker
  sichere_env_datei
  local port protokoll code=0 url basis
  port="$(sichere_port)"
  sag "Die Akte wird gebaut und gestartet. Beim ersten Mal dauert das 3 bis 10 Minuten."
  if [ "$still" -eq 1 ]; then
    protokoll="${TMPDIR:-/tmp}/die-akte-start.log"
    (cd "$WURZEL" && "$DOCKER" compose up -d --build --wait) >"$protokoll" 2>&1 || code=$?
    if [ "$code" -ne 0 ]; then
      sag "Letzte Zeilen von Docker:"
      tail -n 25 "$protokoll" | sed 's/^/  /'
      sag "Ganzes Protokoll: $protokoll"
    fi
  else
    (cd "$WURZEL" && "$DOCKER" compose up -d --build --wait) || code=$?
  fi
  if [ "$code" -ne 0 ]; then
    sag ""
    sag_farbe "$ROT" "Start fehlgeschlagen."
    sag "Häufige Gründe: kein Internet beim ersten Start, zu wenig Speicherplatz (10 GB frei einplanen), Docker hängt."
    sag "Genaueres im Akte-Ordner: docker compose logs api"
    ende 6
  fi
  for _ in $(seq 1 15); do
    einrichtung_stand "$port"
    if [ "$STAND_ERREICHBAR" -eq 1 ]; then break; fi
    sleep 2
  done
  basis="http://localhost:$port"
  sag ""
  if [ "$STAND_OFFEN" -eq 1 ]; then
    zeige_einrichtung "$basis"
  else
    url="$basis/akte"
    sag_farbe "$GRUEN" "Die Akte läuft: $url"
    if [ "$STAND_ERREICHBAR" -eq 0 ]; then sag "Die Seite antwortet noch nicht. Warte eine Minute und lade sie dann neu."; fi
    if [ "$STAND_GRUND" = "eingerichtet" ]; then
      entferne_verbrauchten_code
    elif [ "$STAND_GRUND" = "kein_code" ]; then
      meldung_kein_code
    fi
    if oeffne_browser "$url"; then sag "Browser geöffnet: $url"; fi
  fi
  sag "Sie läuft im Hintergrund weiter, auch nach einem Neustart, sobald Docker läuft."
  sag "Stoppen: $AGENT_AUFRUF stop"
  if ! agent_verbunden; then sag "Claude Code verbinden: $AGENT_AUFRUF agent"; fi
  ende 0
}

befehl_stop() {
  pruefe_entpackt
  finde_docker
  if [ -z "$DOCKER" ] || [ "$(docker_zustand)" != "laeuft" ]; then
    sag "Docker läuft nicht, die Akte ist also schon aus."
    ende 0
  fi
  local ids
  if [ -f "$ENV_DATEI" ]; then
    if (cd "$WURZEL" && "$DOCKER" compose stop); then
      sag_farbe "$GRUEN" "Die Akte ist angehalten. Deine Daten bleiben erhalten."
      ende 0
    fi
  else
    ids="$("$DOCKER" ps -q --filter label=com.docker.compose.project=die-akte || true)"
    # shellcheck disable=SC2086  # mehrere Kennungen, absichtlich getrennt
    if [ -z "$ids" ] || "$DOCKER" stop $ids >/dev/null; then
      sag_farbe "$GRUEN" "Die Akte ist angehalten. Deine Daten bleiben erhalten."
      ende 0
    fi
  fi
  sag_farbe "$ROT" "Anhalten hat nicht geklappt."
  ende 6
}

befehl_status() {
  # Für Agenten: Der Einrichtungscode gehört nicht hierher (siehe Kopf der Datei).
  local port docker_z akte="aus" offen=false grund_json="null" url verbunden=false
  port="$(lies_port)"
  finde_docker
  docker_z="$(docker_zustand)"
  if [ "$docker_z" = "laeuft" ] && akte_laeuft; then akte="laeuft"; fi
  if [ "$akte" = "laeuft" ]; then
    einrichtung_stand "$port"
    if [ "$STAND_OFFEN" -eq 1 ]; then offen=true; fi
    if [ -n "$STAND_GRUND" ]; then grund_json="\"$STAND_GRUND\""; fi
  fi
  url="http://localhost:$port/akte"
  if [ "$offen" = true ]; then url="http://localhost:$port/akte/einrichten"; fi
  if agent_verbunden; then verbunden=true; fi
  if [ "$json" -eq 1 ]; then
    printf '{"docker":"%s","akte":"%s","url":"%s","einrichtung_offen":%s,"einrichtung_grund":%s,"agent_verbunden":%s}\n' \
      "$docker_z" "$akte" "$url" "$offen" "$grund_json" "$verbunden"
    json_ausgegeben=1
    ende 0
  fi
  local docker_text="$docker_z" verbunden_text="nein"
  if [ "$docker_z" = "laeuft" ]; then docker_text="läuft"; fi
  if [ "$docker_z" = "aus" ]; then docker_text="aus (oder startet noch)"; fi
  if [ "$verbunden" = true ]; then verbunden_text="ja"; fi
  sag "Docker:            $docker_text"
  if [ "$akte" = "laeuft" ]; then sag "Akte:              läuft – $url"; else sag "Akte:              aus"; fi
  if [ "$offen" = true ]; then
    sag "Erstes Konto:      fehlt noch → $url"
  elif [ "$grund_json" = '"kein_code"' ]; then
    sag "Erstes Konto:      fehlt; ohne Einrichtungscode geht es nur im Terminal (akte_einrichten)"
  elif [ "$akte" = "laeuft" ]; then
    sag "Erstes Konto:      angelegt"
  fi
  sag "Claude verbunden:  $verbunden_text"
  ende 0
}

befehl_demo() {
  pruefe_entpackt
  pruefe_akte_laeuft
  local port url ausgabe
  port="$(lies_port)"
  url="http://localhost:$port/akte/demo-musterhafen"
  sag "Ich lade die erfundene Demo-Akte „Freie Stadt Musterhafen“ (bis zu einer Minute) …"
  if ausgabe="$(cd "$WURZEL" && "$DOCKER" compose exec -T api python manage.py akte_demo 2>&1)"; then
    sag_farbe "$GRUEN" "Demo geladen: $url"
  elif [[ "$ausgabe" == *'gibt es schon'* ]]; then
    sag_farbe "$GRUEN" "Die Demo ist schon da: $url"
  else
    sag_farbe "$ROT" "Die Demo ließ sich nicht laden:"
    printf '%s\n' "$ausgabe" | tail -n 15 | sed 's/^/  /'
    ende 6
  fi
  sag "Zum Ansehen meldest du dich im Browser mit deinem Konto an."
  if oeffne_browser "$url"; then sag "Browser geöffnet: $url"; fi
  ende 0
}

finde_konto() { # $1 Grund aus einrichtung_stand
  if [ -n "$konto" ]; then
    printf '%s' "$konto"
    return 0
  fi
  local konten anzahl
  # Wer an der Akte arbeiten darf: aktive Konten der Redaktion oder Superuser, dieselbe Auswahl wie bei der
  # Einrichtung. akte_konten gibt je Konto eine Zeile KONTO:name aus.
  konten="$( (cd "$WURZEL" && "$DOCKER" compose exec -T api python manage.py akte_konten) 2>/dev/null | tr -d '\r' | sed -n 's/^KONTO://p' || true)"
  anzahl="$(printf '%s' "$konten" | grep -c . || true)"
  if [ "$anzahl" = "1" ]; then
    printf '%s' "$konten"
    return 0
  fi
  if [ "$anzahl" = "0" ]; then
    sag_farbe "$GELB" "Ich finde kein Konto für die Redaktion." >&2
    if [ "${1:-}" = "kein_code" ]; then
      meldung_kein_code >&2
    else
      sag "Leg zuerst im Browser dein erstes Konto an und starte das hier dann noch einmal." >&2
    fi
    ende 9
  fi
  sag_farbe "$GELB" "Es gibt mehrere Konten: $(printf '%s' "$konten" | tr '\n' ' '). Sag mir, welches Claude benutzen soll:" >&2
  sag "  $AGENT_AUFRUF agent --konto NAME" >&2
  ende 9
}

sha256_von() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

installiere_uv() { # gibt nichts aus, wenn der Installer gelaufen ist, sonst den Grund
  local datei ist
  datei="$(mktemp "${TMPDIR:-/tmp}/uv-installer.XXXXXX")"
  if ! curl -LsSf "$UV_INSTALLER_URL" -o "$datei" 2>/dev/null; then
    rm -f "$datei"
    printf 'Laden von %s fehlgeschlagen.' "$UV_INSTALLER_URL"
    return 0
  fi
  ist="$(sha256_von "$datei")"
  if [ "$ist" != "$UV_INSTALLER_SHA256" ]; then
    rm -f "$datei"
    printf 'Der geladene Installer hat nicht die erwartete Prüfsumme (erwartet %s, bekommen %s). Ich führe ihn nicht aus.' \
      "$UV_INSTALLER_SHA256" "${ist:-keine}"
    return 0
  fi
  # Ohne Variablen, mit denen der Aufrufer den Installer auf eine andere Download-Quelle oder einen anderen Ordner
  # umlenken könnte: Er soll genau die geprüfte Version an den üblichen Ort legen.
  if ! env -u UV_DOWNLOAD_URL -u INSTALLER_DOWNLOAD_URL -u UV_INSTALLER_GITHUB_BASE_URL -u UV_INSTALLER_GHE_BASE_URL \
    -u UV_INSTALL_DIR -u CARGO_DIST_FORCE_INSTALL_DIR -u UV_UNMANAGED_INSTALL -u UV_GITHUB_TOKEN \
    sh "$datei" >/dev/null 2>&1; then
    rm -f "$datei"
    printf 'Der Installer ist fehlgeschlagen.'
    return 0
  fi
  rm -f "$datei"
}

befehl_agent() {
  pruefe_entpackt
  sag "Ich verbinde Claude Code mit deiner Akte."
  local lokal="$HOME/.local/bin" claude uvx port konto_name token ausgabe grund
  case ":$PATH:" in *":$lokal:"*) ;; *) PATH="$PATH:$lokal" && export PATH ;; esac
  claude="$(command -v claude || true)"
  if [ -z "$claude" ] && [ -x "$lokal/claude" ]; then claude="$lokal/claude"; fi
  if [ -z "$claude" ]; then
    sag_farbe "$GELB" "Claude Code fehlt. Installieren wie in docs/erste-schritte.md (Mac und Linux) beschrieben, mit dem offiziellen Installer von claude.ai."
    sag "Danach ein neues Terminal öffnen, claude starten und anmelden (Claude-Abo Pro oder Max)."
    ende 7
  fi
  pruefe_akte_laeuft
  port="$(lies_port)"
  einrichtung_stand "$port"
  if [ "$STAND_OFFEN" -eq 1 ]; then
    sag_farbe "$GELB" "Es gibt noch kein Konto. Leg zuerst im Browser dein erstes Konto an:"
    sag "  http://localhost:$port/akte/einrichten"
    sag "Ist die Seite zu oder das Feld für den Einrichtungscode leer: $AGENT_AUFRUF start noch einmal"
    sag "  (bzw. Doppelklick auf start-akte.command). Er öffnet die Seite mit dem Code."
    sag "Geht kein Browser auf: Notweg im Terminal, ohne Code (fragt Benutzername und Passwort):"
    sag "  cd \"$WURZEL\" && docker compose exec api python manage.py akte_einrichten"
    ende 9
  fi
  if [ "$STAND_GRUND" = "eingerichtet" ]; then entferne_verbrauchten_code; fi
  konto_name="$(finde_konto "$STAND_GRUND")"
  sag "Konto für Claude: $konto_name"

  uvx="$(command -v uvx || true)"
  if [ -z "$uvx" ] && [ -x "$lokal/uvx" ]; then uvx="$lokal/uvx"; fi
  if [ -z "$uvx" ]; then
    sag "uv fehlt (damit startet Claude den Akte-Baustein). Ich installiere uv $UV_VERSION mit dem offiziellen Installer von astral.sh …"
    grund="$(installiere_uv)"
    uvx="$(command -v uvx || true)"
    if [ -z "$uvx" ] && [ -x "$lokal/uvx" ]; then uvx="$lokal/uvx"; fi
    if [ -z "$uvx" ]; then
      sag_farbe "$ROT" "uv ließ sich nicht installieren."
      if [ -n "$grund" ]; then sag "  $grund"; fi
      sag "Von Hand (drei Zeilen: laden, Prüfsumme vergleichen, erst dann ausführen):"
      sag "  curl -LsSf -o /tmp/uv-install.sh $UV_INSTALLER_URL"
      sag "  shasum -a 256 /tmp/uv-install.sh   (muss lauten: $UV_INSTALLER_SHA256)"
      sag "  sh /tmp/uv-install.sh"
      ende 8
    fi
    sag_farbe "$GRUEN" "uv ist installiert."
  fi

  # Vorwärmen mit dem Server selbst (--selbsttest), nicht nur der CLI: sonst läuft Claudes erster Start in die
  # Zeitgrenze (Durchlauf 3, wie in akte.ps1).
  sag "Ich lade den Akte-Baustein für Claude (einmalig, bis zu 2 Minuten) …"
  if ! ausgabe="$("$uvx" --python 3.12 --from "$MCP_QUELLE" akte-mcp --selbsttest 2>&1)"; then
    sag_farbe "$ROT" "Der Akte-Baustein ließ sich nicht laden."
    printf '%s\n' "$ausgabe" | tail -n 15 | sed 's/^/  /'
    sag "Quelle: $MCP_QUELLE"
    ende 11
  fi

  token="$( (cd "$WURZEL" && "$DOCKER" compose exec -T api python manage.py akte_token "$konto_name") 2>/dev/null | tr -d '\r' | grep -E '^[A-Za-z0-9_-]{20,}$' | tail -n 1 || true)"
  if [ -z "$token" ]; then
    sag_farbe "$ROT" "Den Schlüssel für Claude (Token) konnte ich nicht holen."
    ende 12
  fi

  (cd "$START_ORDNER" && "$claude" mcp remove akte -s local >/dev/null 2>&1) || true
  (cd "$START_ORDNER" && "$claude" mcp remove akte -s user >/dev/null 2>&1) || true
  if ! ausgabe="$(cd "$START_ORDNER" && "$claude" mcp add --scope user akte -e "AKTE_BASIS=http://127.0.0.1:$port" -e "AKTE_TOKEN=$token" -- uvx --python 3.12 --from "$MCP_QUELLE" akte-mcp 2>&1)"; then
    sag_farbe "$ROT" "claude mcp add ist fehlgeschlagen:"
    printf '%s\n' "${ausgabe//$token/***}" | tail -n 10 | sed 's/^/  /'
    ende 13
  fi

  sag ""
  sag_farbe "$GRUEN" "Claude Code ist jetzt mit deiner Akte verbunden."
  sag "Fertig. Beende Claude (/exit) und starte es neu mit: claude --continue"
  sag "Danach zeigt /mcp den Eintrag „akte“ als verbunden."
  sag "Der Schlüssel für die Verbindung steht jetzt in deiner Claude-Einstellung (~/.claude.json). Gib diese Datei nicht weiter."
  ende 0
}

befehl_hilfe() {
  sag "Die Akte – Starter für macOS und Linux"
  sag ""
  sag "  $AGENT_AUFRUF start      starten (Standard)"
  sag "  $AGENT_AUFRUF stop       anhalten"
  sag "  $AGENT_AUFRUF status     Zustand; mit --json für Agenten"
  sag "  $AGENT_AUFRUF agent      Claude Code verbinden"
  sag "  $AGENT_AUFRUF demo       Demo-Akte laden"
  sag ""
  sag "Schalter: --still (keine Rückfragen), --json (nur bei status), --konto NAME, --ohne-browser"
  ende 0
}

if [ "$json" -eq 1 ] && [ "$befehl" != "status" ]; then
  # Bei allen anderen Befehlen bliebe die Ausgabe mit --json sonst einfach leer.
  printf '{"fehler":"--json gibt es nur beim Befehl status (aufgerufen: %s)."}\n' "$befehl"
  json_ausgegeben=1
  exit 1
fi

case "$befehl" in
  start) befehl_start ;;
  stop) befehl_stop ;;
  status) befehl_status ;;
  agent) befehl_agent ;;
  demo) befehl_demo ;;
  *) befehl_hilfe ;;
esac
