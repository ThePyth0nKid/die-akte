"""Aufräumen — die Wand ordnet sich, ohne dass etwas etwas anderes verdeckt.

Reine Rechnung ohne Datenbank, damit sie testbar ist und UI-Knopf und Claude
dasselbe Ergebnis bekommen:

1. Jede Karte und jeder Zettel gehört zu dem Rahmen, in dem ihr Mittelpunkt liegt.
   Was in keinem Rahmen liegt, bildet einen eigenen Block ohne Rahmen.
2. Innerhalb eines Blocks sortiert eine Baryzentrum-Runde verbundene Karten
   nebeneinander, dann kommen sie in ein festes Raster. Zwischen den Reihen bleibt
   Luft für die Beschriftung der Fäden.
3. Die Blöcke liegen in Regalreihen nebeneinander, in der Reihenfolge, in der sie
   vorher auf der Wand lagen (oben vor unten, links vor rechts). Rahmen wachsen mit.
"""

from dataclasses import dataclass, field
from math import ceil, sqrt

KARTE_B, KARTE_H = 220, 380
ZETTEL_B, ZETTEL_H = 200, 200
BEWEIS_B, BEWEIS_H = 220, 300
ABSTAND_X, ABSTAND_Y = 120, 150
MAPPE_B, MAPPE_H = 2 * KARTE_B + ABSTAND_X, KARTE_H  # eine Aktenmappe belegt zwei Rasterzellen
MAPPEN_REGAL = 6  # so viele Mappen stehen in einem reinen Mappen-Rahmen nebeneinander
RAHMEN_RAND = 70
RAHMEN_KOPF = 160  # Platz für den Titel, der beim Herauszoomen mitwächst
BLOCK_ABSTAND = 220
REGAL_BREITE = 5200  # Mindestbreite; große Wände werden breiter (Seitenverhältnis REGAL_FORMAT)
REGAL_FORMAT = 16 / 9


@dataclass
class Teil:
    art: str  # "karte" | "zettel" | "beweis" | "mappe"
    id: int
    x: float
    y: float
    entitaet: int | None = None

    @property
    def breite(self):
        return {"karte": KARTE_B, "zettel": ZETTEL_B, "beweis": BEWEIS_B, "mappe": MAPPE_B}[self.art]

    @property
    def hoehe(self):
        return {"karte": KARTE_H, "zettel": ZETTEL_H, "beweis": BEWEIS_H, "mappe": MAPPE_H}[self.art]


@dataclass
class RahmenBox:
    id: int
    x: float
    y: float
    breite: float
    hoehe: float

    def enthaelt(self, t: Teil) -> bool:
        mx, my = t.x + t.breite / 2, t.y + t.hoehe / 2
        return self.x <= mx <= self.x + self.breite and self.y <= my <= self.y + self.hoehe


@dataclass
class Block:
    rahmen: RahmenBox | None
    teile: list[Teil] = field(default_factory=list)

    def ursprung(self):
        if self.rahmen:
            return (self.rahmen.y, self.rahmen.x)
        return (min(t.y for t in self.teile), min(t.x for t in self.teile))


def _reihenfolge(karten: list[Teil], kanten: list[tuple[int, int]]) -> list[Teil]:
    """Verbundene Karten nebeneinander: Grad zuerst, dann drei Baryzentrum-Runden."""
    im_block = {k.entitaet for k in karten}
    nachbarn: dict[int, list[int]] = {k.entitaet: [] for k in karten}
    for a, b in kanten:
        if a in im_block and b in im_block:
            nachbarn[a].append(b)
            nachbarn[b].append(a)
    folge = sorted(karten, key=lambda k: (-len(nachbarn[k.entitaet]), k.y, k.x, k.id))
    for _ in range(3):
        platz = {k.entitaet: i for i, k in enumerate(folge)}
        def schwerpunkt(k):
            n = nachbarn[k.entitaet]
            return sum(platz[m] for m in n) / len(n) if n else platz[k.entitaet]
        folge = sorted(folge, key=lambda k: (schwerpunkt(k), platz[k.entitaet]))
    return folge


def _zellen(folge: list[Teil], spalten: int) -> list[tuple[Teil, int, int]]:
    """Rasterplätze ``(teil, zeile, spalte)``; eine Mappe braucht zwei freie Zellen in derselben Zeile."""
    platz, ergebnis = 0, []
    for t in folge:
        breit = 2 if t.art == "mappe" else 1
        if platz % spalten + breit > spalten:
            platz += spalten - platz % spalten
        zeile, spalte = divmod(platz, spalten)
        ergebnis.append((t, zeile, spalte))
        platz += breit
    return ergebnis


