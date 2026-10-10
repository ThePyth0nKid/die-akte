"""Kamerafahrten aus einer Beschreibung — Claude nennt Karten, der Server rechnet das Bild.

Eine Station sagt „zeig Mustermann und Nordlicht“; daraus wird der Mittelpunkt des
Rechtecks um diese Karten und ein Zoom, bei dem das Rechteck mit Rand ins
Aufnahmeformat passt. So muss niemand Koordinaten raten.
"""

from dataclasses import dataclass

from .layout import KARTE_B, KARTE_H

#: Sichere Bildfläche je Aufnahmeformat in Pixeln (Rand für Plattform-Oberfläche und Texte).
#: Dieselben Werte stehen in apps/web/src/lib/akte/aufnahme.ts; die gerenderte Aufnahme rahmt dort
#: je Format neu aus den Fokus-Karten, der Server liefert das Bild für die Live-Fahrt.
FORMATE = {
    "16:9": (1920 - 192, 1080 - 108),
    "9:16": (1080 - 108, 1920 - 308),
    "1:1": (1080 - 108, 1080 - 108),
    "oben": (1080 - 108, 960 - 88),
}
#: Schreibweisen der Dateinamen und der CLI.
ALIASSE = {"16x9": "16:9", "9x16": "9:16", "1x1": "1:1"}
ZOOM_MIN, ZOOM_MAX = 0.08, 2.4
#: Anteil der sicheren Fläche, den die Fokus-Karten füllen.
FUELLUNG = 0.84
#: Zuschlag je Seite für gedrehte Karten und die Nadel.
ZUSCHLAG = 14


def format_name(format_: str) -> str | None:
    """``16x9`` → ``16:9``; unbekannte Formate → None."""
    name = ALIASSE.get(format_, format_)
    return name if name in FORMATE else None


@dataclass(frozen=True)
class Bild:
    x: float
    y: float
    zoom: float


def bild_fuer(rechtecke: list[tuple[float, float, float, float]], format_: str = "16:9", zoom: float | None = None) -> Bild:
    """Mittelpunkt und Zoom, sodass die Rechtecke ``(x, y, b, h)`` die sichere Fläche zu 84 % füllen."""
    if not rechtecke:
        raise ValueError("bild_fuer braucht mindestens ein Rechteck")
    breite, hoehe = FORMATE[format_name(format_) or "16:9"]
    x0 = min(r[0] for r in rechtecke) - ZUSCHLAG
    y0 = min(r[1] for r in rechtecke) - ZUSCHLAG
    x1 = max(r[0] + r[2] for r in rechtecke) + ZUSCHLAG
    y1 = max(r[1] + r[3] for r in rechtecke) + ZUSCHLAG
    passend = FUELLUNG * min(breite / (x1 - x0), hoehe / (y1 - y0))
    z = zoom if zoom else max(ZOOM_MIN, min(ZOOM_MAX, passend))
    return Bild(x=(x0 + x1) / 2, y=(y0 + y1) / 2, zoom=round(z, 3))


#: Karten ohne Bild sind deutlich niedriger als der Platz, den das Raster für sie hält
#: (gemessen im Browser am 24.09.: 92–155 px je nach Kurzbeschreibung).
KARTE_OHNE_BILD_H = 160


def karten_rechteck(x: float, y: float, mit_bild: bool = True) -> tuple[float, float, float, float]:
    """Das Rechteck, das die Karte wirklich bedeckt — die Kamera rahmt den Inhalt, nicht die Rasterzelle."""
    return (x, y, KARTE_B, KARTE_H if mit_bild else KARTE_OHNE_BILD_H)
