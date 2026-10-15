# Ultra-Akte 0.3.0 – was neu ist

Entwurf der Release-Notizen.

## Arbeiten an der Wand

* **Kartenbilder, die die Akte selbst mitbringt:** `bild_url` nimmt neben http(s)-Adressen auch Bilder unter
  `/static/akte/…` (webp, png, jpg, svg). Andere Pfade, Abfrageteile, `javascript:` und `data:` lehnt die Akte ab,
  ebenso `ftp://`, das kein Browser mehr anzeigt.
* **Demo mit Bildern und allen Faden-Arten:** „Freie Stadt Musterhafen“ hat jetzt 9 Karten und 9 Fäden. Dazu kommen
  KI-Fotos, die auf der Karte als KI-Bild gekennzeichnet sind, gezeichnete Logos und ein Wappen sowie eine
  Privatperson nur mit Initialen. Neu sind auch ein Verdacht, der Entwurf bleibt, und eine unterschriebene Meinung.
  Die Bilder liegen der Akte bei (CC0) und brauchen kein Internet.

## Sicherheit und Datenschutz

* Die öffentliche Lese-Schnittstelle (`/api/v1/akte/oeffentlich/…`) liefert zum Bild den Nachweis mit, also auch
  die KI-Kennzeichnung. Bilder, die die Akte selbst ausliefert, stehen dort als Pfad (`/static/akte/…`); wer die
  Schnittstelle von anderswo liest, setzt die Adresse der Akte davor.
* **Leckschutz für Bilder:** `werkzeuge/scrub/pruefen.py` liest PNG, GIF und WebP nach ihrem Aufbau. Geprüft werden
  Metadaten, jetzt auch gepackter Text, und jeder unbekannte Teil. Die Pixeldaten prüft er nicht mehr; dort trafen
  Regeln nur zufällig. Eine unsaubere Datei prüft er weiter ganz.
