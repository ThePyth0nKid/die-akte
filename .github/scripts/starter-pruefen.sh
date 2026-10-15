#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# shellcheck disable=SC2319  # "[ … ]; echo $?" liefert hier absichtlich das Ergebnis der Bedingung.
# shellcheck disable=SC1111  # Deutsche Anführungszeichen „…“ sind in Bash nur Text.
#
# Prüft start/akte.sh ohne echtes Docker, ohne echtes Claude Code, ohne echten Browser und ohne Internet (Attrappen
# für docker, claude, uvx, den Browser und eine kleine HTTP-Attrappe der Akte). Läuft in der CI (ubuntu-latest und
# macOS) und lokal:
#   bash .github/scripts/starter-pruefen.sh
# Braucht python3 (für die HTTP-Attrappe und das Lesen von JSON); anderer Name über PYTHON=…
# Die Starter selbst laufen mit STARTER_BASH (Standard: bash aus dem Pfad). Auf dem Mac setzt die CI /bin/bash, die
# Bash 3.2, mit der ein Doppelklick auf start-akte.command läuft; dieses Prüfskript braucht eine neuere Bash.
#
# Wie unter Windows: Der Einrichtungscode erscheint in keiner Konsole; er geht nur im Fragment (#code=…) an den
# Browser. Nach der Einrichtung verschwindet er aus .env, und eine Akte mit Daten bekommt keinen neuen. Die
# Browser-Attrappe wirkt nur mit AKTE_STARTER_TEST=1; lauf setzt beides, damit nie ein echter Browser aufgeht.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python3}"
STARTER_BASH="${STARTER_BASH:-bash}"
ARBEIT="$(mktemp -d)"
fehler=0
geprueft=0
server_pid=""

aufraeumen() {
  if [ -n "$server_pid" ]; then kill "$server_pid" 2>/dev/null || true; fi
  rm -rf "$ARBEIT"
}
trap aufraeumen EXIT

pruefe() { # $1 Name, $2 0 = ok, $3 Info
  geprueft=$((geprueft + 1))
  if [ "$2" -eq 0 ]; then
    echo "ok      $1"
  else
    fehler=$((fehler + 1))
    echo "FEHLER  $1"
    if [ -n "${3:-}" ]; then printf '%s\n' "$3" | sed 's/^/        /'; fi
  fi
}

enthaelt() { # $1 Text, $2 Teil
  case "$1" in *"$2"*) return 0 ;; esac
  return 1
}

kopie() {
  local ziel="$ARBEIT/$1"
  mkdir -p "$ziel/start"
  cp "$REPO/compose.yaml" "$REPO/.env.example" "$ziel/"
  cp "$REPO/start/akte.sh" "$ziel/start/"
  printf '%s' "$ziel"
}

freier_port() {
  "$PY" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

env_code() { # $1 Ordner → Wert von AKTE_EINRICHTUNGSCODE; "FEHLT", wenn die Zeile fehlt
  if grep -q '^AKTE_EINRICHTUNGSCODE=' "$1/.env"; then sed -n 's/^AKTE_EINRICHTUNGSCODE=//p' "$1/.env"; else printf 'FEHLT'; fi
}

# ─── Attrappen ──────────────────────────────────────────────────────────────────────────────────────────────
ATTRAPPEN="$ARBEIT/attrappen"
mkdir -p "$ATTRAPPEN" "$ARBEIT/claude"
PROTOKOLL="$ARBEIT/aufrufe.log"
BROWSER_LOG="$ARBEIT/browser.log"
: >"$PROTOKOLL"
cat >"$ATTRAPPEN/docker" <<'ENDE'
#!/usr/bin/env bash
echo "docker $*" >>"$ATTRAPPE_LOG"
case "$1" in
  version | info)
    if [ "${ATTRAPPE_DOCKER_AUS:-}" = 1 ]; then echo "Cannot connect to the Docker daemon" >&2; exit 1; fi
    echo "99.0.0-attrappe" ;;
  ps)
    if [ "${ATTRAPPE_AKTE_LAEUFT:-}" = 1 ]; then printf 'die-akte-api-1\ndie-akte-web-1\ndie-akte-proxy-1\n'; fi ;;
  volume)
    if [ "${ATTRAPPE_DATEN:-}" = 1 ]; then echo "die-akte_akte-daten"; else echo "no such volume" >&2; exit 1; fi ;;
  compose)
    case "$*" in
      *akte_token*) echo "ATTRAPPExTOKENxATTRAPPExTOKENxATTRAPPExx" ;;
      *akte_konten*) echo "KONTO:testkonto" ;;
      *akte_demo*) echo "Demo-Akte angelegt: /akte/demo-musterhafen" ;;
    esac ;;
