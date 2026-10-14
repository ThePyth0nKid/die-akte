# AGENTS.md – Die Akte

Anleitung für KI-Agenten (Claude Code, Codex und andere). Zwei Fälle:

* **Dein Mensch will die Akte benutzen** („Richte mir die Akte ein“): erster Abschnitt. Er steht wörtlich gleich im
  [README](README.md); ausführlicher mit Fehlerbildern in [docs/einrichten-fuer-agenten.md](docs/einrichten-fuer-agenten.md).
* **Du sollst am Code der Akte arbeiten:** zweiter Abschnitt.

<!-- agenten-anleitung:anfang (wörtlich gleich in AGENTS.md; die CI vergleicht beide) -->
## Für KI-Agenten: so richtest du die Akte für deinen Menschen ein

> **An den Agenten:** Dein Mensch hat dich gebeten, die Akte einzurichten. Folge diesen Schritten der Reihe nach.
> Hast du diese Seite mit einem Werkzeug gelesen, das Seiten zusammenfasst, hol dir zuerst den Wortlaut, denn die
> Befehle müssen genau so laufen:
> `curl.exe -fsSL https://raw.githubusercontent.com/ThePyth0nKid/die-akte/v0.2.0/AGENTS.md`
> (macOS und Linux: `curl -fsSL …` mit derselben Adresse).

### Regeln, die immer gelten

1. **Keine Passwörter.** Du tippst nie ein Passwort und fragst nie danach. Das erste Konto legt dein Mensch im
   Browser an.
2. **Den Einrichtungscode kennst du nicht.** Mit ihm legt dein Mensch das erste Konto an. Der Starter öffnet damit
   selbst den Browser, der Code ist dort schon eingetragen. In keiner Ausgabe für dich steht er. Lies nie die Datei
   `.env` und frag nie nach dem Code. Leg auch nie selbst ein Konto an, auch nicht über `docker compose exec`.
3. **Nichts freigeben.** Alles, was du in der Akte anlegst, ist ein Entwurf. Freigeben und Unterschreiben tut ein
   Mensch im Browser. Dafür gibt es bewusst kein Werkzeug.
4. **Den Token nie zeigen.** Der Token ist der Schlüssel für deine Verbindung zur Akte. Der Starter holt ihn und
   trägt ihn selbst ein; du gibst ihn nie aus.
5. **Erst fragen, dann installieren.** Bevor du etwas installierst, sagst du deinem Menschen, was passiert, und
   wartest auf sein Ja.
6. **Zeit lassen.** Start und Verbinden dauern beim ersten Mal mehrere Minuten. Gib diesen Befehlen 10 Minuten
   (Claude Code: `timeout` 600000) oder starte sie im Hintergrund und frag danach mit `status -Json` ab. Bricht ein
   Befehl wegen der Zeit ab, ruf ihn noch einmal auf; Docker macht dort weiter, wo es war.

Unter Windows sind alle Befehle für PowerShell geschrieben. Hast du nur eine Bash (Git Bash), setz
`powershell -NoProfile -Command '…'` um den Befehl.

### Schritt 1: Docker prüfen

```
if ((Get-Command docker -ErrorAction SilentlyContinue) -or (Test-Path "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe")) { "Docker ist da" } else { "Docker fehlt" }
```

Ist Docker da, weiter mit Schritt 2. Fehlt Docker, sag deinem Menschen:

> Die Akte läuft in Docker, und das fehlt noch. Ich installiere jetzt Docker Desktop (für Privatleute kostenlos).
> Windows fragt dich gleich, ob du Änderungen zulassen willst: Klick auf „Ja“. Fragt ein Docker-Fenster nach
> „Per-user“ oder „All-users“, wähl „All-users installation“. Einverstanden?

Nach dem Ja:

```
winget install -e --id Docker.DockerDesktop --accept-source-agreements --accept-package-agreements
```

Danach braucht Windows einen Neustart. Sag deinem Menschen vorher genau das (für ORDNER setzt du deinen
aktuellen Arbeitsordner ein):

