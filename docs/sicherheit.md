# Sicherheit und Beweiskraft

Was die Ultra-Akte schützt, was eine gültige Beweiskette beweist – und was nicht. Stand: Version 0.3.

## Grundannahmen

* **Lokal zuerst.** Die Akte läuft auf dem Rechner der Redaktion. Der Port ist an `127.0.0.1` gebunden; von außen ist
  sie nicht erreichbar, solange du das nicht bewusst änderst ([betrieb.md](betrieb.md)).
* **Menschen und Werkzeuge sind getrennt.** Menschen melden sich mit Passwort an (JWT im httpOnly-Cookie).
  Werkzeuge und Agenten benutzen ein Token (`manage.py akte_token`). Der Server unterscheidet beide.
* **Der Server signiert nie für einen Menschen.** Der private Schlüssel eines Menschen entsteht im Browser
  (WebCrypto, Ed25519, nicht exportierbar) und verlässt ihn nie.
* **Das erste Konto legt ein Mensch im Browser an.** Der Starter erzeugt einen Einrichtungscode (8 Zeichen aus 32,
  also 40 Bit, in `.env`), aber nur für eine Akte, die noch keine Daten hat. Keine Konsole zeigt ihn an: nicht
  `status -Json`, nicht die Ausgabe von `start` oder `agent`, auch nicht das Fenster nach einem Doppelklick auf
  `START-AKTE` (ein Agent mit Pseudo-Terminal sähe für den Starter aus wie ein Fenster). Der Starter öffnet den
  Browser selbst auf `/akte/einrichten#code=…`. Den Teil hinter `#` (das Fragment) schickt ein Browser an keinen
  Server, er steht in keinem Protokoll der Akte, und die Seite löscht ihn sofort aus der Adresszeile. Geht kein
  Browser auf, bleibt der Notweg `akte_einrichten` im Terminal; der braucht keinen Code. Die Einrichtung nimmt den
  Code nur an, solange es kein aktives Konto der Redaktion gibt, vergleicht in konstanter Zeit und ist gedrosselt
  wie die Anmeldung. Steht das erste Konto, löscht der Starter den Code aus `.env`. So öffnet auch ein später
  deaktiviertes Konto die Einrichtung nicht mit dem alten Code wieder. Der laufende Container kennt den Code, bis er
  neu erstellt wird (nächstes `START-AKTE` bzw. `docker compose up -d`; ein Neustart von PC oder Docker erstellt ihn
  nicht neu). Eine Ablaufzeit hat der Code bewusst nicht: Sie wäre für Anfänger eine Stolperfalle mehr.
* **Was das schützt und was nicht:** Die Maßnahme verhindert, dass ein Agent, der seinen Anweisungen folgt, den Code
  versehentlich sieht, in einem Gespräch wiedergibt oder weitergibt. Gegen einen Agenten, der sich darüber
  hinwegsetzt, hilft sie nicht. Wer eine Shell, Docker oder Lesezugriff auf deine Dateien hat, kann den Code lesen:
  aus `.env`, aus der Umgebung des Containers oder aus der Befehlszeile des Browsers, die der Starter aufruft (dort
  steht er, solange der Browser-Prozess läuft; bei einem schon offenen Browser nur kurz). Mit Docker braucht er ihn
  nicht einmal: `manage.py` im Container legt Konten ohne Code an. Unter Umständen steht die Adresse samt Code auch
  im Verlauf des Browsers; nach der Einrichtung ist er dort wertlos. Wer ganz sicher gehen will, legt das erste Konto
  an, bevor er einen Agenten startet (Doppelklick auf `START-AKTE`), und prüft auf der Seite, dass das Konto seins
  ist.