esac
exit 0
ENDE
cat >"$ATTRAPPEN/claude" <<'ENDE'
#!/usr/bin/env bash
echo "claude $*" >>"$ATTRAPPE_LOG"
if [ "${2:-}" = remove ]; then exit 1; fi
exit 0
ENDE
cat >"$ATTRAPPEN/uvx" <<'ENDE'
#!/usr/bin/env bash
echo "uvx $*" >>"$ATTRAPPE_LOG"
echo "usage: akte [-h]"
ENDE
cat >"$ATTRAPPEN/browser" <<'ENDE'
#!/usr/bin/env bash
echo "$*" >>"$ATTRAPPE_BROWSER_LOG"
ENDE
chmod +x "$ATTRAPPEN/docker" "$ATTRAPPEN/claude" "$ATTRAPPEN/uvx" "$ATTRAPPEN/browser"

# Antwortet wie die Akte auf GET /api/v1/auth/einrichtung/ (Antwort = Inhalt der Datei einrichtung.json).
EINRICHTUNG="$ARBEIT/einrichtung.json"
setze_einrichtung() { printf '%s\n' "$1" >"$EINRICHTUNG"; }
setze_einrichtung '{"offen": true, "grund": "offen"}'
PORT="$(freier_port)"
cat >"$ARBEIT/server.py" <<'ENDE'
import http.server, sys
port, datei = int(sys.argv[1]), sys.argv[2]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/v1/auth/einrichtung/":
            body = open(datei).read().strip().encode()
            self.send_response(200)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
ENDE
"$PY" "$ARBEIT/server.py" "$PORT" "$EINRICHTUNG" &
server_pid=$!
for _ in $(seq 1 40); do
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then break; fi
  sleep 0.25
done

lauf() { # $1 Ordner, Rest: Argumente; Umgebung über UMGEBUNG
  local ordner="$1"
  shift
  env -u AKTE_PORT -u AKTE_DOCKER -u AKTE_DOCKER_WARTEN -u AKTE_MCP_QUELLE -u AKTE_OHNE_BROWSER -u ATTRAPPE_DATEN \
    AKTE_BROWSER="$ATTRAPPEN/browser" AKTE_STARTER_TEST=1 ATTRAPPE_BROWSER_LOG="$BROWSER_LOG" CLAUDE_CONFIG_DIR="$ARBEIT/claude" \
    ATTRAPPE_LOG="$PROTOKOLL" TMPDIR="$ARBEIT" "${UMGEBUNG[@]}" "$STARTER_BASH" "$ordner/start/akte.sh" "$@" 2>&1
}

warte_auf_browser() { # $1 erwartete Adresse; die Attrappe läuft im Hintergrund wie ein echter Browser
  for _ in $(seq 1 40); do
    if [ -f "$BROWSER_LOG" ] && grep -qF "$1" "$BROWSER_LOG"; then return 0; fi
    sleep 0.25
  done
  return 1
}

json_feld() { # $1 JSON, $2 Feld → Wert (Python-Darstellung)
  printf '%s' "$1" | "$PY" -c 'import json, sys; d = json.load(sys.stdin); print(json.dumps(d[sys.argv[1]]))' "$2"
}

json_felder() {
  printf '%s' "$1" | "$PY" -c 'import json, sys; print(",".join(json.load(sys.stdin)))' 2>/dev/null || true
}

VERTRAG="docker,akte,url,einrichtung_offen,einrichtung_grund,agent_verbunden"

# ─── Fälle ───────────────────────────────────────────────────────────────────────────────────────────────────
for d in akte.sh start-akte.command stop-akte.command; do
  pruefe "bash -n start/$d ($STARTER_BASH)" "$("$STARTER_BASH" -n "$REPO/start/$d" >/dev/null 2>&1; echo $?)"
