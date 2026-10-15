# SPDX-License-Identifier: MIT
"""Was die README zeigt. Alles stammt aus der erfundenen Demo „Freie Stadt Musterhafen“ (``manage.py akte_demo``).

Zwei eigene Boards tragen dieselben Demo-Karten, nur anders gelegt: ``readme-kopf`` für das Kopfbild (vier Karten,
alle drei Faden-Arten in einem Bild) und ``readme-karten`` für die Kartengalerie (jede Karte allein). Die Demo-Wand
bleibt, wie sie ist. Fahrten mit dem Titelanfang „README · “ legt ``erzeugen.py vorbereiten`` jedes Mal neu an.
"""

DEMO = "demo-musterhafen"
DEMO_FAHRT = "Wer wertet Musterhafens Daten aus?"
PRAEFIX = "README · "

ERIKA = "Erika Mustermann"
MAX = "Max Mustermann"
THEA = "Thea Beispiel"
SENAT = "Senat der Freien Stadt Musterhafen"
RECHNUNGSHOF = "Rechnungshof Musterhafen"
NORDLICHT = "Nordlicht Analytik GmbH"
KRANICH = "Kranich Holding AG"
MDAG = "Musterhafener Datengesetz (MDAG) § 4"
KAMERAS = "Verkehrskameras Musterhafen"

# Kartengalerie: jede Bild-Variante einmal, mit Beschriftung für die Tafel.
GALERIE = [
    (ERIKA, "KI-Foto", "Person, auf der Karte als KI-Bild gekennzeichnet"),
    (RECHNUNGSHOF, "KI-Foto", "erfundenes Gebäude"),
    (KAMERAS, "KI-Foto", "erfundene Anlage, in Farbe"),
    (SENAT, "Wappen", "gezeichnet, auf hellem Grund"),
    (KRANICH, "Logo", "gezeichnet, auf hellem Grund"),
    (THEA, "Initialen", "Privatperson: kein Foto, mit Absicht"),
    (MDAG, "Ohne Bild", "Gesetze haben kein Bildfeld"),
]

BUEHNEN = {
    "readme-kopf": {
        "titel": "README · Kopfbild (Demo)",
        # Eine Reihe im Zickzack: Erika ↔ Senat belegt, Erika ↔ Kameras Meinung, Kranich ↔ Kameras Verdacht.
        "karten": {ERIKA: (0, 220), SENAT: (420, 0), KAMERAS: (840, 220), KRANICH: (1260, 0)},
    },
    "readme-karten": {
        "titel": "README · Kartengalerie (Demo)",
        # Weit auseinander und versetzt: kein Faden läuft durch einen Ausschnitt.
        "karten": {name: (i * 1400, (i % 2) * 1400) for i, (name, _, _) in enumerate(GALERIE)},
    },
}

FAHRTEN = [
    {"board": "readme-kopf", "titel": PRAEFIX + "Kopf", "format": "16:9",
     "stationen": [{"fokus": [ERIKA, SENAT, KAMERAS, KRANICH], "stichwort": ""}]},
    {"board": "readme-karten", "titel": PRAEFIX + "Karten", "format": "16:9",
     "stationen": [{"fokus": [name], "stichwort": ""} for name, _, _ in GALERIE]},
]

KOPF = [ERIKA, SENAT, KAMERAS, KRANICH]

# Beleg in Großansicht: eine Quelle, deren Zitat die Akte gefunden und ausgeschnitten hat.
BELEG_QUELLE = "Drucksache 9/1234"

# Exakte Standbilder aus der Render-Ansicht. ``rahmen``: nach dem Standbild genau diese Karten einpassen (die
# Render-Kamera hält Titel mindestens 40 px hoch und schwenkt sonst); ``groesse``: Fenster in CSS-Pixeln;
# ``zeitpunkt``: „ankunft“ statt Mitte des Haltens (vor dem Einschweben eines Beweisstücks).
STANDBILDER = [
    {"name": "kopf-dunkel", "board": "readme-kopf", "fahrt": PRAEFIX + "Kopf", "format": "16x9", "look": "dunkel",
     "rahmen": KOPF, "groesse": (1920, 960)},
    {"name": "kopf-hell", "board": "readme-kopf", "fahrt": PRAEFIX + "Kopf", "format": "16x9", "look": "papier",
     "rahmen": KOPF, "groesse": (1920, 960)},
    {"name": "format-16x9", "board": DEMO, "fahrt": DEMO_FAHRT, "station": 1, "zeitpunkt": "ankunft",
     "format": "16x9", "look": "dunkel"},
    {"name": "format-9x16", "board": DEMO, "fahrt": DEMO_FAHRT, "station": 1, "zeitpunkt": "ankunft",
     "format": "9x16", "look": "dunkel"},
    {"name": "format-1x1", "board": DEMO, "fahrt": DEMO_FAHRT, "station": 1, "zeitpunkt": "ankunft",
     "format": "1x1", "look": "dunkel"},
]

