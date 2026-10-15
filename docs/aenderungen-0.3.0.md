# Ultra-Akte 0.3.0 – was neu ist

Entwurf der Release-Notizen.

## Neuer Name: Ultra-Akte

* **Die Akte heißt jetzt Ultra-Akte.** Sie gehört zu IGOULTRA und soll neben Recherchen auch Figuren, Welten und
  Bücher tragen. Das Repo heißt `ThePyth0nKid/ultra-akte`; GitHub leitet alte Adressen mit `die-akte` weiter.
* **Neues Zeichen:** ein Dienstsiegel, ein Achteck mit der Umschrift ULTRA und AKTE, innen das A mit dem roten Faden
  als Querstrich. Für 16 bis 48 px gibt es eine kleine Fassung ohne Umschrift; sie ist jetzt auch das Symbol der App
  im Browser-Tab, hell oder dunkel passend zum System.
* **Was bleibt:** der Befehl `akte`, der Ordner `Akte`, die Starter `START-AKTE`, `STOP-AKTE` und
  `AGENT-VERBINDEN`, der Eintrag `akte` bei Claude, das Docker-Projekt `die-akte` mit seinem Daten-Volume und die
  Schlüssel im Browser. Deine Daten und Unterschriften bleiben gültig.
* **Sichtbar neu:** Titel im Browser, Überschriften, Anmeldung und Einrichtung, die Banner der Starter, Meldungen,
  die den Namen nennen, und die Kennung beim Abruf von Quellen (`Ultra-Akte/0.3`). Der MCP-Server meldet sich als
  `ultra-akte`.

## Arbeiten an der Wand

* **Kartenbilder, die die Akte selbst mitbringt:** `bild_url` nimmt neben http(s)-Adressen auch Bilder unter
  `/static/akte/…` (webp, png, jpg, svg). Andere Pfade, Abfrageteile, `javascript:` und `data:` lehnt die Akte ab,
  ebenso `ftp://`, das kein Browser mehr anzeigt.
* **Demo mit Bildern und allen Faden-Arten:** „Freie Stadt Musterhafen“ hat jetzt 9 Karten und 9 Fäden. Dazu kommen
  KI-Fotos, die auf der Karte als KI-Bild gekennzeichnet sind, gezeichnete Logos und ein Wappen sowie eine
  Privatperson nur mit Initialen. Neu sind auch ein Verdacht, der Entwurf bleibt, und eine unterschriebene Meinung.
  Die Bilder liegen der Akte bei (CC0) und brauchen kein Internet.

## README

* **Die README zeigt die Akte in Bildern:** Wand, Fäden, Beleg, Regeln, Leser-Ansicht, Live-Ansicht, Terminal und
  Unterschrift, dazu eine Kamerafahrt. Alle Bilder entstehen aus der Demo mit `werkzeuge/readme_bilder/erzeugen.py`
  und lassen sich auf einer frischen Akte neu erzeugen.

## Sicherheit und Datenschutz

* Die öffentliche Lese-Schnittstelle (`/api/v1/akte/oeffentlich/…`) liefert zum Bild den Nachweis mit, also auch
  die KI-Kennzeichnung. Bilder, die die Akte selbst ausliefert, stehen dort als Pfad (`/static/akte/…`); wer die
  Schnittstelle von anderswo liest, setzt die Adresse der Akte davor.
* **Leckschutz für Bilder:** `werkzeuge/scrub/pruefen.py` liest PNG, GIF und WebP nach ihrem Aufbau. Geprüft werden
  Metadaten, jetzt auch gepackter Text, und jeder unbekannte Teil. Die Pixeldaten prüft er nicht mehr; dort trafen
  Regeln nur zufällig. Eine unsaubere Datei prüft er weiter ganz.

## Wer von 0.2 kommt

Schritte: [betrieb.md, „Neue Version 0.3.0“](betrieb.md#neue-version-030-von-02). Das Wichtigste:

1. **Titel:** In einer alten `.env` steht `AKTE_TITEL=Die Akte`. Auf `Ultra-Akte` setzen oder die Zeile löschen.
2. **Alte Links** auf `github.com/ThePyth0nKid/die-akte` leitet GitHub weiter, auch die Adressen der Release-ZIPs.
3. **Prüfsummen:** Eine ZIP von v0.2.0, die nach der Umbenennung geladen wird, hat einen anderen Ordnernamen
   (`ultra-akte-0.2.0`) und damit eine andere SHA-256-Prüfsumme als die bei v0.2.0 veröffentlichte.
4. **Anleitung von v0.2.0:** Schritt 2 dort kopiert den Ordner `die-akte-*` aus der ZIP und findet ihn nach der
   Umbenennung nicht mehr. Die Anleitung von 0.3.0 nimmt `ultra-akte-*` ebenso wie `die-akte-*`.

## Release-Ablauf

Wie bei 0.2.0 ([Checkliste](aenderungen-0.2.0.md#release-ablauf-checkliste)), mit `/v0.3.0`. Danach darf
`git grep -n -e "/v0\.2\.0" -- ":!docs/aenderungen-0.2.0.md"` nichts mehr finden. Neu dazu:

1. **Repo umbenennen, bevor der Branch nach `main` geht,** und das Actions-Secret `OSS_SCRUB_SPERRLISTE_INHALT`
   mit der aktuellen Sperrliste füllen. `IST_ORIGINAL` in `leckschutz.yml` erkennt beide Namen.
2. **Archiv prüfen:** Der Ordner in der ZIP heißt `ultra-akte-0.3.0`. Schritt 2 der Agentenanleitung damit einmal
   durchspielen.
3. **Vorschaubild:** `werkzeuge/readme_bilder/marken/social-preview.png` unter Settings → Social preview hochladen.
4. **Weiterleitung prüfen:** `https://github.com/ThePyth0nKid/die-akte/archive/refs/tags/v0.2.0.zip` muss auf
   `ultra-akte` umleiten. Den alten Namen `die-akte` nie neu anlegen: Ein neues Repo unter dem Namen beendet die
   Weiterleitung, und die Anleitungen von 0.2 würden Code von dort laden.

## Prüfsumme der Release-ZIP

Beim Veröffentlichen eintragen:

| Datei | SHA-256 | Commit |
|---|---|---|