done

# Die Agenten-Anleitung steht wörtlich gleich in README.md und AGENTS.md.
abschnitt() { sed -n '/<!-- agenten-anleitung:anfang/,/<!-- agenten-anleitung:ende -->/p' "$1" | tr -d '\r'; }
a_readme="$(abschnitt "$REPO/README.md")"
a_agents="$(abschnitt "$REPO/AGENTS.md")"
pruefe "Agenten-Anleitung: README.md und AGENTS.md gleich" \
  "$([ -n "$a_readme" ] && [ "$a_readme" = "$a_agents" ]; echo $?)" \
  "$(diff <(printf '%s\n' "$a_readme") <(printf '%s\n' "$a_agents") | head -20 || true)"
for d in start-akte.command stop-akte.command; do
  pruefe "start/$d ruft akte.sh auf" "$(grep -q 'akte.sh' "$REPO/start/$d"; echo $?)"
done
pruefe "akte.sh: AKTE_BROWSER wirkt nur mit AKTE_STARTER_TEST=1" \
  "$(grep -qF '[ -n "${AKTE_BROWSER:-}" ] && [ "${AKTE_STARTER_TEST:-}" = "1" ]' "$REPO/start/akte.sh"; echo $?)"
# Die Version steht einmal im Starter; die Prüfungen nehmen sie von dort (für Vorabversionen nur eine Stelle ändern).
VERSION="$(sed -n 's/^AKTE_VERSION="\(.*\)"$/\1/p' "$REPO/start/akte.sh")"
pruefe "akte.sh: Version als Konstante (AKTE_VERSION=$VERSION)" "$([[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; echo $?)"

# nicht entpackt
mkdir -p "$ARBEIT/nur-skript/start"
cp "$REPO/start/akte.sh" "$ARBEIT/nur-skript/start/"
UMGEBUNG=()
code=0
aus="$(lauf "$ARBEIT/nur-skript" start --still)" || code=$?
pruefe "nicht entpackt: Rückgabe 2" "$([ "$code" -eq 2 ] && enthaelt "$aus" "zuerst entpacken"; echo $?)" "$aus"

# Docker fehlt
ordner="$(kopie docker-fehlt)"
UMGEBUNG=(AKTE_DOCKER="$ARBEIT/gibt-es-nicht/docker")
code=0
aus="$(lauf "$ordner" start --still)" || code=$?
pruefe "Docker fehlt: Rückgabe 3 und Hinweis" "$([ "$code" -eq 3 ] && enthaelt "$aus" "Docker fehlt"; echo $?)" "$aus"
aus="$(lauf "$ordner" status --json)"
pruefe "status --json: genau die Felder aus dem Vertrag (ohne Einrichtungscode)" \
  "$([ "$(json_felder "$aus")" = "$VERTRAG" ]; echo $?)" "$aus"
pruefe "Docker fehlt: docker=fehlt, grund=null" \
  "$([ "$(json_feld "$aus" docker)" = '"fehlt"' ] && [ "$(json_feld "$aus" einrichtung_grund)" = null ]; echo $?)" "$aus"

# Docker aus
ordner="$(kopie docker-aus)"
UMGEBUNG=(AKTE_DOCKER="$ATTRAPPEN/docker" ATTRAPPE_DOCKER_AUS=1 AKTE_DOCKER_WARTEN=4)
code=0
aus="$(lauf "$ordner" start --still)" || code=$?
pruefe "Docker aus: Rückgabe 4" "$([ "$code" -eq 4 ] && enthaelt "$aus" "Docker startet nicht"; echo $?)" "$aus"

# Port belegt (die HTTP-Attrappe hält den Port, die Akte-Container laufen nicht)
ordner="$(kopie port-belegt)"
UMGEBUNG=(AKTE_DOCKER="$ATTRAPPEN/docker" AKTE_PORT="$PORT")
code=0
aus="$(lauf "$ordner" start --still)" || code=$?
pruefe "Port belegt: Rückgabe 5" "$([ "$code" -eq 5 ] && enthaelt "$aus" "belegt"; echo $?)" "$aus"

