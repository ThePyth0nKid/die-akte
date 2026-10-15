# Bilder der README

Jedes Bild und jede Animation der README entsteht hier aus der erfundenen Demo „Freie Stadt Musterhafen“. Nichts
davon zeigt echte Menschen: Die Fotos der Demo-Karten sind KI-Bilder und auf jeder Karte so gekennzeichnet, Logos
und Wappen sind eigene Zeichnungen.

## Voraussetzungen

* eine laufende Akte mit Demo (`manage.py akte_demo --neu --oeffentlich`) und ein Konto der Redaktion
* Python mit Playwright und Pillow; Chromium von Playwright (`python -m playwright install chromium`, falls noch
  nicht da)
* ffmpeg mit `libwebp_anim` für die Animationen
* für `terminal`: ein Python mit dem Paket aus `mcp/` samt `[beweis]` (über `AKTE_PYTHON`) und für `--atlas` die
  Abhängigkeiten in `beweis/kreuzpruefung` (`npm ci`)

```
AKTE_WEB=http://127.0.0.1:8080  AKTE_WEB_LOGIN=…  AKTE_WEB_PASSWORT=…  AKTE_TOKEN=…  AKTE_PYTHON=…
```

Konto, Passwort und Token gehören nie ins Repo. Am besten eine eigene Akte nur für die Bilder: `docker compose -p
akte-readme …` mit eigenem Port, dann bleibt deine Akte unberührt.

## Ablauf

```
python werkzeuge/readme_bilder/erzeugen.py standbilder     # Bühnen anlegen, Standbilder, Karten, Oberfläche
python werkzeuge/readme_bilder/erzeugen.py fahrt           # Kamerafahrt der Demo, 12 Bilder je Sekunde
python werkzeuge/readme_bilder/erzeugen.py terminal        # echte Ausgaben von akte pruefe-signaturen und zitat-pruefen
python werkzeuge/readme_bilder/erzeugen.py live            # ein Agent legt Karte und Faden an, die Wand zeigt es live
python werkzeuge/readme_bilder/erzeugen.py kompositionen   # Tafeln: Kartengalerie, Faden-Arten, Formate, Kacheln
python werkzeuge/readme_bilder/erzeugen.py kodieren        # WebP mit Größengrenzen, ohne Metadaten
python werkzeuge/readme_bilder/erzeugen.py pruefen         # README: Links, Anker, Alt-Texte, Größen
python werkzeuge/readme_bilder/erzeugen.py uebernehmen     # nach docs/bilder/readme/
```

Was gezeigt wird, steht in `szenen.py`. Zwei Dinge macht das Werkzeug anders als die App:

* **Eigene Bühnen.** Für Kopfbild, Kartengalerie und Live-Wand legt es eigene Boards mit denselben Demo-Karten an
  und entfernt sie danach wieder. Die Demo-Wand bleibt, wie sie ist.
* **Eigener Ausschnitt.** Die Render-Kamera hält Titel mindestens 40 px hoch und schwenkt sonst. Für das Kopfbild
  und die Live-Wand setzt das Werkzeug den Ausschnitt selbst (CSS-Transformation der Wand).

Für den Unterschrift-Dialog wählt es „Freigeben (unterschreiben)“ und bricht ab. Das Speichern des Fadens davor
fängt es im Browser ab, alle anderen Schreibzugriffe bricht es ab. Erlaubt sind nur zwei: Der Browser meldet seinen
Schlüssel für das Konto an und bereitet die Freigabe vor; daraus entstehen die Angaben im Dialog. Karten, Fäden und
Belege der Demo bleiben unverändert.

## Vor dem Übernehmen

Der Leck-Prüfer liest Metadaten, aber keine Pixel. Sieh dir jedes Bild selbst an: keine Pfade, keine echten Namen,
keine Gesichter echter Menschen. Erst dann `uebernehmen` und in einem Commit einchecken.

Die Zeichen in `marken/` sind fertige Dateien: das Dienstsiegel allein (`zeichen-*`), die kleine Fassung ohne
Umschrift für 16 bis 48 px (`zeichen-klein-*`), Siegel mit Wortmarke für den README-Kopf (`wortmarke-*`) und das
Vorschaubild für geteilte Links. `dunkel` heißt helle Tinte für dunklen Grund, `hell` dunkle Tinte für hellen Grund.
Schriftzüge sind Pfade, damit sie ohne Webschrift gleich aussehen, und Aussparungen sind echte Löcher, damit das
Siegel auf jedem Grund steht. `social-preview.png` lädt man unter Settings → Social preview hoch.
