# Die Akte 0.2.0 – was neu ist

Entwurf der Release-Notizen. Version 0.2.0 macht die Akte für Menschen ohne Vorkenntnisse benutzbar: Ein KI-Agent
wie Claude Code richtet sie auf einem frischen Windows ein, der Mensch legt sein Konto im Browser an und
unterschreibt. Der Agent schreibt nur Entwürfe.

## Einrichten

* **Starter für Windows, macOS und Linux** (`start/akte.ps1`, `start/akte.sh`) mit den Befehlen `start`, `stop`,
  `status`, `agent`, `demo`. Doppelklick auf `START-AKTE`, `STOP-AKTE`, `AGENT-VERBINDEN` (Windows) bzw.
  `start-akte.command` (Mac). Der Starter startet Docker Desktop selbst, sucht einen freien Port, wartet, bis die
  Akte antwortet, und meldet Fehler mit festen Rückgabewerten und deutschen Sätzen.
* **Anleitung für Agenten** im README und in `AGENTS.md` (wörtlich gleich, die CI prüft das), ausführlich in
  `docs/einrichten-fuer-agenten.md`. Für Menschen: `docs/erste-schritte.md` und `docs/woerter.md`.
* **Erstes Konto im Browser** unter `/akte/einrichten` statt Passwortfrage im Terminal. Der Einrichtungscode geht
  in keine Konsole: Der Starter öffnet den Browser mit dem Code im Fragment der Adresse (`#code=…`), die Seite trägt
  ihn ein und löscht ihn aus der Adresszeile; der Doppelklick auf `START-AKTE` tut dasselbe. Ohne Browser bleibt der
  Notweg `akte_einrichten`, der keinen Code braucht. Nach der Einrichtung löscht der Starter den Code aus `.env`; eine
  Akte mit Daten bekommt keinen neuen.
* **`status -Json`** für Agenten: `docker`, `akte`, `url`, `einrichtung_offen`, `einrichtung_grund`,
  `agent_verbunden`. Bei Fehlern `{"fehler": "…"}`.
* **Claude verbinden mit einem Befehl** (`agent`): uv in fester Version mit geprüfter Prüfsumme, Benutzer-Pfad,
  Token ohne Anzeige, `claude mcp add --scope user … --python 3.12 …` aus der Release-ZIP, vorgewärmt.
* `.env` ist nur für das eigene Benutzerkonto lesbar (Windows: Zugriffsliste nur mit diesem Konto, sonst
  `chmod 600`).
* `compose.yaml` mit Healthchecks, damit `docker compose up --wait` erst zurückkehrt, wenn die Akte antwortet.

## Arbeiten an der Wand

* **Live-Aktualisierung:** Was ein Agent anlegt, erscheint nach wenigen Sekunden auf der offenen Wand, ohne dass
  Kamera, Auswahl oder offene Formulare verloren gehen.
* **Zitat prüfen ohne Warteschleife:** `zitat_pruefen` antwortet nach höchstens 30 Sekunden mit `gefunden`,
  `nicht_gefunden` oder `nicht_pruefbar`. `gefunden` heißt nur: Der Wortlaut steht in der Quelle; ob er die Behauptung
  trägt, entscheidet ein Mensch. Silbentrennung im PDF („EU-⏎Verordnung“) wird richtig behandelt.
* **Beweissicherung im Hintergrund:** Quellen anlegen und sichern kehrt sofort zurück. Ohne Redis läuft Gunicorn
  dafür mit einem Worker und 8 Threads; nach einem Neustart holt die Akte Liegengebliebenes nach.
* **Unterschreiben verständlich:** eigener Dialog in Klartext statt Browser-Rückfrage, Siegel an unterschriebenen
  Karten und Fäden, Zähler „X unterschrieben · Y Entwürfe“.
* **Import mit Zeitraum:** Verbindungen in `import_paket` nehmen `start`, `bis` und `aktuell`.

## Sicherheit und Datenschutz

* **archive.org ist standardmäßig aus.** Einschalten kann es nur ein Mensch: beim ersten Konto oder unter „Regeln“ →
  „Für die ganze Akte“. Ist es aus, zählt für die Regel `quelle_ohne_archiv` die eigene gesicherte Kopie.
* **Host-Filter im Eingang:** Die Akte antwortet nur unter den Namen in `AKTE_HOSTS` (Standard
  `localhost 127.0.0.1 ::1 [::1]`), sonst 421. Schutz gegen DNS-Rebinding.
* Einrichtung zeitkonstant verglichen und gedrosselt, mit Deckel über alle Absender.
* Der MCP-Baustein warnt, wenn ein Token über `http://` an einen fremden Rechner ginge, und kennzeichnet Auszüge aus
  Quellen als fremden Text.
* Neu in `docs/sicherheit.md`: was ein Agent mit Dateizugriff trotzdem lesen kann, und woher jedes Teil kommt
  (Lieferkette).