* **`.env` nur für dich.** Der Starter beschränkt die Rechte der Datei auf dein Benutzerkonto (Windows: nur dein
  Konto in der Zugriffsliste, ohne geerbte Rechte; macOS und Linux: `chmod 600`). Andere Konten ohne Adminrechte
  lesen sie nicht; Administratoren des Rechners kommen wie an jede Datei trotzdem heran. Sie enthält den geheimen
  Schlüssel der Akte. Leg den Ordner der Akte nicht in OneDrive, Dropbox oder einen anderen Cloud-Ordner (unter
  Windows sind Desktop und Dokumente oft welche): Sonst landet `.env` in der Cloud.
* **Protokolle auf verwalteten Rechnern:** Ist auf dem Rechner PowerShell-Protokollierung (Modul- oder
  Skriptblock-Protokoll, Transkription) oder eine Prozess-Überwachung mit Befehlszeilen eingeschaltet, wie oft auf
  Firmen-PCs, können der Einrichtungscode (Befehlszeile des Browsers) und der Token (Befehlszeile von
  `claude mcp add`) in diesen Protokollen stehen. Wer sie lesen darf, kann beides nutzen: den Code nur bis zum ersten
  Konto, den Token bis `akte_token NAME --neu`.
* **Der Token eines Agenten** entsteht mit `akte_token` im Container. Der Starter (`akte.ps1 agent`, `akte.sh
  agent`) gibt ihn nie aus und trägt ihn direkt bei Claude Code ein. Zwei Stellen, an denen er trotzdem steht: kurz
  in der Befehlszeile von `claude mcp add` (andere Programme unter deinem Konto können die Prozessliste lesen) und
  danach im Klartext in `.claude.json` im Benutzerordner. Einen sichereren Weg ohne Mehraufwand für Anfänger gibt es
  in Claude Code derzeit nicht. Wer den Token hat, kann als Werkzeug Entwürfe anlegen, aber nichts freigeben.
  Neuer Token: `akte_token NAME --neu`, danach den Agenten neu verbinden (jeder verbundene Agent braucht dann den
  neuen). Der Baustein `akte-mcp` warnt auf stderr, wenn ein Token über `http://` an eine Adresse geht, die nicht
  dein eigener Rechner ist; für eine Akte im Netz gehört `https://` davor.

## Was Leser sehen

Mitglieder und Besucher ohne Konto bekommen eine eigene Lese-Ansicht, nie die Werkstatt. Standard
(`AKTE_LESEANSICHT=nur_gepruefte`):

* nur Karten, die ein Mensch freigegeben hat und die seit der Unterschrift unverändert sind,
* nur Fäden, die die Prüfung des Boards bestehen: freigegeben, unverändert, kein sperrender Befund,
* Personen mit vollem Namen erst, wenn ein Mensch die Karte samt „öffentliche Person“ unterschrieben hat; sonst
  Initialen, ohne Kennung, die sich über Boards verknüpfen ließe,
* keine Notizen, Fragen, Fahrten, Befunde, Verfasser; Meinungs-Zettel nur von Menschen.

`alles_belegte` zeigt jeden belegten Faden, auch Entwürfe. Das ist für geschlossene Runden gedacht, nicht für die
Öffentlichkeit.

**Veröffentlichen** geht über „Regeln“ → „Veröffentlichen“: Erst die Vorschau für Besucher, dann das Umschalten. Die
Vorschau zeigt genau die Lese-Ansicht und alle Freitexte, die keine Unterschrift deckt – Titel, Beschreibung,
Rahmen, Meinungs-Zettel, Mappen –, auch wenn ein Werkzeug sie auf dem Arbeits-Board geschrieben hat.

## Was Werkzeuge und Agenten nicht können

Mit einem Token (CLI, MCP-Server) lässt der Server **nicht** zu (403 bzw. 409):

* den Status setzen oder freigeben, Freigegebenes ändern oder löschen, die Quelle eines freigegebenen Fadens ändern,
* ein Board öffentlich schalten, seine Prüfregeln ändern, ein Board löschen,
* ein **veröffentlichtes** Board (öffentlich oder Mitglieder-Board) ändern: keine Karten, Zettel, Rahmen, Mappen,
  kein Ausblenden; erlaubt bleiben Anordnung und Fahrten, die Leser nicht als Inhalt sehen,
