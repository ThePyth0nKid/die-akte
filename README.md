# Die Akte

**Eine Ermittler-Wand mit Belegpflicht und Beweiskette – gebaut für Recherche mit KI-Agenten.**

Agenten recherchieren schnell. Die Akte sorgt dafür, dass daraus nur dann eine Aussage wird, wenn sie belegt ist und
ein Mensch sie unterschrieben hat. *Agenten recherchieren, Regeln beraten, der Mensch entscheidet und unterschreibt.*

[English version](README.en.md)

---

## Was die Akte ist

Eine gewöhnliche Datenbank mit drei Schichten darüber:

1. **Regeln im Datenmodell.** Ein Faden zwischen zwei Karten (Personen, Firmen, Behörden, Gesetze …) ist kein
   Strich, sondern eine Aussage: Art der Verbindung, Zeitraum, Aussageart (*belegt*, *Verdacht*, *Meinung*) und
   Belege – jeweils Quelle, **wörtliches Zitat** und Fundstelle. Eine Prüfung meldet, was fehlt: Beleg, Abrufdatum,
   Archivkopie, Anhörung bei Verdacht, Schutz von Privatpersonen. Jede Regel ist einzeln auf *aus*, *Hinweis* oder
   *Sperre* stellbar.
2. **Beweisschicht.** Jede Quelle wird gesichert: Original mit SHA-256, Archivkopie, Seitenbild und die
   **Fundstelle**, also der Ausschnitt mit dem markierten Zitat. Jede Sicherung und jede Freigabe wird ein signiertes
   Glied einer Hash-Kette im Format [`atlas-trace-v1`](https://github.com/ThePyth0nKid/atlas). Prüfen kann jeder,
   ohne dem Server zu vertrauen – mit `akte pruefe-signaturen` oder dem unabhängigen Prüfer von Atlas.
3. **Ausgabeschicht.** Aus derselben Wand entstehen Kamerafahrten bis zum fertigen Video: deterministisch Bild für
   Bild, in 16:9, 9:16, 1:1, auf Wunsch mit Stimme, Musik und markierten Beweisstücken.

Darüber steht ein **Verfahren**: Recherche-Agenten → unabhängiger Faktenprüfer *vor* dem Import → Import als Entwurf
→ Beweissicherung → Prüfung → **Freigabe durch einen Menschen mit seiner Unterschrift**. Agenten (Werkzeug-Token,
MCP) können nichts freigeben, nichts löschen und nichts öffentlich schalten.

Verwandte Werkzeuge mit anderem Schwerpunkt: [Aleph](https://github.com/alephdata/aleph) (Dokumente und Entitäten
durchsuchen), [Maltego](https://www.maltego.com/) (OSINT-Verknüpfungen), [Kumu](https://kumu.io/) (Netzwerkkarten),
[Hunchly](https://hunch.ly/) (Web-Sicherung). Die Akte verbindet Belegpflicht am einzelnen Faden, signierte
Freigaben und Video-Ausgabe in einem lokalen Programm.

## Auf deinem Rechner installieren

Die Akte läuft **nur auf deinem Rechner** – kein Konto bei uns, kein Server, keine Kosten.

1. **Docker Desktop** installieren: <https://www.docker.com/products/docker-desktop/> und starten.
2. Dieses Repo herunterladen (grüner Knopf „Code“ → „Download ZIP“, entpacken) oder `git clone`.
3. Starten:
   * **Windows:** Doppelklick auf `start\START-AKTE.cmd`
   * **macOS:** Doppelklick auf `start/start-akte.command` (beim ersten Mal: Rechtsklick → Öffnen)
   * **Linux / Terminal:** `./start/start-akte.command`

   Beim ersten Start wird alles gebaut (einige Minuten), eine `.env` mit einem geheimen Schlüssel angelegt und
   dein erstes Konto für die Redaktion eingerichtet. Danach öffnet sich <http://localhost:8080/akte>.
4. **Demo laden** (empfohlen): `docker compose exec api python manage.py akte_demo` – eine erfundene Akte
   „Freie Stadt Musterhafen“ mit Quellen, Fundstellen, einer Fahrt und signierten Freigaben.

Stoppen: `start\STOP-AKTE.cmd` bzw. `docker compose stop`. Deine Daten bleiben im Docker-Volume `akte-daten`.

<details>
<summary>Ohne Docker (für Entwickler)</summary>

```sh
# Backend
cd backend && python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt ../beweis
DJANGO_DEBUG=1 python manage.py migrate && python manage.py createcachetable
DJANGO_DEBUG=1 python manage.py akte_einrichten && DJANGO_DEBUG=1 python manage.py runserver 8000
# Web (zweites Terminal)
cd web && npm ci && AKTE_OHNE_PROXY=1 npm run dev     # http://localhost:3000/akte
```
</details>

## Mit Claude Code arbeiten (MCP)

```sh
docker compose exec api python manage.py akte_token <dein-konto>      # Token einmal anzeigen lassen
claude mcp add akte -e AKTE_BASIS=http://localhost:8080 -e AKTE_TOKEN=<token> \
  -- uvx --from "git+https://github.com/ThePyth0nKid/die-akte#subdirectory=mcp" akte-mcp
```

Dann zum Beispiel: *„Lies die Wand demo-musterhafen und sag mir, welche Fäden noch offene Befunde haben.“* Ohne
`AKTE_TOKEN` liest der Server nur. Alles, was ein Agent anlegt, ist ein Entwurf. Einzelheiten: [docs/mcp.md](docs/mcp.md).

## Beweiskette prüfen – ohne dem Server zu vertrauen

```sh
uv tool install "akte-mcp[beweis] @ git+https://github.com/ThePyth0nKid/die-akte#subdirectory=mcp"
akte pruefe-signaturen --basis http://localhost:8080 --speichern ./pruefung     # oder --datei export.json
```

Geprüft werden Hashes, Ed25519-Signaturen, die lückenlose Reihenfolge, Rollen (Freigaben nur durch Menschen),
Widerrufe und die offengelegten Inhalte. Mit `--atlas` zusätzlich durch den WASM-Prüfer von Atlas. Was eine gültige
Kette beweist und was nicht: [docs/sicherheit.md](docs/sicherheit.md).

## Freigeben heißt unterschreiben

Wählst du in der Oberfläche „Freigeben (unterschreiben)“, erzeugt dein Browser beim ersten Mal ein Ed25519-Schlüsselpaar.
Der private Schlüssel ist nicht exportierbar und verlässt den Browser nie; der Server kennt nur den öffentlichen.
Sperrende Befunde kannst du mit einer Begründung überstimmen – die Begründung wird mitsigniert und mit dem Objekt
veröffentlicht. Änderst du etwas Freigegebenes, wird es wieder Entwurf und braucht eine neue Unterschrift. Wie streng
die Prüfung eines Boards ist, stellst du unter **„Regeln“** ein; dort widerrufst du auch einen Schlüssel, etwa nach
dem Verlust eines Geräts. Leser sehen nur, was ein Mensch unterschrieben hat. Regeln und Stufen:
[docs/belegregeln.md](docs/belegregeln.md).

## Videos aus der Wand

```sh
cd render && npm ci && npx playwright install chromium
python render/aufnahme.py rendern demo-musterhafen "Wer wertet Musterhafens Daten aus?" --format 16x9,9x16
```

Mit Stimme und Musik (ElevenLabs, eigener Schlüssel): [docs/aufnahme.md](docs/aufnahme.md).

## Grenzen

* Die Akte ersetzt **keine anwaltliche Prüfung**. Die Regeln zu Verdacht und Privatpersonen orientieren sich am
  deutschen Presserecht, sind aber Werkzeuge, kein Urteil.
* Eine gültige Signatur beweist, *wer* *wann* *was* unterschrieben hat – nicht, dass es wahr ist.
* Selbst betreiben im Netz: [docs/betrieb.md](docs/betrieb.md) (Proxy, HTTPS, Backups, Browser-Worker).

## Aufbau

| Ordner | Inhalt | Lizenz |
|---|---|---|
| `backend/` | Django-API, Prüfung, Beweissicherung, Beweisschicht | AGPL-3.0 |
| `web/` | Wand (Next.js, React Flow), Unterschrift im Browser | AGPL-3.0 |
| `render/` | Kamerafahrten zu Video, Stimme, Mischung | AGPL-3.0 |
| `mcp/` | `akte-mcp`, Python-Client, CLI `akte` | MIT |
| `beweis/` | `akte-beweis`: Atlas-Format, Prüfung, Richtlinie | MIT |
| `skills/` | Skill für Claude Code: an der Akte arbeiten | MIT |
| `docs/` | Anleitungen | CC BY 4.0 |

## Mitmachen

Fehler und Ideen gern als Issue. Sicherheitslücken bitte vertraulich melden: [SECURITY.md](SECURITY.md).
Beiträge: [CONTRIBUTING.md](CONTRIBUTING.md).

Lizenz: AGPL-3.0-or-later für das Programm; Teile unter MIT und CC BY 4.0 wie oben (siehe `REUSE.toml`).
Wer die Akte im Netz für andere betreibt, muss ihnen den Quelltext anbieten (AGPL § 13) – der Link steht schon unten
auf der Board-Übersicht.