* **Abruf fremder Links:** Verbunden wird genau mit der geprüften IP (IPv4 zuerst), mit harter Gesamtfrist (in
  Docker; ohne Docker unter Windows endet ein hängendes Lesen erst an der Lesezeitgrenze); eine Seite, die bei
  Fristablauf erst halb da ist, gilt nie als Original. Adressen mit Umlauten (`müller.de`) gehen. Ein vorübergehender
  DNS-Fehler sperrt eine Quelle nicht mehr dauerhaft für archive.org. Fehlermeldungen nennen fremde Rechnernamen nur,
  wenn sie aus Namenszeichen bestehen (sie gehen bis zum Agenten).

## Alle Plattformen

* Die Starter prüft die CI jetzt unter Windows (PowerShell 5.1), Linux und **macOS**, dort mit `/bin/bash` 3.2 wie
  beim Doppelklick auf `start-akte.command`. `status --json` meldet unter macOS und Linux `agent_verbunden` genauso
  wie unter Windows (Eintrag mit dem jetzigen Port).

## Wer von 0.1 kommt

Schritte und Hinweise: [betrieb.md, „Neue Version 0.2.0“](betrieb.md#neue-version-020-von-01). Das Wichtigste:

1. **archive.org:** In 0.1 war es ohne Eintrag in `.env` an, jetzt ist es aus. Wer es weiter will, schaltet es unter
   „Regeln“ ein.
2. **Eigene Domain, IP-Adresse oder Rechnername:** vor dem Start in `.env` in `AKTE_HOSTS` und
   `DJANGO_ALLOWED_HOSTS` eintragen (beim Anmelden unter diesem Namen auch `DJANGO_CSRF_TRUSTED_ORIGINS`), sonst
   antwortet die Akte mit 421 bzw. 400.
3. **Wand mit dem Kurznamen `einrichten`:** ist unter dieser Adresse nicht mehr erreichbar; die Akte meldet das beim
   Start im Protokoll und nennt den Weg zu einem neuen Kurznamen.
4. **`.env` aus dem alten Ordner übernehmen**, dann `START-AKTE` und `AGENT-VERBINDEN`, danach Claude neu starten.

## Release-Ablauf (Checkliste)

Für die Vorabversion `v0.2.0-rc.1` und für `v0.2.0` gleich:

1. Alle Prüfungen grün auf dem Commit, der veröffentlicht wird (CI: Backend, Web, MCP und Beweis, Starter Windows und
   Linux, Host-Filter gegen den gestarteten Stack, Leckschutz).
2. **Tag-Stellen prüfen.** Der Tag steht in den Startern genau einmal (`$AkteVersion` in `start/akte.ps1`,
   `AKTE_VERSION` in `start/akte.sh`) und in der Doku nur in Adressen, immer als `/v0.2.0` (mit Schrägstrich davor).
   Für die Vorabversion: in beiden Startern `0.2.0` → `0.2.0-rc.1`, in den Markdown-Dateien (außer dieser hier)
   `/v0.2.0` → `/v0.2.0-rc.1`, in `mcp/pyproject.toml` und `mcp/README.md` ebenso. Danach darf
   `git grep -n -e "/v0\.2\.0" -- ":!docs/aenderungen-0.2.0.md" | grep -v "/v0\.2\.0-rc"` nichts mehr finden. Die
   Prüfskripte lesen die Version aus den Startern und brauchen keine Änderung.
3. **Agentenblock gleich:** `bash .github/scripts/starter-pruefen.sh` (prüft README.md gegen AGENTS.md) oder die CI.
4. **Commit, dann Tag auf genau diesen Commit** (`git tag -a v0.2.0-rc.1 COMMIT`, danach `git push origin v0.2.0-rc.1`),
   Release bzw. Vorabversion auf GitHub anlegen.
5. **Archive prüfen:** „Source code (zip)“ und „(tar.gz)“ laden, enthalten sie `start/akte.ps1` mit BOM, die
   `.cmd`-Dateien mit CRLF, `start/akte.sh` ausführbar? Dann die Prüfsummen bilden und unten sowie in den
   Release-Notizen auf GitHub eintragen, dazu den Commit-Hash.
6. **Probelauf** mit dem Agenten-Weg aus dem README auf einem frischen Windows (Durchlauf 3), erst danach `v0.2.0`.

## Prüfsumme der Release-ZIP

Beim Veröffentlichen eintragen:

| Datei | SHA-256 | Commit |
|---|---|---|
| `die-akte-0.2.0.zip` (Source code, zip) | NOCH-EINTRAGEN | NOCH-EINTRAGEN |
| `die-akte-0.2.0.tar.gz` (Source code, tar.gz) | NOCH-EINTRAGEN | NOCH-EINTRAGEN |

Prüfen unter Windows: `Get-FileHash "$env:TEMP\die-akte-0.2.0.zip"`; macOS und Linux: `shasum -a 256 DATEI`.