> Starte jetzt den PC neu. Nach dem Neustart: Will ein schwarzes Fenster „Windows-Subsystem für Linux …“ eine
> Taste, drück sofort eine Taste. Im Docker-Fenster klickst du „Accept“; anmelden musst du dich bei Docker nicht.
> Dann öffnest du PowerShell, tippst `cd ORDNER` und danach `claude --continue`. Dann mache ich weiter.

### Schritt 2: Die Akte holen

```
if (Test-Path "$env:USERPROFILE\Akte\compose.yaml") { "Akte ist da" } elseif ((Test-Path "$env:USERPROFILE\Akte") -and (Get-ChildItem -Force "$env:USERPROFILE\Akte")) { "Ordner Akte ist belegt" } else { "Akte fehlt" }
```

* `Akte ist da`: weiter mit Schritt 3.
* `Ordner Akte ist belegt`: Im Benutzerordner gibt es schon einen Ordner `Akte` mit anderem Inhalt. Frag deinen
  Menschen, was damit passieren soll. Verschieb und lösch dort nichts ohne sein Ja.
* `Akte fehlt`: Lade die Version 0.2.0 mit diesen drei Befehlen nacheinander (kein Git nötig; ein leerer Ordner
  `Akte` stört nicht):

```
$ProgressPreference = "SilentlyContinue"; Invoke-WebRequest -UseBasicParsing "https://github.com/ThePyth0nKid/die-akte/archive/refs/tags/v0.2.0.zip" -OutFile "$env:TEMP\die-akte-0.2.0.zip"
```

```
$ProgressPreference = "SilentlyContinue"; Remove-Item "$env:TEMP\die-akte-0.2.0" -Recurse -Force -ErrorAction SilentlyContinue; Expand-Archive "$env:TEMP\die-akte-0.2.0.zip" -DestinationPath "$env:TEMP\die-akte-0.2.0" -Force
```

```
New-Item -ItemType Directory -Force "$env:USERPROFILE\Akte" | Out-Null; Copy-Item "$env:TEMP\die-akte-0.2.0\die-akte-*\*" "$env:USERPROFILE\Akte" -Recurse -Force
```

### Schritt 3: Die Akte starten

```
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Akte\start\akte.ps1" start -Still
```