def aufraeumen(teile: list[Teil], rahmen: list[RahmenBox], kanten: list[tuple[int, int]]):
    """Neue Positionen: ``({(art, id): (x, y)}, {rahmen_id: (x, y, breite, hoehe)})``."""
    bloecke = [Block(r) for r in sorted(rahmen, key=lambda r: (r.y, r.x))]
    frei = Block(None)
    for t in teile:
        ziel = next((b for b in bloecke if b.rahmen.enthaelt(t)), None)
        (ziel or frei).teile.append(t)
    if frei.teile:
        bloecke.append(frei)
    bloecke = [b for b in bloecke if b.teile or b.rahmen]
    bloecke.sort(key=lambda b: b.ursprung() if b.teile or b.rahmen else (0, 0))

    zell_b = KARTE_B + ABSTAND_X
    zell_h = KARTE_H + ABSTAND_Y
    positionen: dict[tuple[str, int], tuple[float, float]] = {}
    neue_rahmen: dict[int, tuple[float, float, float, float]] = {}

    plan: list[tuple[Block, list[tuple[Teil, int, int]], int, int, int, int, int]] = []
    for block in bloecke:
        mappen = sorted((t for t in block.teile if t.art == "mappe"), key=lambda t: (t.y, t.x, t.id))
        karten = _reihenfolge([t for t in block.teile if t.art == "karte"], kanten)
        zettel = sorted((t for t in block.teile if t.art == "zettel"), key=lambda t: (t.y, t.x, t.id))
        beweise = sorted((t for t in block.teile if t.art == "beweis"), key=lambda t: (t.y, t.x, t.id))
        # Mappen zuerst: sie belegen je zwei Zellen nebeneinander.
        folge = mappen + karten + beweise + zettel
        n = max(len(folge) + len(mappen), 1)
        spalten = max(2 if mappen else 1, ceil(sqrt(n * 1.6)))
        if mappen and len(mappen) == len(folge) and len(mappen) <= MAPPEN_REGAL:
            spalten = 2 * len(mappen)  # nur Mappen: ein Aktenregal in einer Reihe
        zellen = _zellen(folge, spalten)
        zeilen = max((z for _, z, _ in zellen), default=0) + 1
        rand = RAHMEN_RAND if block.rahmen else 0
        kopf = RAHMEN_KOPF if block.rahmen else 0
        block_b = spalten * zell_b - ABSTAND_X + 2 * rand
        block_h = zeilen * zell_h - ABSTAND_Y + 2 * rand + kopf
        plan.append((block, zellen, spalten, rand, kopf, block_b, block_h))

    # Viele Rahmen in 5200 Breite ergeben eine hohe Säule, die im Überblick winzig wird.
    # Das Regal wächst deshalb mit der Fläche der Wand in Richtung Querformat.
    flaeche = sum((b + BLOCK_ABSTAND) * (h + BLOCK_ABSTAND) for *_, b, h in plan)
    regal = max(REGAL_BREITE, sqrt(flaeche * REGAL_FORMAT), max((b for *_, b, _ in plan), default=0))

    cursor_x, cursor_y, reihen_hoehe = 0.0, 0.0, 0.0
    for block, zellen, spalten, rand, kopf, block_b, block_h in plan:
        if cursor_x > 0 and cursor_x + block_b > regal:
            cursor_x, cursor_y, reihen_hoehe = 0.0, cursor_y + reihen_hoehe + BLOCK_ABSTAND, 0.0

        start_x, start_y = cursor_x + rand, cursor_y + rand + kopf
        for t, zeile, spalte in zellen:
            # Zettel sitzen mittig in ihrer Zelle, damit ihre Nadel in der Kartenreihe liegt.
            dx = (KARTE_B - t.breite) / 2 if t.art != "mappe" else 0
            positionen[(t.art, t.id)] = (start_x + spalte * zell_b + dx, start_y + zeile * zell_h)
        if block.rahmen:
            neue_rahmen[block.rahmen.id] = (cursor_x, cursor_y, block_b, block_h)

        cursor_x += block_b + BLOCK_ABSTAND
        reihen_hoehe = max(reihen_hoehe, block_h)

    return positionen, neue_rahmen


def ueberlappungen(rechtecke: list[tuple[float, float, float, float]]) -> list[tuple[int, int]]:
    """Paare sich überlappender Rechtecke ``(x, y, b, h)`` — für Tests und die Prüfung nach dem Ziehen."""
    paare = []
    for i, (ax, ay, ab, ah) in enumerate(rechtecke):
        for j in range(i + 1, len(rechtecke)):
            bx, by, bb, bh = rechtecke[j]
            if ax < bx + bb and bx < ax + ab and ay < by + bh and by < ay + ah:
                paare.append((i, j))
    return paare