# ── läuft, erstes Konto fehlt: Code entsteht, geht nur an den Browser ──
ordner="$(kopie laeuft)"
UMGEBUNG=(AKTE_DOCKER="$ATTRAPPEN/docker" ATTRAPPE_AKTE_LAEUFT=1 AKTE_PORT="$PORT")
MIT_DATEN=(AKTE_DOCKER="$ATTRAPPEN/docker" ATTRAPPE_AKTE_LAEUFT=1 AKTE_PORT="$PORT" ATTRAPPE_DATEN=1)
rm -f "$BROWSER_LOG"
code=0
aus="$(lauf "$ordner" start --still)" || code=$?
pruefe "läuft: Rückgabe 0" "$([ "$code" -eq 0 ]; echo $?)" "$aus"
ecode="$(env_code "$ordner")"
pruefe "läuft: .env mit Schlüssel und Code (neue Akte ohne Daten)" \
  "$(grep -Eq '^DJANGO_SECRET_KEY=[A-Za-z0-9_-]{50,}$' "$ordner/.env" && [[ "$ecode" =~ ^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}$ ]]; echo $?)" "$(cat "$ordner/.env")"
anzeige="${ecode:0:4}-${ecode:4:4}"
pruefe "läuft: Ausgabe nennt den Einrichtungscode nicht" \
  "$(! enthaelt "$aus" "$anzeige" && ! enthaelt "$aus" "$ecode"; echo $?)" "$aus"
pruefe "läuft: „Der Browser ist offen“ und /akte/einrichten" \
  "$(enthaelt "$aus" "Der Browser ist offen: wähl dort Name und Passwort." && enthaelt "$aus" "localhost:$PORT/akte/einrichten"; echo $?)" "$aus"
pruefe "läuft: Browser bekommt den Code im Fragment (#code=)" \
  "$(warte_auf_browser "http://localhost:$PORT/akte/einrichten#code=$anzeige"; echo $?)" "$(cat "$BROWSER_LOG" 2>/dev/null || true)"
case "$(uname -s)" in
  Linux | Darwin)
    rechte="$(stat -c '%a' "$ordner/.env" 2>/dev/null || stat -f '%Lp' "$ordner/.env")"
    pruefe "läuft: .env nur für das eigene Konto (600)" "$([ "$rechte" = 600 ]; echo $?)" "$rechte"
    ;;
esac
aus="$(lauf "$ordner" status --json)"
pruefe "läuft: status --json (offen, grund=offen, kein Code)" \
  "$([ "$(json_felder "$aus")" = "$VERTRAG" ] && [ "$(json_feld "$aus" akte)" = '"laeuft"' ] && [ "$(json_feld "$aus" einrichtung_offen)" = true ] && [ "$(json_feld "$aus" einrichtung_grund)" = '"offen"' ] && ! enthaelt "$aus" "$anzeige"; echo $?)" "$aus"
aus="$(lauf "$ordner" status)"
pruefe "läuft: status (Text) nennt den Code nicht" "$(enthaelt "$aus" "fehlt noch" && ! enthaelt "$aus" "$anzeige"; echo $?)" "$aus"

# zweiter Start, Einrichtung noch offen: Code bleibt
vorher="$(cat "$ordner/.env")"
UMGEBUNG=("${MIT_DATEN[@]}")
code=0
aus="$(lauf "$ordner" start --still --ohne-browser)" || code=$?
pruefe "zweiter Start: Code bleibt; ohne Browser kommt der Notweg akte_einrichten, kein Code" \
  "$([ "$code" -eq 0 ] && [ "$(cat "$ordner/.env")" = "$vorher" ] && enthaelt "$aus" "manage.py akte_einrichten" && ! enthaelt "$aus" "$anzeige"; echo $?)" "$aus"

# Doppelklick-Weg (start-akte.command): öffnet den Browser wie start, zeigt keinen Code
rm -f "$BROWSER_LOG"
cp "$REPO/start/start-akte.command" "$ordner/start/"
code=0
aus="$(env AKTE_BROWSER="$ATTRAPPEN/browser" AKTE_STARTER_TEST=1 ATTRAPPE_BROWSER_LOG="$BROWSER_LOG" \
  CLAUDE_CONFIG_DIR="$ARBEIT/claude" ATTRAPPE_LOG="$PROTOKOLL" "${MIT_DATEN[@]}" "$STARTER_BASH" "$ordner/start/start-akte.command" 2>&1)" || code=$?