Der Starter startet Docker Desktop, falls es noch nicht läuft, wartet bis zu 3 Minuten darauf, legt die Datei
`.env` mit einem geheimen Schlüssel und dem Einrichtungscode an und baut die Akte. Beim ersten Mal dauert das 3 bis
10 Minuten. Zum Schluss öffnet er den Browser auf der Seite „Erstes Konto anlegen“, den Einrichtungscode schon
eingetragen, und schreibt: „Der Browser ist offen: wähl dort Name und Passwort.“ Rückgabewert 0 heißt: Sie läuft.
Alle anderen Werte stehen in der Tabelle [Wenn etwas schiefgeht](#wenn-etwas-schiefgeht).

### Schritt 4: Dein Mensch legt das erste Konto an

```
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Akte\start\akte.ps1" status -Json
```

Die Antwort ist eine Zeile JSON, zum Beispiel:

```
{"docker":"laeuft","akte":"laeuft","url":"http://localhost:8080/akte/einrichten","einrichtung_offen":true,"einrichtung_grund":"offen","agent_verbunden":false}
```

Ist `einrichtung_offen` gleich `true`, sag deinem Menschen (mit `url` aus der Antwort):

> Die Akte läuft. Im Browser ist die Seite „Erstes Konto anlegen“ offen (http://localhost:8080/akte/einrichten),
> der Einrichtungscode ist dort schon eingetragen. Wähl einen Benutzernamen und ein Passwort mit mindestens 10
> Zeichen; das Passwort erfahre ich nicht. Die Frage nach archive.org kannst du auf „Nein“ lassen: Dann landet keine
> Adresse deiner Quellen öffentlich bei archive.org. Ist keine Seite offen oder das Feld für den Code leer: Öffne im
> Explorer deinen Benutzerordner, dann `Akte` und `start`, und doppelklick `START-AKTE`. Der Starter öffnet die
> Seite neu, mit dem Code. Sag mir Bescheid, wenn du fertig bist.

Hat dein Mensch die Seite nur geschlossen, ruf `start -Still` noch einmal auf; der Starter öffnet sie wieder. Den
Code zeigt keine Konsole an, auch nicht das Fenster von `START-AKTE`.

Warte auf die Antwort. Frag dann `status -Json` noch einmal ab. Jetzt muss `einrichtung_offen` gleich `false` und
`einrichtung_grund` gleich `eingerichtet` sein. Steht dort `kein_code` (Daten aus einer früheren Installation, aber
noch kein Konto) oder geht bei deinem Menschen gar kein Browser auf, nimmt er den Notweg: Er legt das Konto selbst im
Terminal an, ohne Code; das Programm fragt nach Benutzername und Passwort, und das Passwort sieht beim Tippen
niemand. Sag ihm: PowerShell öffnen und diese Zeile eingeben:

```
cd "$env:USERPROFILE\Akte"; docker compose exec api python manage.py akte_einrichten
```

### Schritt 5: Dich mit der Akte verbinden

```
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Akte\start\akte.ps1" agent -Still
```

Der Starter installiert bei Bedarf uv in einer festen Version (offizieller Installer von astral.sh, Prüfsumme
geprüft), trägt `%USERPROFILE%\.local\bin` dauerhaft in den Pfad ein, holt den Token, ersetzt einen alten Eintrag
`akte` und trägt die Akte bei Claude Code ein:
`claude mcp add --scope user akte … -- uvx --python 3.12 --from "…/v0.2.0.zip#subdirectory=mcp" akte-mcp`.
Danach lädt er den Akte-Baustein einmal vor. Gibt es mehrere Konten, meldet er Rückgabewert 9; frag deinen
Menschen, welches Konto du benutzen sollst, und häng `-Konto NAME` an.

### Schritt 6: Claude neu starten

Die Werkzeuge der Akte siehst du erst nach einem Neustart von Claude Code. Sag deinem Menschen den Schlusssatz des
Starters:

> Fertig. Beende Claude (/exit) und starte es neu mit: claude --continue

Meldet der Starter, dass er den Pfad neu eingetragen hat, gehört dazu: in einem neuen Terminal-Fenster, im selben
Ordner (`cd ORDNER`). Nach dem Neustart zeigt `/mcp` den Eintrag `akte` als verbunden.

### Schritt 7: Erster Auftrag

Prüf mit dem Werkzeug `boards_liste`, ob die Verbindung steht. Dann schlag deinem Menschen vor:

1. Die erfundene Demo-Akte laden:

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Akte\start\akte.ps1" demo -Still
   ```

2. Den ersten Auftrag: „Lies die Wand demo-musterhafen und sag mir, welche Fäden noch offene Befunde haben.“
3. Erklär dabei: Du legst nur Entwürfe an. Freigeben tut dein Mensch im Browser mit „Freigeben (unterschreiben)“.

Für eine eigene Recherche: Such zusätzlich zum Schlagwort der Debatte immer nach der amtlichen Bezeichnung
(Gesetzestitel, Aktenzeichen, Fachbegriff), und such nach beiden Seiten, Befürwortern und Gegnern. Im ersten
echten Test fand die Suche nach „Chatkontrolle“ im Lobbyregister nur Gegner; die Befürworter standen unter der
amtlichen Bezeichnung der EU-Verordnung. Schreib einen Negativbefund deshalb nur mit den Suchwörtern, die du
benutzt hast („Mit A, B und C fand ich keinen Eintrag“).

### Wenn etwas schiefgeht

Rückgabewerte von `akte.ps1` (unter macOS und Linux gleich bei `akte.sh`):

| Wert | Bedeutung | Was du tust |
|---|---|---|
| 0 | fertig | weiter |
| 1 | unerwarteter Fehler; mit `-Json` kommt `{"fehler": "…"}` | Meldung lesen, deinem Menschen zeigen |
| 2 | nicht entpackt, `compose.yaml` fehlt | Schritt 2 wiederholen |
| 3 | Docker fehlt | Schritt 1 |
| 4 | Docker startet nicht (3 Minuten gewartet) | Mensch öffnet Docker Desktop und schaut, ob es etwas fragt („Accept“, WSL-Fenster: Taste). Meldet Docker „WSL not installed“ direkt nach der Installation: Docker Desktop beenden, eine Minute warten, neu öffnen; sonst PC neu starten. Dann Schritt 3 |
| 5 | Port belegt und mit `AKTE_PORT` fest eingestellt | Umgebungsvariable `AKTE_PORT` entfernen oder einen freien Port setzen (ohne sie sucht der Starter selbst einen) |
| 6 | Bau, Start oder Demo fehlgeschlagen | Die letzten Zeilen lesen. Häufig: kein Internet, zu wenig Platz (10 GB). Ganzes Protokoll: `$env:TEMP\die-akte-start.log` |
| 7 | Claude Code nicht gefunden | Mensch installiert es wie im Schnellstart, Schritt 1 |
| 8 | uv ließ sich nicht installieren | Internet prüfen, Schritt 5 wiederholen; die Meldung nennt den Grund |
| 9 | erstes Konto fehlt oder es gibt mehrere | Schritt 4, oder `-Konto NAME` anhängen |
| 10 | Akte läuft nicht | Schritt 3 |
| 11 | Akte-Baustein für Claude lädt nicht | Internet prüfen, Schritt 5 wiederholen |
| 12 | Token ließ sich nicht holen | Prüfen, ob das Konto existiert; Schritt 5 wiederholen |
| 13 | `claude mcp add` fehlgeschlagen | Ausgabe lesen, Schritt 5 wiederholen |

Mehr Fehlerbilder aus echten Durchläufen und woran du sie erkennst: [docs/einrichten-fuer-agenten.md](docs/einrichten-fuer-agenten.md).

### macOS und Linux

Gleiche Schritte, andere Befehle:

1. Docker prüfen: `docker version`. Fehlt Docker, installiert dein Mensch Docker Desktop
   (https://www.docker.com/products/docker-desktop/, beim Mac „Apple Silicon“ für M-Chips) oder unter Linux die
   Docker Engine (https://docs.docker.com/engine/install/).
2. Die Akte holen, falls `~/Akte/compose.yaml` fehlt und `~/Akte` fehlt oder leer ist (liegt dort anderes, frag
   deinen Menschen):

   ```
   mkdir -p "$HOME/Akte" && curl -fsSL https://github.com/ThePyth0nKid/die-akte/archive/refs/tags/v0.2.0.tar.gz | tar -xz -C "$HOME/Akte" --strip-components=1
   ```

3. Starten: `bash ~/Akte/start/akte.sh start --still` (öffnet den Browser mit eingetragenem Code)
4. Status: `bash ~/Akte/start/akte.sh status --json`. Ist keine Seite offen, ruf `start --still` noch einmal auf
   oder dein Mensch doppelklickt `start-akte.command` im Ordner `Akte/start`. Geht kein Browser auf (etwa Linux ohne
   Bildschirm), nimmt dein Mensch den Notweg ohne Code: `cd ~/Akte && docker compose exec api python manage.py akte_einrichten`.
5. Verbinden: `bash ~/Akte/start/akte.sh agent --still`
6. Claude neu starten: `claude --continue`
<!-- agenten-anleitung:ende -->

---

## Am Code der Akte arbeiten

* **Der Mensch entscheidet.** Keine Änderung darf einem Werkzeug, Token oder Agenten erlauben, freizugeben, zu
  löschen, öffentlich zu schalten oder zu unterschreiben. Die Sperre gehört in den Server; dass der MCP-Server
  solche Werkzeuge gar nicht anbietet, reicht allein nicht.
* **Keine echten Personen** in Tests, Beispielen und Demos. Erfundene Namen („Freie Stadt Musterhafen“).
* **Deutsch** in Oberfläche, Meldungen und Code-Kommentaren, mit echten Umlauten. Englisch nur in `README.en.md`.
* **Keine Geheimnisse im Repo.** Vor jedem Commit laufen gitleaks und eine Sperrliste:
  `git config core.hooksPath .githooks`.
* **Byte-Gleichheit mit Atlas:** Änderungen an `beweis/` brauchen die grüne Kreuzprüfung.

Tests:

| Bereich | Befehl |
|---|---|
| Backend | `cd backend && python -m pytest -q` |
| MCP | `cd mcp && python -m pytest -q` |
| Beweis | `cd beweis && pytest -q` |
| Web | `cd web && npx tsc --noEmit && npx vitest run && npm run build` |
| Starter Windows | `powershell -NoProfile -ExecutionPolicy Bypass -File .github\scripts\starter-pruefen.ps1` |
| Starter macOS/Linux | `bash .github/scripts/starter-pruefen.sh` |

Fallen bei den Startern (`start/`):

* `akte.ps1` muss unter Windows PowerShell 5.1 laufen: keine Syntax aus PowerShell 7 (`??`, `?.`, `&&`), Datei als
  UTF-8 **mit** BOM, sonst zeigt 5.1 Umlaute falsch.
* Deutsche Anführungszeichen „ und “ beenden in PowerShell einen Text in `"…"`. Sie gehören nur in `'…'`.
* `.cmd`-Dateien brauchen CRLF (regelt `.gitattributes`) und enthalten keine Logik außer der Prüfung „entpackt?“.
  Eine `)` in einem `echo` innerhalb eines `( … )`-Blocks beendet den Block; daran scheiterte `START-AKTE.cmd` in
  0.1.0 auf jedem Windows.
* `akte.sh` läuft mit `set -euo pipefail`: kein `… | grep -q` (SIGPIPE), Bash 3.2 (macOS) muss reichen.
* Der Einrichtungscode erscheint in keiner Konsole, auch nicht im Fenster nach einem Doppelklick (ein
  Pseudo-Terminal sieht für ein Programm aus wie ein Fenster). `start` gibt ihn nur im Fragment der Adresse an den
  Browser (`#code=…`). Ohne Browser bleibt der Notweg `akte_einrichten`, der keinen Code braucht. Die Prüfskripte
  unter `.github/scripts/` prüfen das; neue Meldungen dürfen den Code nicht enthalten.
* `AKTE_BROWSER` (Browser-Ersatz) wirkt nur mit `AKTE_STARTER_TEST=1`; beides setzen nur die Prüfskripte.
* `-Fenster` (aus den `.cmd`-Dateien) lässt das Fenster am Ende auf Enter warten, aber nur, wenn Ein- und Ausgabe
  ein echtes Konsolenfenster sind. Ruft ein Agent auf, blockiert nichts.
* Ein Einrichtungscode entsteht nur für eine Akte ohne Daten-Volume; nach der Einrichtung löscht der Starter ihn aus
  `.env`. Windows: `.env` nur für das eigene Konto (`icacls`), macOS/Linux: `chmod 600`.
* Die Version steht in jedem Starter genau einmal (`$AkteVersion` in `akte.ps1`, `AKTE_VERSION` in `akte.sh`); die
  Prüfskripte lesen sie dort. In der Doku steht der Tag nur in Adressen als `/v0.2.0`.
* Programme mit vollem Pfad aufrufen (`%SystemRoot%\System32\…`), wo es geht: Auf manchen Rechnern ist der
  System-Pfad kaputt.
* Neue Starter-Dateien ausführbar einchecken: `git add --chmod=+x start/akte.sh start/stop-akte.command`.

Mehr: [CONTRIBUTING.md](CONTRIBUTING.md), [docs/mcp.md](docs/mcp.md), [docs/sicherheit.md](docs/sicherheit.md).