* eine Person zur öffentlichen Person machen (ein Vorschlag beim Anlegen bleibt bis zur Unterschrift verdeckt),
* Meinungs-Zettel schreiben, ändern oder löschen,
* einen Schlüssel anmelden, eine Freigabe oder einen Widerruf unterschreiben.

Der MCP-Server bietet diese Werkzeuge gar nicht erst an; die Sperre liegt trotzdem im Server, damit sie auch gilt,
wenn jemand die API direkt aufruft. Tests: `backend/akte/tests/test_menschenrecht.py`, `test_beweisschicht.py`.

## Die Beweiskette

Format: [`atlas-trace-v1`](https://github.com/ThePyth0nKid/atlas) (Prüfer unter Apache-2.0).

* Jedes Ereignis ist ein kanonisch kodiertes CBOR-Dokument (RFC 8949 § 4.2.1) mit Arbeitsbereich, Kennung,
  Zeitstempel, Schlüssel-ID, Vorgänger-Hash und Nutzlast; signiert mit **Ed25519**, adressiert über **BLAKE3**.
* Die Kette ist **linear**: genau ein Anfang, jedes Ereignis hat genau einen Vorgänger (`--require-strict-chain`).
* Das **Schlüsselbündel** (alle öffentlichen Schlüssel) ist über seinen Hash an den Trace gebunden; wer einen
  Schlüssel austauscht, bricht den Hash.
* **Rollen** stecken in der Schlüssel-ID: `akte-mensch:<fingerabdruck>`, `akte-geraet:<fingerabdruck>`,
  `akte-agent:<name>`. Freigaben, Überstimmungen und Widerrufe gelten nur mit einem Menschenschlüssel. Die IDs tragen
  keine Kontonamen: Das Schlüsselbündel ist öffentlich.
* **Nutzlast** einer Freigabe ist nur `{type, objekt, inhalt_zusage}`. Objekt-ID, Inhalt, offene Hinweise und
  Überstimmungen samt Begründung stecken in der Zusage `sha256(salz ‖ kanonisches JSON)`.
* **Offenlegung:** Der Export legt Inhalt und Salz nur für die jüngste Freigabe von Objekten offen, die öffentlich
  sichtbar sind, dazu die Sicherungen ihrer Quellen – nie für Inhalte mit dem vollen Namen einer Privatperson.
  Begründungen von Überstimmungen werden dabei veröffentlicht; die Oberfläche sagt das vor jeder Unterschrift.
* **Widerruf** ist ein signiertes Ereignis (`akte.widerruf`, Knopf „Regeln“ → „Deine Schlüssel“). Jedes spätere
  Ereignis eines widerrufenen Schlüssels ist für jeden Prüfer ungültig, gemessen an der Abstammung in der Kette.
* **Schwärzen** (`manage.py akte_schwaerzen`) löscht Salz und Inhalt eines Ereignisses, etwa nach einer
  Unterlassungsverfügung. Die Kette bleibt gültig, der Export nennt das Ereignis unter `geschwaerzt`, und das Objekt
  verschwindet aus der Lese-Ansicht, bis ein Mensch neu unterschreibt.

### Eine gültige Kette beweist

* **Unverändertheit:** Kein Ereignis, kein offengelegter Inhalt und kein Schlüssel wurde nachträglich verändert,
  eingefügt, umsortiert oder entfernt (innerhalb des exportierten Traces).
* **Urheberschaft:** Jede Freigabe stammt von dem Schlüssel, dessen ID sie trägt, und dieser ist ein Menschenschlüssel.
* **Bezug:** Die Freigabe eines Fadens deckt genau diesen Inhalt – Enden, Aussage, Konfidenz, Zeitraum, Anhörung,
  Belege mit Zitat, Quellen mit Datum, Archiv und Güte sowie der SHA-256 der gesicherten Originale. Ändert sich
  etwas, auch an einer Karte oder Quelle, ist der Faden wieder Entwurf bzw. „verändert seit Freigabe“ und für Leser
  unsichtbar, bis ein Mensch neu unterschreibt. Die Akte vergleicht das bei jedem Lesen, nicht nur beim Speichern.

### Sie beweist nicht

* **Wahrheit.** Eine Unterschrift sagt, wer wann was freigegeben hat, nicht, dass es stimmt.
* **Identität hinter einem Schlüssel.** `akte-mensch:<fingerabdruck>` sagt nur, dass ein Mensch dieser Instanz
  unterschrieben hat. Wer prüfen will, wer das ist, braucht den Fingerabdruck auf einem zweiten Weg (z. B.
  veröffentlicht im Impressum).
* **Zeitpunkt gegenüber Dritten.** Die Zeitstempel setzt der Server. Gegen einen Betreiber, der rückdatiert, hilft nur
  eine Verankerung bei einer unabhängigen Stelle (Sigstore Rekor, RFC-3161-Zeitstempel). Das ist **geplant** und noch
  nicht enthalten.
* **Vollständigkeit über den Export hinaus.** Wer einen älteren Export zurückhält und einen neueren zeigt, fällt nur
  auf, wenn jemand beide vergleicht (gleiche Anfänge, neuere Kette verlängert die ältere) – oder mit Verankerung.

## Weitere Schutzmaßnahmen

* **Abruf fremder Seiten (SSRF):** Die Beweissicherung lädt nur `http(s)` auf Port 80/443, prüft jede aufgelöste
  Adresse und jede Weiterleitung gegen private, lokale und reservierte Netze und begrenzt Größe und Zeit
  (`backend/akte/abruf.py`, Tests in `test_sicherung.py`).
* **Nur bekannte Namen:** Der Eingang (Caddy) beantwortet nur Anfragen an die Namen in `AKTE_HOSTS` (Standard
  `localhost 127.0.0.1 ::1 [::1]`), alles andere mit 421. Das schützt vor DNS-Rebinding: Eine fremde Webseite, deren
  Name plötzlich auf 127.0.0.1 zeigt, kommt so nicht an die Akte. Wer die Akte unter eigener Domain betreibt, trägt
  sie in `AKTE_HOSTS` ein ([betrieb.md](betrieb.md#für-ein-team-im-netz)).
* **Drossel ohne Konto:** zählt die Verbindungsadresse; Proxy-Köpfen wird nur nach Einstellung geglaubt
  (`AKTE_CLIENT_IP_HEADER`, `AKTE_VERTRAUTE_PROXYS`). Der Export der Kette hat eine eigene, engere Drossel.
* **Anmeldung:** Fehlversuche zählen je Konto *und* Absender (10 je Minute), dazu ein Deckel je Absender. Ein Fremder
  kann so niemanden aussperren. Der Preis: Wer von sehr vielen Adressen aus rät, kommt auf 10 Versuche je Minute und
  Adresse. Darum lange Passwörter (mindestens 10 Zeichen, gegen Listen geprüft) und die Akte nur hinter HTTPS und
  bewusst ins Netz stellen.
* **Sitzungen:** Refresh-Tokens rotieren; ein benutzter oder abgemeldeter Token steht auf einer Sperrliste.
  Ändernde Anfragen an die Oberfläche müssen aus ihr selbst kommen (`Sec-Fetch-Site`/`Origin`), dazu
  `SameSite=Lax`-Cookies, `frame-ancestors 'none'`, `nosniff`. Die Django-Verwaltung ist über den Eingang nicht
  erreichbar.
* **archive.org** ist standardmäßig aus. Einschalten kann es nur ein Mensch: beim ersten Konto oder unter „Regeln“ →
  „Für die ganze Akte“; ein Token kann die Einstellung nicht ändern. Die Änderung wirkt sofort auf die Prüfung
  (Regel `quelle_ohne_archiv`). Ist es an, geht jede Quell-URL hinaus, sobald
  die Sicherung läuft, auch für Quellen, die ein Werkzeug angelegt hat. Nie hinaus gehen Adressen mit Zugangsdaten,
  mit Zugangs-Parametern (signierte Links, `token`, `key`, `session` …) und aus dem eigenen Netz.
* **Abruf von deinem Anschluss:** Die Beweissicherung lädt jede Quelle selbst. Die Gegenseite sieht deine IP-Adresse
  und die Kennung „Ultra-Akte/0.3 … Beweissicherung“, die bei allen Installationen gleich ist und die Akte als
  Absender erkennbar macht (ändern mit `AKTE_ABRUF_KENNUNG`). Wer das nicht will, lädt die Quelle als Datei hoch.
* **Beweis-Speicher:** Kopien werden vollständig geschrieben und erst dann sichtbar; beim Lesen wird die Prüfsumme
  verglichen, eine veränderte Kopie wird nie ausgeliefert.
* **Privatpersonen:** öffentlich nur mit Initialen, ohne Kennung, die sich über Boards verknüpfen ließe; Verdacht und
  Familie über sie sperren von Haus aus.
* **Geräteschlüssel:** Datei mit Rechten 600 im Datenordner, nie in der Datenbank, nie im Export. Er unterschreibt
  nur, was der Server selbst gesehen hat; ein lokal gemeldetes Video (Prüfsumme vom Helfer) unterschreibt er nicht.
* **Kein Geheimnis im Repo:** gitleaks und eine Sperrliste prüfen jeden Commit (`werkzeuge/scrub/`, `.githooks/`).

## Woher die Teile kommen (Lieferkette)

Wer die Akte einrichtet, vertraut diesen Stellen. Was davon fest ist und was nicht:

| Teil | Woher | Fest? | Wer vertraut wem |
|---|---|---|---|
| Die Akte selbst (Starter, Backend, Oberfläche) | Release-ZIP zum Git-Tag `v0.3.0` auf GitHub | Ein Tag ist ein Verweis auf einen Commit. Der Besitzer des Repos könnte ihn verschieben. Die SHA-256-Prüfsumme der ZIP steht in den Release-Notizen; vergleichen mit `Get-FileHash DATEI` bzw. `shasum -a 256 DATEI`. GitHub packt die ZIP selbst; ihre Prüfsumme bleibt in der Praxis gleich, garantiert ist das nicht. Fester ist der Commit-Hash in den Release-Notizen. | du dem Konto `ThePyth0nKid` bei GitHub |
| Der Baustein für Claude (`akte-mcp`) | dieselbe Release-ZIP (`…/v0.3.0.zip#subdirectory=mcp`), seine Python-Pakete von PyPI | Pakete nur mit Mindest- und Höchstversion, nicht auf Prüfsummen festgelegt | du PyPI und den Paket-Autoren |
| uv | offizieller Installer von astral.sh in der festen Version 0.12.21 | Der Starter prüft die SHA-256 der Installer-Datei gegen den Wert im Starter und führt sie sonst nicht aus. Der Installer lädt dann uv dieser Version von GitHub. | du astral.sh und GitHub |
| Python 3.12 für den Baustein | uv lädt es (python-build-standalone) | Version 3.12, kleinere Updates offen | du astral.sh |
| Docker Desktop | winget bzw. docker.com | neueste Version | du Docker Inc. und Microsoft (winget) |
| Claude Code | `claude.ai/install.ps1` bzw. `install.sh` | neueste Version | du Anthropic |
| Bausteine im Container | Docker Hub (`python:3.12-slim`, `node:22-slim`, `caddy:2.10-alpine`), PyPI (feste Versionen in `backend/requirements.txt`), npm (`web/package-lock.json`) | Basis-Abbilder nur über Tags, Pakete über feste Versionen bzw. Lock-Datei | du Docker Hub, PyPI, npm |

Eine neue uv-Version kommt nur mit einer neuen Version der Akte: Datei laden, Prüfsumme bilden, beide Werte in
`start/akte.ps1` und `start/akte.sh` eintragen. Den Installer startet der Starter ohne die Umgebungsvariablen, mit
denen man ihn auf eine andere Download-Quelle oder einen anderen Ordner umlenken könnte (`UV_DOWNLOAD_URL`,
`UV_INSTALLER_GITHUB_BASE_URL`, `UV_INSTALL_DIR` und verwandte). Auch seine Hinweise für den Handweg sagen: laden,
Prüfsumme vergleichen, erst dann ausführen, nie `irm … | iex` bzw. `curl … | sh`.

**Offen (später):** Der Baustein `akte-mcp` und seine Python-Pakete sind nicht auf Prüfsummen festgelegt. Geplant ist
ein fertig gebautes Paket als Release-Anhang mit veröffentlichter Prüfsumme und festen Abhängigkeiten
(`uv … --require-hashes`). Bis dahin vertraut man dem Tag und PyPI.

## Bekannte Grenzen (Stand 0.2)

* Der Browser bestätigt die Freigabe mit einer Zusammenfassung, rechnet die zu signierenden Bytes aber nicht selbst
  nach; er vertraut darin dem eigenen, lokalen Server. Weil die Nutzlast nur die Zusage trägt und das Salz erst mit
  der Offenlegung kommt, kann er auch nicht prüfen, dass die Zusage genau den angezeigten Inhalt bindet. Ein
  manipulierter Server könnte also etwas anderes unterschreiben lassen; spätestens die Offenlegung im Export würde
  dann nicht zum gezeigten Stand passen. Nachrechnen im Browser (kanonisches JSON, Zusage, Signing-Input) ist für
  eine spätere Version vorgesehen.
* Wer Zugang zur Datenbank oder zur Django-Verwaltung hat, kann einen Status ohne Unterschrift auf „freigegeben“
  setzen. Die Lese-Ansicht zeigt solche Objekte (es gibt keine Unterschrift, mit der sie nicht übereinstimmen), die
  Kette enthält für sie aber keine Freigabe. Werkzeuge und Agenten können das nicht.
* Ein verlorener Browser-Schlüssel lässt sich nur mit einem anderen eigenen Schlüssel widerrufen; der Browser legt
  dafür bei der nächsten Anmeldung einen neuen an.
* Der Trace eines Exports enthält alle Ereignisse, auch zu nicht öffentlichen Objekten: Zeitpunkt, Art und Schlüssel
  sind sichtbar, Inhalte nur als Zusage. Anders ließe sich die Kette nicht auf Lücken prüfen.
* Jedes neue Ereignis zwischen Vorbereiten und Unterschreiben lässt eine Freigabe neu anlaufen. Die Oberfläche
  wiederholt das von selbst; ein Werkzeug, das ständig sichert, kann Freigaben aber verzögern (Sichern und Anhänge
  sind je Konto gedrosselt).
* Ein Werkzeug kann beim Anlegen „öffentliche Person“ vorschlagen. Der volle Name erscheint erst, wenn ein Mensch die
  Karte mit dieser Angabe unterschreibt; der Dialog zeigt sie.
* In Mappen gelten für Bündel-Fäden die Prüfregeln des Boards, das man gerade ansieht, nicht die des Unter-Boards.
* Der Atlas-Prüfer im Browser kennt nur den nachsichtigen Modus; die strikte Kette prüft `akte pruefe-signaturen`.
* Ein Kartenbild mit fremder Adresse (`https://…`) lädt der Browser jedes Betrachters direkt vom fremden Server. Der
  sieht dabei IP-Adresse und Zeitpunkt. Nur die Bilder der Demo (`/static/akte/demo/`) liefert die Akte selbst aus.

## Sicherheitslücken melden

Bitte vertraulich über „Security → Report a vulnerability“ auf GitHub, nicht als öffentliches Issue.