pruefe "start-akte.command: Rückgabe 0, kein Code in der Ausgabe, Browser mit #code=" \
  "$([ "$code" -eq 0 ] && ! enthaelt "$aus" "$anzeige" && warte_auf_browser "#code=$anzeige"; echo $?)" "$aus"

# agent, solange das erste Konto fehlt
UMGEBUNG=("${MIT_DATEN[@]}" PATH="$ATTRAPPEN:$PATH")
code=0
aus="$(lauf "$ordner" agent --still)" || code=$?
pruefe "agent ohne Konto: Rückgabe 9, kein Code" \
  "$([ "$code" -eq 9 ] && enthaelt "$aus" "akte/einrichten" && ! enthaelt "$aus" "$anzeige"; echo $?)" "$aus"

# Ältere Akte ohne „grund“ in der Antwort: wird abgeleitet
setze_einrichtung '{"offen": true}'
UMGEBUNG=("${MIT_DATEN[@]}")
aus="$(lauf "$ordner" status --json)"
pruefe "status --json ohne „grund“ vom Server: grund=offen abgeleitet" "$([ "$(json_feld "$aus" einrichtung_grund)" = '"offen"' ]; echo $?)" "$aus"

# ── Konto angelegt: agent verbindet, Code verschwindet ──
setze_einrichtung '{"offen": false, "grund": "eingerichtet"}'
: >"$PROTOKOLL"
UMGEBUNG=("${MIT_DATEN[@]}" PATH="$ATTRAPPEN:$PATH")
code=0
aus="$(lauf "$ordner" agent --still)" || code=$?
quelle="https://github.com/ThePyth0nKid/ultra-akte/archive/refs/tags/v$VERSION.zip#subdirectory=mcp"
pruefe "agent: Rückgabe 0 und Schlusssatz" \
  "$([ "$code" -eq 0 ] && enthaelt "$aus" "Fertig. Beende Claude (/exit) und starte es neu mit: claude --continue"; echo $?)" "$aus"
pruefe "agent: Token erscheint nie in der Ausgabe" "$(! enthaelt "$aus" "ATTRAPPExTOKENxATTRAPPExTOKENxATTRAPPExx"; echo $?)" "$aus"
pruefe "agent: claude mcp add wie im Vertrag" \
  "$(grep -qF "claude mcp add --scope user akte -e AKTE_BASIS=http://127.0.0.1:$PORT -e AKTE_TOKEN=ATTRAPPExTOKENxATTRAPPExTOKENxATTRAPPExx -- uvx --python 3.12 --from $quelle akte-mcp" "$PROTOKOLL"; echo $?)" "$(cat "$PROTOKOLL")"
pruefe "agent: vorwärmen mit dem Server selbst (Python 3.12)" \
  "$(grep -qF "uvx --python 3.12 --from $quelle akte-mcp --selbsttest" "$PROTOKOLL"; echo $?)" "$(cat "$PROTOKOLL")"
pruefe "agent: Konto-Suche über akte_konten" "$(grep -q 'manage.py akte_konten' "$PROTOKOLL"; echo $?)" "$(cat "$PROTOKOLL")"
pruefe "agent nach der Einrichtung: Code aus .env gelöscht" "$([ -z "$(env_code "$ordner")" ]; echo $?)" "$(cat "$ordner/.env")"
UMGEBUNG=("${MIT_DATEN[@]}")
code=0
aus="$(lauf "$ordner" start --still)" || code=$?
pruefe "Start nach der Einrichtung: kein neuer Code" "$([ "$code" -eq 0 ] && [ -z "$(env_code "$ordner")" ]; echo $?)" "$aus"