# Live-Wand auf einer kleinen eigenen Bühne: Erika und der Senat liegen schon, rechts ist Platz. Ein Agent legt dort
# eine Karte und einen belegten Faden zum Senat an; das Werkzeug räumt danach alles wieder ab.
LIVE = {
    "board": "readme-live", "titel": "Freie Stadt Musterhafen (Demo)", "dauer_s": 15, "schritte_s": (2.0, 7.0),
    "karten": {ERIKA: (0, 200), SENAT: (440, 0)},
    "karte": {"name": "Bürgerschaft Musterhafen", "typ": "behoerde", "kurz": "Landesparlament", "x": 880, "y": 200},
    # Ausschnitt in Wandkoordinaten (x0, y0, x1, y1): alle drei Karten samt Platz für die Beschriftungen.
    "ausschnitt": (-60, -90, 1160, 680),
    "faden": {"nach": SENAT, "typ": "aussage", "text": "fragt nach der Datenauswertung", "start": "2024-02-01",
              "quelle": BELEG_QUELLE, "zitat": "Antwort des Senats auf die Kleine Anfrage zur Datenauswertung.",
              "fundstelle": "S. 1"},
}

# Terminal: Zitatprüfung erst an einem richtigen, dann am absichtlich falschen Zitat der Demo.
TERMINAL_ZITATE = [
    "Der Senat beauftragt die Nordlicht Analytik GmbH mit der Auswertung der Verkehrsdaten.",
    "Die Vergabe erfolgte ohne Ausschreibung.",
]

# Tafel „Faden-Arten“: Titel, Stil (Art, Strich, Breite, Farbe, Stempel) wie web/src/lib/akte/faden.ts, Erklärung.
FADEN_ARTEN = [
    ("Belegt", ("belegt", "none", 3, "#FF1744", ""),
     "Quelle und wörtliches Zitat. Nach der Unterschrift dürfen Leser ihn sehen."),
    ("Verdacht", ("verdacht", "10 8", 2.5, "#FF1744", "VERDACHT"),
     "Bei Personen meldet die Prüfung fehlende Anhörung und zweite Quelle. Gegen Privatpersonen sperrt sie."),
    ("Meinung", ("meinung", "2 6", 2.5, "#FFB300", "MEINUNG"),
     "Als Einschätzung gekennzeichnet, mit Tatsachengrundlage. Leser sehen Meinungen nur auf eigenen Zetteln."),
]

FORMATE_TEXT = [("16x9", "Langvideo"), ("9x16", "Shorts, Reels, TikTok"), ("1x1", "Beitrag im Feed")]

# Drei Kacheln: Titel, Rohbild, Bildbreite im Ausschnitt, Versatz links und oben (Pixel bei dieser Breite), Text.
KACHELN = [
    ("Die Wand", "kopf-dunkel", 1024, 24, 88, "Karten, Fäden, Rahmen. Ein Agent schreibt Entwürfe, du siehst sie live."),
    ("Der Beleg", "beleg", 760, 116, 100, "Zu jedem Faden die Quelle. Die Akte sucht das Zitat selbst in der Kopie."),
    ("Das Siegel", "siegel", 823, 337, 34, "Freigeben heißt unterschreiben. Das kann nur ein Mensch, im Browser."),
]

# Zeichen, die fertig im Repo liegen (werkzeuge/readme_bilder/marken/) und nur mit übernommen werden.
MARKEN = ["wortmarke-dunkel.svg", "wortmarke-hell.svg", "social-preview.png"]

# Fertige Medien in docs/bilder/readme/: Name → (größte Breite in px, Höchstgröße in KB).
MEDIEN = {
    "gesperrt.webp": (1660, 300),
    "kopf-dunkel.webp": (1660, 300), "kopf-hell.webp": (1660, 300),
    "kartengalerie.webp": (1660, 300),
    "faden-arten.webp": (1660, 300),
    "formate.webp": (1660, 300),
    "kacheln.webp": (1660, 300),
    "beleg.webp": (1660, 300),
    "regeln.webp": (1660, 300),
    "unterschrift.webp": (1660, 300),
    "leseansicht.webp": (1660, 300),
    "fahrt.webp": (1280, 8 * 1024), "fahrt-standbild.webp": (1280, 300),
    "live.webp": (1280, 3 * 1024), "live-standbild.webp": (1280, 300),
    "terminal.webp": (1280, 1536), "terminal-standbild.webp": (1280, 300),
}
PAARE = [("kopf-dunkel.webp", "kopf-hell.webp")]  # zusammen höchstens 500 KB
GESAMT_KB = 20 * 1024
