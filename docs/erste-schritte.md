# Erste Schritte mit der Akte

Diese Anleitung bringt dich von einem frischen Windows-PC bis zu deiner ersten eigenen Wand. Rechne mit 20 bis
40 Minuten; das meiste davon ist Warten auf Downloads. Alle Bilder stammen von einem Test-PC mit frischem
Windows 11. Fachwörter erklärt [docs/woerter.md](woerter.md). Mac und Linux: [ganz unten](#mac-und-linux).

## Was du brauchst

* Windows 10 oder 11 mit 64 Bit. Fast jeder PC ist ein „AMD64“-Rechner; „ARM64“ haben nur Geräte mit
  Snapdragon-Chip.
* 8 GB Arbeitsspeicher (mit 4 GB wird es knapp) und rund 10 GB frei auf Laufwerk C:.
* Internet.
* Ein Claude-Abo, Pro oder Max. Das kostenlose Claude-Konto reicht für Claude Code nicht.

## Teil 1: Claude Code installieren

**PowerShell öffnen.** Drück die Windows-Taste, tippe `PowerShell` und drück Enter. Es geht ein blaues oder
schwarzes Fenster auf. Darin tippst du Befehle und drückst Enter.

![Startmenü mit dem Suchwort PowerShell](bilder/powershell-oeffnen.png)

**Claude Code installieren.** Tipp diese Zeile ab oder kopier sie (Einfügen im Fenster: Rechtsklick oder Strg+V):

```
irm https://claude.ai/install.ps1 | iex
```

Das dauert etwa anderthalb Minuten, ohne Fortschrittsanzeige. Am Ende steht „Claude Code successfully installed!“.

**Der bekannte Fehler: „not in your PATH“.** Auf einem frischen Windows steht darunter oft:
`Native installation exists but …\.local\bin is not in your PATH`. Tippst du dann `claude`, antwortet Windows
mit „Die Benennung "claude" wurde nicht als Name eines Cmdlet … erkannt“. Der Installer hat vergessen, Windows zu
sagen, wo Claude liegt. Diese eine Zeile behebt das:

```
[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:USERPROFILE + '\.local\bin', 'User')
```

Danach schließt du das Fenster und öffnest ein neues. Ein offenes Fenster kennt neue Pfade nicht.

![Meldung des Claude-Installers: .local\bin is not in your PATH](bilder/claude-pfad-fehler.png)
![PowerShell erkennt claude nicht](bilder/claude-nicht-erkannt.png)

**Eigenen Ordner anlegen und Claude starten.** Claude Code arbeitet in dem Ordner, in dem du es startest. Ein
eigener Ordner `Recherche` sorgt dafür, dass Claude nicht deinen ganzen Benutzerordner sieht:

```
mkdir -Force $HOME\Recherche; cd $HOME\Recherche; claude
```

**Anmelden.** Claude Code ist englisch; schreiben kannst du ihm trotzdem auf Deutsch. Beim ersten Start wählst du
einen Farbstil (Enter genügt) und dann „1. Claude account with subscription“. Der Browser öffnet claude.ai. Gib
deine E-Mail-Adresse ein; du bekommst eine Mail mit einem Anmelde-Link. Öffnest du die Mail am Handy, zeigt der Link
einen Code, den du am PC eintippst. Danach bestätigst du mit „Autorisieren“.

![Claude Code: Auswahl der Anmeldung](bilder/claude-anmeldung.png)
![claude.ai: Anmeldecode eingeben](bilder/claude-anmeldecode.png)

**Der Sicherheitshinweis.** Claude Code sagt dir gleich zu Beginn: „Claude can make mistakes“, und dass du es nur mit
Inhalten benutzen sollst, denen du traust. Genau dafür gibt es die Akte: Claude schreibt Entwürfe, du prüfst und
unterschreibst.

![Claude Code: Security notes](bilder/claude-sicherheitshinweis.png)

**Dem Ordner vertrauen.** Claude fragt, ob du dem Ordner `Recherche` vertraust. Vorausgewählt ist „No, exit“:
Drück einmal den Pfeil nach unten auf „Yes, I trust this folder“ und dann Enter. Fragt es das für deinen ganzen
Benutzerordner, hast du Claude im falschen Ordner gestartet: „No, exit“ und zurück zum Schritt davor.

![Claude Code fragt, ob du dem Ordner Recherche vertraust](bilder/claude-ordner-vertrauen.png)

## Teil 2: Claude richtet die Akte ein

Tipp in Claude:

> Richte mir die Akte ein. Die Anleitung steht hier: https://github.com/ThePyth0nKid/die-akte

![Der Auftrag „Richte mir die Akte ein“ in Claude Code](bilder/claude-auftrag-einrichten.png)

Claude liest die Anleitung und arbeitet sie Schritt für Schritt ab. Es fragt dich, bevor es etwas installiert.
Folgendes machst du selbst:

**1. Docker installieren lassen (nur wenn es fehlt).** Docker ist das Programm, in dem die Akte läuft, abgeschottet
vom Rest deines PCs. Claude fragt dich, ob es Docker Desktop installieren soll. Sag ja. Dann:

* Windows fragt „Möchten Sie zulassen, dass durch diese App Änderungen an Ihrem Gerät vorgenommen werden?“: **Ja**.
* Erscheint ein Fenster „Configuration“ mit „Per-user installation (Recommended)“ und „All-users installation“:
  Wähl **„All-users installation“**. Die empfohlene Variante scheitert auf frischem Windows mit „Installation failed.
  One prerequisite is not fulfilled“. „Requires password“ heißt hier nur: Windows fragt noch einmal mit „Ja“.

![Docker-Installer: All-users installation wählen](bilder/docker-all-users.png)
![Docker-Installer: Fehler bei Per-user installation](bilder/docker-per-user-fehler.png)

**2. Neu starten.** Nach der Installation braucht Windows einen Neustart. Claude sagt dir vorher, was danach kommt.
Nach dem Neustart gehen zwei Fenster gleichzeitig auf:

* Ein schwarzes Fenster: „Windows-Subsystem für Linux muss auf die neueste Version aktualisiert werden … Drücken Sie
  eine beliebige Taste … Timeout in 60 Sekunden“. **Drück sofort eine Taste** und danach „Ja“. Es liegt oft halb
  hinter dem Docker-Fenster.
* Das Docker-Fenster mit dem Vertrag: **„Accept“**. Anmelden bei Docker musst du dich nicht.

Meldet Docker danach „WSL not installed … run wsl --install …“, obwohl das schwarze Fenster gerade „erfolgreich“
gemeldet hat: Docker war schneller als Windows. Klick „Quit“, warte eine Minute und öffne Docker Desktop wieder
(Startmenü: „Docker Desktop“). Das Fenster „Willkommen bei WSL“ kannst du schließen.

![WSL-Aktualisierung: eine Taste drücken](bilder/docker-wsl-taste.png)
![Docker meldet WSL not installed](bilder/docker-wsl-rennen.png)

**3. Claude weitermachen lassen.** Öffne PowerShell und tipp:

```
cd $HOME\Recherche; claude --continue
```

`--continue` setzt das Gespräch von vorhin fort. Claude lädt jetzt die Akte und startet sie. Beim ersten Mal baut
Docker 3 bis 10 Minuten.

**4. Dein Konto anlegen.** Wenn die Akte läuft, öffnet sich der Browser mit der Seite „Erstes Konto anlegen“. Dein
**Einrichtungscode** (acht Zeichen wie `K7QM-3XPA`) ist dort schon eingetragen. Der Code beweist der Akte, dass du
an diesem Rechner sitzt. Claude kennt ihn nicht und fragt nie danach. Wähl:

* einen Benutzernamen,
* ein Passwort mit mindestens 10 Zeichen, kein Allerweltswort, nicht nur Ziffern. Claude erfährt es nicht.
* die Antwort auf „Quellen zusätzlich öffentlich bei archive.org sichern?“. **Ja** heißt: Die Akte meldet die
  Adresse jeder Quelle an archive.org, das eine öffentliche Kopie anlegt. Verschwindet die Seite später, gibt es
  einen unabhängigen Beleg; dafür kann jeder sehen, welche Seiten gesichert wurden. **Nein** (Standard) heißt: Nur
  deine eigene Kopie auf deinem Rechner. Du kannst es später unter „Regeln“ ändern.

Sag Claude danach „fertig“.

![Die Seite Erstes Konto anlegen](bilder/akte-einrichten-seite.png)

Hast du die Seite geschlossen oder ist das Feld für den Code leer: Öffne im Explorer deinen Benutzerordner, dann
`Akte` und `start`, und doppelklick `START-AKTE`. Der Starter öffnet die Seite neu, mit dem Code. Ein Fenster, das
den Code anzeigt, gibt es bewusst nicht. Sobald dein Konto steht, löscht der Starter den Code wieder; er wird nicht
mehr gebraucht.

Geht gar kein Browser auf, legst du das Konto im Terminal an. Dafür brauchst du keinen Code. Öffne PowerShell und
tipp diese Zeile; das Programm fragt nach Benutzername und Passwort (das Passwort siehst du beim Tippen nicht):

```
cd "$env:USERPROFILE\Akte"; docker compose exec api python manage.py akte_einrichten
```

**5. Claude neu starten.** Claude verbindet sich jetzt mit der Akte (bis zu 2 Minuten) und sagt dann:
„Fertig. Beende Claude (/exit) und starte es neu mit: claude --continue“. Tipp `/exit`, Enter, dann
`claude --continue`. Sagt Claude, du sollst dafür ein neues Fenster öffnen, mach das und geh vorher mit
`cd $HOME\Recherche` in deinen Ordner.

![Ausgabe: Claude Code ist mit deiner Akte verbunden](bilder/akte-agent-verbunden.png)

**6. Prüfen.** Tipp `/mcp`. Dort steht `akte` mit einem Haken. Schau dir bei der Gelegenheit die anderen Einträge
an: Claude zeigt dort auch Verbindungen aus deinem claude.ai-Konto, etwa Gmail oder Kalender. Was du für die
Recherche nicht brauchst, schaltest du in den Einstellungen deines Claude-Kontos ab.

![/mcp: akte ist verbunden](bilder/claude-mcp-verbunden.png)

## Teil 3: Dein erster Auftrag

**Demo laden.** Tipp „Lade die Demo der Akte.“ Claude lädt die erfundene Akte „Freie Stadt Musterhafen“ und öffnet
http://localhost:8080/akte/demo-musterhafen. Melde dich dort mit deinem Konto an. Alle Namen darin sind erfunden.

**Die Wand lesen lassen.** Tipp:

> Lies die Wand demo-musterhafen und sag mir, welche Fäden noch offene Befunde haben.

Nach etwa 20 Sekunden zählt Claude auf, welche Fäden belegt sind und wo etwas fehlt.

![Claudes Antwort zur Demo-Wand](bilder/claude-erster-auftrag.png)

**Freigeben ist deine Sache.** Tipp „Gib Faden 6 frei.“ Claude antwortet, dass es dafür bewusst kein Werkzeug hat.
So ist es gebaut: Was Claude anlegt, bleibt Entwurf, bis du es unterschreibst.

![Claude lehnt die Freigabe ab](bilder/claude-freigabe-verweigert.png)

**Unterschreiben.** Im Browser klickst du einen Faden an. Prüf, ob das Zitat in der Quelle steht: Quelle
öffnen, Stelle suchen. Dann Status „Freigeben (unterschreiben)“ und „Faden speichern“. Ein Fenster zeigt in
Klartext, was du unterschreibst; lies es und bestätige. Beim ersten Mal erzeugt dein Browser dafür deinen
persönlichen Schlüssel. Ein Faden wird erst sichtbar, wenn auch beide Karten unterschrieben sind (Karte anklicken,
Stift, Status, Speichern).

![Faden mit dem Status Freigeben (unterschreiben)](bilder/akte-faden-unterschreiben.png)
![Das Fenster vor der Unterschrift](bilder/akte-unterschrift-dialog.png)

**Deine eigene Wand.** Drei Aufträge zum Kopieren:

> Recherchiere im Lobbyregister des Bundestags, welche Organisationen zur Chatkontrolle Lobbyarbeit eingetragen
> haben, Befürworter und Gegner. Such auch nach der amtlichen Bezeichnung der EU-Verordnung. Leg die wichtigsten als
> Karten mit Quelle und wörtlichem Zitat auf eine neue Wand „Chatkontrolle“.

> Prüf jedes Zitat auf der Wand chatkontrolle mit zitat_pruefen und sag mir, welche nicht gefunden wurden.

> Welche Fäden auf der Wand chatkontrolle haben noch kein Startdatum? Schlag mir Daten mit Quelle vor.

Was Claude anlegt, erscheint nach wenigen Sekunden von selbst auf der Wand, als Entwurf.

![Eine fertige Recherche-Wand](bilder/akte-wand-chatkontrolle.png)

**Die Lehre aus dem ersten Test.** Claude suchte im Lobbyregister nur nach „Chatkontrolle“, fand nur Gegner und
schrieb sicher klingend, es gebe keine Befürworter. Das war falsch: Die Befürworter stehen unter der amtlichen
Bezeichnung der EU-Verordnung. Darum: nach der amtlichen Bezeichnung fragen, beide Seiten verlangen, selbst prüfen,
dann unterschreiben.

## Ohne Claude: von Hand starten

1. **Docker Desktop** von https://www.docker.com/products/docker-desktop/ laden („Download for Windows – AMD64“),
   installieren mit **„All-users installation“**, neu starten, WSL-Fenster: Taste, Docker-Fenster: „Accept“.
2. **Die Akte laden:** https://github.com/ThePyth0nKid/die-akte/releases/tag/v0.2.0-rc.2 → „Source code (zip)“.
3. **Entpacken:** Rechtsklick auf die ZIP-Datei → „Alle extrahieren“. Klick nicht in der ZIP auf START-AKTE: Windows
   entpackt dann nur diese eine Datei, und der Starter meldet „Bitte zuerst entpacken“.

   ![Rechtsklick: Alle extrahieren](bilder/zip-entpacken.png)

4. **Starten:** im entpackten Ordner `start` die Datei `START-AKTE` doppelklicken (Typ „Windows-Befehlsskript“).
   Windows warnt „Der Herausgeber konnte nicht verifiziert werden“: „Ausführen“. Das Fenster zeigt, was passiert;
   am Ende öffnet der Browser die Seite „Erstes Konto anlegen“ mit deinem Einrichtungscode schon eingetragen. Das
   Fenster bleibt offen, bis du Enter drückst.

   ![Warnung: Unbekannter Herausgeber](bilder/herausgeber-warnung.png)

5. **Konto anlegen** im Browser wie in Teil 2, Punkt 4.
6. **Claude verbinden** (wenn du Claude Code installiert hast): `start\AGENT-VERBINDEN` doppelklicken, danach Claude
   neu starten.

## Jeden Tag

* Die Akte läuft im Hintergrund weiter, auch nach einem Neustart, sobald Docker Desktop läuft. Adresse:
  http://localhost:8080/akte (hat der Starter einen anderen Port gewählt, steht er im Starter-Fenster).
* Anhalten: `start\STOP-AKTE`. Wieder starten: `start\START-AKTE`. Deine Daten bleiben erhalten.
* Claude starten: PowerShell öffnen, `cd $HOME\Recherche; claude`.

## Wenn etwas hakt

| Problem | Lösung |
|---|---|
| `claude` wird nicht erkannt | Die Pfad-Zeile aus Teil 1, dann ein neues Fenster öffnen |
| Docker: „Installation failed. One prerequisite is not fulfilled“ | Installer neu starten, „All-users installation“ wählen |
| WSL-Fenster nach dem Neustart verpasst | Docker Desktop schließen, PC noch einmal neu starten |
| Docker: „WSL not installed“ direkt nach der Installation | „Quit“, eine Minute warten, Docker Desktop neu öffnen |
| START-AKTE blitzt nur kurz auf | Die ZIP ist nicht entpackt: Rechtsklick → „Alle extrahieren“ |
| Starter meldet „Port 8080 ist belegt“ | Er nimmt selbst einen anderen; die neue Adresse steht im Fenster. War Claude schon verbunden: `AGENT-VERBINDEN` noch einmal |
| Passwort vergessen | Im Akte-Ordner Rechtsklick auf eine freie Stelle → „In Terminal öffnen“, dann `docker compose exec api python manage.py changepassword DEIN-NAME` |
| In `/mcp` steht `akte` mit ✗ | `start\AGENT-VERBINDEN` noch einmal, dann Claude neu starten |
| Claude sagt „Die Akte ist nicht erreichbar“ | Docker Desktop öffnen, `start\START-AKTE` doppelklicken |
| Oben in Claude steht mal Opus, mal Sonnet | Das Modell wählst du mit `/model` |

## Was es kostet

Die Akte und uv kosten nichts. Docker Desktop ist für Privatleute, Bildung, nichtkommerzielle Open-Source-Arbeit und
kleine Firmen kostenlos. Für Claude Code brauchst du ein Claude-Abo (Pro oder Max). Weitere Suchdienste brauchst du
nicht. Die Tabelle: [README](../README.md#was-es-kostet).

## Was deinen Rechner verlässt

* **An Anthropic:** deine Aufträge an Claude und alles, was Claude von der Wand liest oder im Netz findet.
* **An die Webseiten deiner Quellen:** Die Akte ruft jede Quelle von deinem Anschluss ab, um eine Kopie zu sichern.
  Die Seite sieht deine IP-Adresse und die Kennung „Die-Akte … Beweissicherung“.
* **An archive.org:** nur, wenn du es eingeschaltet hast (Frage beim ersten Konto).

Datenbank, Kopien, Passwort und dein Unterschrift-Schlüssel bleiben bei dir. Die ganze Tabelle:
[README](../README.md#was-deinen-rechner-verlässt).

## Mac und Linux

**macOS:**

1. Docker Desktop von https://www.docker.com/products/docker-desktop/ laden („Apple Silicon“ für Macs mit M-Chip,
   sonst „Intel Chip“), in „Programme“ ziehen, einmal öffnen, Vertrag „Accept“.
2. Claude Code im Terminal (Programme → Dienstprogramme → Terminal):

   ```
   curl -fsSL https://claude.ai/install.sh | bash
   ```

3. Ordner anlegen und Claude starten:

   ```
   mkdir -p ~/Recherche && cd ~/Recherche && claude
   ```

4. Dann wie unter Windows: Sag zu Claude:

   > Richte mir die Akte ein. Die Anleitung steht hier: https://github.com/ThePyth0nKid/die-akte

Von Hand: Die Akte nach `~/Akte` laden und `start/start-akte.command` doppelklicken. Beim ersten Mal blockiert
macOS die Datei. Dann: Rechtsklick → „Öffnen“, bei neuem macOS Systemeinstellungen → „Datenschutz & Sicherheit“ →
„Dennoch öffnen“. Der Browser öffnet die Seite „Erstes Konto anlegen“ mit dem Einrichtungscode schon eingetragen.

**Linux:** Docker Engine mit dem Compose-Plugin installieren (https://docs.docker.com/engine/install/) und dein Konto
in die Gruppe `docker` aufnehmen: `sudo usermod -aG docker $USER`, danach ab- und wieder anmelden. Claude Code wie
beim Mac. Starten: `~/Akte/start/start-akte.command`, anhalten: `bash ~/Akte/start/akte.sh stop`. Ohne Browser
(etwa auf einem Server) legst du das erste Konto ohne Code im Terminal an:
`cd ~/Akte && docker compose exec api python manage.py akte_einrichten`.

## Bilder für diese Seite

Die Bilder liegen in `docs/bilder/`. Wo ein Bild aus dem ersten Durchlauf auf dem Test-PC passt, steht es in der
rechten Spalte; „neu“ heißt: im nächsten Durchlauf (Version 0.2.0) aufnehmen.

| Datei | Was zu sehen sein soll | Vorlage |
|---|---|---|
| `powershell-oeffnen.png` | Startmenü mit dem Suchwort „PowerShell“ | neu |
| `claude-pfad-fehler.png` | Installer: „successfully installed“ und „…\.local\bin is not in your PATH“ | d1_66_claude_path |
| `claude-nicht-erkannt.png` | PowerShell: „Die Benennung "claude" wurde nicht … erkannt“ | d1_68_claude_nicht_erkannt |
| `claude-anmeldung.png` | Claude Code: „Select login method“ | d1_70 |
| `claude-anmeldecode.png` | claude.ai: Anmeldecode eingeben oder „Autorisieren“ | d1_72, d1_76 |
| `claude-sicherheitshinweis.png` | Claude Code: „Security notes: Claude can make mistakes …“ | d1_79_claude_sicherheit |
| `claude-ordner-vertrauen.png` | Vertrauensfrage für den Ordner `Recherche` (nicht den Benutzerordner) | neu (d1_80 zeigt den Benutzerordner) |
| `claude-auftrag-einrichten.png` | Eingabe „Richte mir die Akte ein …“ in Claude Code | neu |
| `docker-all-users.png` | Docker-Installer „Configuration“ mit „All-users installation“ gewählt | d1_16 |
| `docker-per-user-fehler.png` | „Installation failed. One prerequisite is not fulfilled.“ | d1_14_fehler_zoom |
| `docker-wsl-taste.png` | Konsole „Windows-Subsystem für Linux muss … aktualisiert werden … beliebige Taste“ | d1_22_wsl_zoom |
| `docker-wsl-rennen.png` | Docker „WSL not installed“ neben der WSL-Erfolgsmeldung | d1_25_wsl_rennen |
| `akte-einrichten-seite.png` | Browser: Seite „Erstes Konto anlegen“, Code schon eingetragen, mit der Frage nach archive.org | neu |
| `akte-agent-verbunden.png` | Ausgabe von AGENT-VERBINDEN bzw. `akte.ps1 agent` mit dem Schlusssatz | neu |
| `claude-mcp-verbunden.png` | `/mcp` mit „akte ✓“ (claude.ai-Verbindungen unkenntlich) | d1_101_mcp_verbunden |
| `claude-erster-auftrag.png` | Claudes Antwort zur Demo-Wand | d1_102_erster_auftrag |
| `claude-freigabe-verweigert.png` | „Es gibt bewusst kein Tool, mit dem ich einen Faden selbst freigeben kann …“ | d1_103_freigabe_verweigert |
| `akte-faden-unterschreiben.png` | Faden-Formular mit Status „Freigeben (unterschreiben)“ | neu (d1_110 zeigt die alte Fassung) |
| `akte-unterschrift-dialog.png` | Das neue Fenster vor der Unterschrift, in Klartext | neu (ersetzt d1_112) |
| `akte-wand-chatkontrolle.png` | Fertige Wand „Chatkontrolle“ mit belegten Fäden | d1_109_wand_chatkontrolle |
| `zip-entpacken.png` | Explorer: Rechtsklick auf die ZIP → „Alle extrahieren“ | d1_40 |
| `herausgeber-warnung.png` | „Der Herausgeber konnte nicht verifiziert werden … Unbekannter Herausgeber“ | d1_37_herausgeber |
