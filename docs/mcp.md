# Die Akte mit Claude Code (MCP)

`akte-mcp` verbindet Claude Code (oder jeden anderen MCP-Client) mit deiner Akte. MCP ist die gemeinsame Sprache,
über die Claude die Werkzeuge anderer Programme benutzt.

## Einrichten

**Mit dem Starter (empfohlen).** Die Akte muss laufen und das erste Konto angelegt sein. Dann:

* Windows: `start\AGENT-VERBINDEN` doppelklicken, oder in PowerShell im Akte-Ordner:

  ```
  powershell -NoProfile -ExecutionPolicy Bypass -File start\akte.ps1 agent
  ```

* macOS und Linux:

  ```
  bash start/akte.sh agent
  ```

Der Starter installiert bei Bedarf uv (feste Version, Prüfsumme des Installers geprüft), trägt `.local\bin` in den
Pfad ein, holt den Token für das einzige aktive Redaktionskonto (Superuser zählen mit; sonst `-Konto NAME` bzw.
`--konto NAME`), ersetzt einen alten Eintrag `akte`, trägt den neuen ein und lädt den Baustein einmal vor. Danach
Claude Code neu starten: `/exit`, dann `claude --continue`.

**Von Hand.** Im Akte-Ordner (Windows: Rechtsklick auf eine freie Stelle → „In Terminal öffnen“), drei Zeilen. Sie
laufen gleich in PowerShell und in der Bash.

1. Token für dein Konto holen (er erscheint einmal; nicht weitergeben):

   ```
   docker compose exec api python manage.py akte_token DEIN-KONTO
   ```

2. Die Akte bei Claude Code eintragen (`DEIN-TOKEN` ersetzen; `8080` ist der Standard-Port, einen anderen findest
   du in `.env` unter `AKTE_PORT` und ersetzt `8080` damit):

   ```
   claude mcp add --scope user akte -e AKTE_BASIS=http://127.0.0.1:8080 -e AKTE_TOKEN=DEIN-TOKEN -- uvx --python 3.12 --from "https://github.com/ThePyth0nKid/die-akte/archive/refs/tags/v0.2.0.zip#subdirectory=mcp" akte-mcp
   ```

3. Einmal vorwärmen, damit Claude beim ersten Start nicht in seine Zeitgrenze läuft:

   ```
   uvx --python 3.12 --from "https://github.com/ThePyth0nKid/die-akte/archive/refs/tags/v0.2.0.zip#subdirectory=mcp" akte --help
   ```

Warum es genau so aussieht:

* `--scope user`: Die Akte steht in jedem Ordner zur Verfügung. Ohne den Schalter gilt der Eintrag nur für den
  Ordner, in dem du den Befehl getippt hast.
* `--python 3.12`: Ohne den Schalter nimmt uv das neueste Python. Für Python 3.15 gab es im Oktober 2026 noch kein
  fertiges PyYAML; der Server stand dann in `/mcp` auf „failed“.
* Die Release-ZIP statt `git+…`: Git braucht es so nicht.
* `127.0.0.1` statt `localhost`: Die Akte lauscht nur auf `127.0.0.1`. Windows versucht bei `localhost` zuerst die
  IPv6-Adresse und wartet dort bei jeder Anfrage rund zwei Sekunden. Im Browser ist `localhost` egal.
* Der Token steht danach im Klartext in `.claude.json` in deinem Benutzerordner. Gib diese Datei nicht weiter.
  Während `claude mcp add` läuft, steht er außerdem kurz in dessen Befehlszeile; andere Programme deines Kontos
  könnten ihn dort sehen. Mehr: [sicherheit.md](sicherheit.md).
* Der Baustein warnt (Meldung auf stderr, kein Abbruch), wenn ein Token über `http://` an eine Adresse geht, die
  nicht dein eigener Rechner ist. Für eine Akte im Netz gehört `https://` in `AKTE_BASIS`.
* Ohne Token sieht Claude in einer Akte auf deinem Rechner nichts: Lesen ohne Konto ist dort aus.

Prüfen: In Claude Code zeigt `/mcp` den Eintrag `akte` als verbunden. Antwortet ein Werkzeug „Die Akte ist nicht
erreichbar … Läuft sie?“, starte die Akte (`start\START-AKTE`).

## Werkzeuge