# start löscht den Code ebenso
ordner2="$(kopie eingerichtet)"
setze_einrichtung '{"offen": true, "grund": "offen"}'
UMGEBUNG=(AKTE_DOCKER="$ATTRAPPEN/docker" ATTRAPPE_AKTE_LAEUFT=1 AKTE_PORT="$PORT")
lauf "$ordner2" start --still >/dev/null || true
vorher="$(env_code "$ordner2")"
setze_einrichtung '{"offen": false, "grund": "eingerichtet"}'
UMGEBUNG=("${MIT_DATEN[@]}")
aus="$(lauf "$ordner2" start --still)" || true
pruefe "start nach der Einrichtung: Code aus .env gelöscht" \
  "$([ "${#vorher}" -eq 8 ] && [ -z "$(env_code "$ordner2")" ] && enthaelt "$aus" "aus .env gelöscht"; echo $?)" "$aus"

# neue Version einer eingerichteten Akte: alte .env ohne Code, Volume mit Daten → kein Code
ordner3="$(kopie neue-version)"
printf 'DJANGO_SECRET_KEY=%s\nAKTE_PORT=8080\n' "altaltaltaltaltaltaltaltaltaltaltaltaltaltaltaltaltalt" >"$ordner3/.env"
aus="$(lauf "$ordner3" start --still)" || true
pruefe "neue Version mit Daten: kein Einrichtungscode angelegt" "$([ "$(env_code "$ordner3")" = FEHLT ]; echo $?)" "$(cat "$ordner3/.env")"
setze_einrichtung '{"offen": false, "grund": "kein_code"}'
aus="$(lauf "$ordner3" start --still)" || true
pruefe "kein Code, kein Konto: Notweg akte_einrichten" "$(enthaelt "$aus" "manage.py akte_einrichten"; echo $?)" "$aus"
aus="$(lauf "$ordner3" status --json)"
pruefe "kein Code: status --json grund=kein_code" "$([ "$(json_feld "$aus" einrichtung_grund)" = '"kein_code"' ]; echo $?)" "$aus"

# agent_verbunden aus .claude.json, wie akte.ps1: Eintrag da und derselbe Port
setze_einrichtung '{"offen": false, "grund": "eingerichtet"}'
UMGEBUNG=("${MIT_DATEN[@]}")
claude_eintrag() { # $1 Port in AKTE_BASIS
  printf '%s\n' '{"projects": {"/x": {}},' \
    ' "mcpServers": {"akte": {"type": "stdio", "command": "uvx", "args": ["akte-mcp"],' \
    "  \"env\": {\"AKTE_BASIS\": \"http://127.0.0.1:$1\", \"AKTE_TOKEN\": \"x\"}}}}" >"$ARBEIT/claude/.claude.json"
}
claude_eintrag "$PORT"
aus="$(lauf "$ordner" status --json)"
pruefe "status --json: agent_verbunden erkennt den Eintrag" "$([ "$(json_feld "$aus" agent_verbunden)" = true ]; echo $?)" "$aus"
claude_eintrag 9
aus="$(lauf "$ordner" status --json)"
pruefe "status --json: Eintrag mit altem Port zählt nicht (wie akte.ps1)" \
  "$([ "$(json_feld "$aus" agent_verbunden)" = false ]; echo $?)" "$aus"
rm -f "$ARBEIT/claude/.claude.json"

# --json: immer JSON, auch bei Fehlern
code=0
aus="$(lauf "$ordner" start --json)" || code=$?
pruefe "--json bei start: JSON-Fehlerobjekt, Rückgabe 1" \
  "$([ "$code" -eq 1 ] && [ "$(json_felder "$aus")" = "fehler" ]; echo $?)" "$aus"

# demo und stop
setze_einrichtung '{"offen": false, "grund": "eingerichtet"}'
UMGEBUNG=(AKTE_DOCKER="$ATTRAPPEN/docker" ATTRAPPE_AKTE_LAEUFT=1 AKTE_PORT="$PORT")
code=0
aus="$(lauf "$ordner" demo --still)" || code=$?
pruefe "demo: Rückgabe 0" "$([ "$code" -eq 0 ] && enthaelt "$aus" "/akte/demo-musterhafen"; echo $?)" "$aus"
code=0
aus="$(lauf "$ordner" stop --still)" || code=$?
pruefe "stop: Rückgabe 0" "$([ "$code" -eq 0 ]; echo $?)" "$aus"

echo
if [ "$fehler" -gt 0 ]; then
  echo "$fehler von $geprueft Prüfungen fehlgeschlagen."
  exit 1
fi
echo "Alle $geprueft Prüfungen bestanden."