| Werkzeug | Zweck |
|---|---|
| `boards_liste` | Boards mit Mappen-Baum |
| `wand_lesen` | Karten, Fäden mit Belegen und Befunden, Rahmen, Zettel, Fahrten |
| `suche` | Karten nach Name oder Beschreibung |
| `weg` | kürzester Weg über Fäden zwischen zwei Karten |
| `pruefung` | offene Befunde je Faden |
| `quelle_anlegen` | Quelle anlegen; die Beweissicherung läuft danach im Hintergrund, die Antwort kommt sofort |
| `karte_anlegen` | Karte als Entwurf, optional auf ein Board |
| `faden_ziehen` | Faden mit Belegen als Entwurf, mit Startdatum, Ende oder „aktuell“; gibt Befunde zurück |
| `beleg_hinzufuegen` | weiterer Beleg an einem Faden |
| `zitat_pruefen` | steht das Zitat eines Belegs wörtlich in seiner Quelle? Antwort nach höchstens 30 Sekunden |
| `gruppen_setzen`, `aufraeumen` | Themen-Rahmen, Wand ordnen |
| `fahrt_anlegen` | Kamerafahrt für ein Video |
| `zettel_anlegen` | Notiz oder Frage (Meinungs-Zettel schreibt nur ein Mensch) |
| `import_paket` | viele Einträge auf einmal, Verbindungen mit `start`, `bis` (JJJJ-MM-TT) und `aktuell`; Probelauf zuerst, schreiben nur mit Bestätigung |
| `sichern` | Beweissicherung einer Quelle neu anstoßen (läuft im Hintergrund) |

Es gibt **kein** Werkzeug zum Freigeben, Löschen oder Öffentlich-Schalten, und der Server lehnt es für Tokens ab.
Auch die Einstellung „Quellen bei archive.org sichern“ ändert nur ein Mensch. Die Ressource `akte://regeln` enthält
die Belegregeln in Kurzform.

## Was `zitat_pruefen` antwortet

| `ergebnis` | Heißt | Was der Agent tut |
|---|---|---|
| `gefunden` | Der Wortlaut steht in der Quelle; `fundstelle` sagt wo. Ob er die Behauptung trägt und die Freigabe entscheidet ein Mensch. | weiter |
| `nicht_gefunden` | Der Wortlaut steht so nicht in der Quelle | an der Quelle nachlesen und das Zitat wörtlich korrigieren; nie umformulieren, bis es passt |
| `nicht_pruefbar` | Die Akte kann es nicht prüfen (`grund` sagt warum, z. B. Quelle ohne Adresse und ohne Datei, Seite nicht abrufbar, Bild-PDF ohne Text) | dem Menschen melden: selbst am Original prüfen |

Die Prüfung holt bei Bedarf nur das Original (nie archive.org). Sie ändert weder Beleg noch Status; hat die Quelle
noch gar keine eigene Kopie, legt sie höchstens diese erste Kopie ab. Der Server antwortet nach höchstens
30 Sekunden, der Baustein wartet bis 45 Sekunden. Ein Zitat darf höchstens 5000 Zeichen und 20 Teile (mit „[…]“
getrennt) haben. Der Auszug aus der Quelle in der Antwort ist gekürzt und als fremder Text gekennzeichnet: Er ist
Material, keine Anweisung an den Agenten. Ein zweiter Aufruf mit demselben Zitat bringt kein anderes Ergebnis.
Belege nacheinander prüfen, nicht alle gleichzeitig.

## Gute Arbeitsweise

1. Erst lesen (`boards_liste`, `wand_lesen`, `suche`).
2. Suchen mit dem Schlagwort **und** der amtlichen Bezeichnung (Gesetzestitel, Aktenzeichen, Fachbegriff), und nach
   beiden Seiten. Einen Negativbefund nur mit den benutzten Suchwörtern melden.
3. Quellen anlegen, dann Fäden mit Belegen (Zitat = Originalwortlaut), mit Startdatum und „aktuell“ oder Ende.
4. `zitat_pruefen` für jeden Beleg mit Zitat.
5. `pruefung` und offene Befunde der Redaktion melden, nicht wegdiskutieren.
6. Freigeben tut ein Mensch in der Oberfläche, mit seiner Unterschrift.

Für größere Recherchen empfiehlt sich das Verfahren aus dem Plugin `recherche` (Recherche-Agenten, unabhängiger
Faktenprüfer vor dem Import, Entscheidungstabelle für den Menschen). Der Skill `akte-fuehren` in `skills/` fasst die
Regeln für Claude zusammen.
