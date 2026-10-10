"""Mappen — ein Board als Aktenmappe auf einem anderen Board.

Eine große Hauptwand, auf der eine Karte ein ganzes anderes Board enthält; man klickt sich hinein und
wieder hinaus. Mappen dürfen ineinander liegen, aber keinen Kreis bilden.

Reine Rechnung ohne Datenbank (wie ``layout.py``), damit Werkstatt, Mitglieder-Ansicht und Tests
dasselbe Ergebnis bekommen. Die Views laden die Zeilen und rufen diese Funktionen auf.

Begriffe:
- **direkt**: Entitäten, die als Karte auf der Wand selbst liegen.
- **Inhalt einer Mappe**: alle Entitäten ihres Ziel-Boards und aller Boards darin (rekursiv).
- **Bündel**: Fäden zwischen einer Karte und einer Mappe oder zwischen zwei Mappen, als ein Strang.
  Ein Faden gehört zu genau einem Bündel oder zu keinem:
  1. beide Enden direkt → gewöhnlicher Faden (zeichnet ``wand_daten`` wie immer),
  2. ein Ende direkt, das andere nur in Mappen → Bündel Karte ↔ Mappe; bevorzugt die Mappe, in der
     der Faden selbst liegt (beide Enden drin), sonst die spezifischste Mappe des anderen Endes,
  3. kein Ende direkt: liegen beide in einer gemeinsamen Mappe, ist der Faden intern (dort zu sehen),
     sonst Bündel zwischen den spezifischsten Mappen beider Enden.
- **Gelenk**: eine Entität, die nicht direkt liegt, aber in mindestens zwei verschiedenen Boards
  unter dieser Wand steckt. Genau das sind die Schlüsselfiguren; die Werkstatt schlägt vor, sie auf
  die Wand zu holen — erst dann werden ihre Querverbindungen als Bündel sichtbar.

Bewusst keine Geldsumme im Bündel: Sie würde Währungen und Jahre mischen, Ketten doppelt zählen und
einen Geldfluss zwischen Themen behaupten, den kein einzelner Beleg trägt (Belegregel 1).
"""

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

MAX_TIEFE = 12
GESICHTER = 4
VORSCHAU_KARTEN = 400


def teilbaum(start: int, kinder: dict[int, list[int]], erlaubt: set[int] | None = None,
             max_tiefe: int = MAX_TIEFE) -> set[int]:
    """Alle Boards in ``start``, ``start`` eingeschlossen. Zyklenfest; betritt nur erlaubte Boards."""
    if erlaubt is not None and start not in erlaubt:
        return set()
    gesehen = {start}
    schlange = deque([(start, 0)])
    while schlange:
        board, tiefe = schlange.popleft()
        if tiefe >= max_tiefe:
            continue
        for kind in kinder.get(board, ()):
            if kind in gesehen or (erlaubt is not None and kind not in erlaubt):
                continue
            gesehen.add(kind)
            schlange.append((kind, tiefe + 1))
    return gesehen


def wuerde_zyklus(eltern: int, ziel: int, kinder: dict[int, list[int]]) -> bool:
    """Legt man ``ziel`` als Mappe auf ``eltern``, entstünde dann ein Kreis?

    Ohne Tiefengrenze (die BFS ist über ``gesehen`` zyklenfest): sonst ließe sich über eine Kette mit
    mehr als ``MAX_TIEFE`` Ebenen ein Kreis anlegen. Die Anzeige kappt weiter bei ``MAX_TIEFE``."""
    return eltern == ziel or eltern in teilbaum(ziel, kinder, max_tiefe=len(kinder) + 1)


def kinder_aus(kanten) -> dict[int, list[int]]:
    """``[(eltern, ziel), …]`` → ``{eltern: [ziel, …]}``."""
    kinder: dict[int, list[int]] = defaultdict(list)
    for eltern, ziel in kanten:
        kinder[eltern].append(ziel)
    return kinder


@dataclass
class Lage:
    #: Entität → Karten-ID auf dieser Wand
    direkt: dict[int, int]
    #: Mappen-ID → Board-IDs (Ziel und alles darin)
    boards: dict[int, set[int]]
    #: Mappen-ID → Entitäten darin (rekursiv)
    inhalt: dict[int, set[int]]
    #: Entität → Mappen-IDs, in denen sie steckt
    in_mappen: dict[int, set[int]] = field(default_factory=dict)
    gelenke: list[int] = field(default_factory=list)

    def spezifischste(self, mappen) -> int:
        """Die kleinste Mappe (wenigste Entitäten), bei Gleichstand die ältere."""
        return min(mappen, key=lambda m: (len(self.inhalt[m]), m))

    def auf_der_wand(self) -> set[int]:
        alle = set(self.direkt)
        for s in self.inhalt.values():
            alle |= s
        return alle


def lage_rechnen(direkt: dict[int, int], mappen: list[tuple[int, int]], kinder: dict[int, list[int]],
                 karten_je_board: dict[int, set[int]], erlaubt: set[int] | None = None) -> Lage:
    """``mappen``: ``[(mappe_id, ziel_board_id)]`` dieser Wand. ``erlaubt``: nur diese Boards betreten."""
    boards, inhalt = {}, {}
    for mappe_id, ziel in mappen:
        boards[mappe_id] = teilbaum(ziel, kinder, erlaubt)
        s: set[int] = set()
        for b in boards[mappe_id]:
            s |= karten_je_board.get(b, set())
        inhalt[mappe_id] = s
    in_mappen: dict[int, set[int]] = defaultdict(set)
    for m, s in inhalt.items():
        for e in s:
            in_mappen[e].add(m)
    lage = Lage(direkt=dict(direkt), boards=boards, inhalt=inhalt, in_mappen=dict(in_mappen))

    unter = set().union(*boards.values()) if boards else set()
    halter: dict[int, set[int]] = defaultdict(set)
    for b in unter:
        for e in karten_je_board.get(b, ()):
            halter[e].add(b)
    lage.gelenke = sorted(e for e, hs in halter.items() if e not in direkt and len(hs) >= 2)
    return lage


@dataclass
class Buendel:
    #: Knoten-Schlüssel der Enden: ("k", karten_id) oder ("m", mappen_id)
    a: tuple[str, int]
    b: tuple[str, int]
    faeden: list[int] = field(default_factory=list)
    je_art: Counter = field(default_factory=Counter)
    je_typ: Counter = field(default_factory=Counter)
    mit_betrag: int = 0
    #: Werkstatt: auf der Elternwand ausgeblendete Fäden zwischen denselben Enden (zum Wiedereinblenden)
    versteckt: list[int] = field(default_factory=list)


def _ende(lage: Lage, e: int, bevorzugt: set[int] | None = None) -> tuple[str, int] | None:
    if e in lage.direkt:
        return ("k", lage.direkt[e])
    mappen = lage.in_mappen.get(e)
    if not mappen:
        return None
    wahl = (bevorzugt & mappen) if bevorzugt else set()
    return ("m", lage.spezifischste(wahl or mappen))


def buendel_rechnen(lage: Lage, faeden) -> list[Buendel]:
    """``faeden``: Zeilen ``(id, von, nach, typ, aussageart, hat_betrag)``. Ergebnis sortiert, stabil."""
    je_paar: dict[tuple, Buendel] = {}
    for fid, von, nach, typ, art, hat_betrag in faeden:
        von_direkt, nach_direkt = von in lage.direkt, nach in lage.direkt
        if von_direkt and nach_direkt:
            continue
        gemeinsam = lage.in_mappen.get(von, set()) & lage.in_mappen.get(nach, set())
        if not von_direkt and not nach_direkt:
            if gemeinsam:
                continue  # liegt ganz in einer Mappe und ist dort zu sehen
            a, b = _ende(lage, von), _ende(lage, nach)
        else:
            a, b = _ende(lage, von, gemeinsam), _ende(lage, nach, gemeinsam)
        if a is None or b is None or a == b:
            continue
        schluessel = tuple(sorted((a, b)))
        bu = je_paar.get(schluessel)
        if bu is None:
            bu = je_paar[schluessel] = Buendel(a=schluessel[0], b=schluessel[1])
        bu.faeden.append(fid)
        bu.je_art[art] += 1
        bu.je_typ[typ] += 1
        bu.mit_betrag += 1 if hat_betrag else 0
    for bu in je_paar.values():
        bu.faeden.sort()
    return [je_paar[k] for k in sorted(je_paar)]


def zaehler(lage: Lage, faeden, quellen_je_faden: dict[int, set[int]]) -> dict[int, dict]:
    """Je Mappe: Karten, Fäden (beide Enden drin) und verschiedene Quellen dieser Fäden."""
    ergebnis = {}
    for m, s in lage.inhalt.items():
        drin = [fid for fid, von, nach, *_ in faeden if von in s and nach in s]
        quellen: set[int] = set()
        for fid in drin:
            quellen |= quellen_je_faden.get(fid, set())
        ergebnis[m] = {"karten": len(s), "faeden": len(drin), "quellen": len(quellen)}
    return ergebnis


def gesichter(lage: Lage, faeden, mit_bild: set[int], anzahl: int = GESICHTER) -> dict[int, list[int]]:
    """Je Mappe die meistverbundenen Entitäten mit Bild (Privatpersonen hat der Aufrufer schon entfernt)."""
    ergebnis = {}
    for m, s in lage.inhalt.items():
        grad: Counter = Counter()
        for _fid, von, nach, *_ in faeden:
            if von in s and nach in s:
                grad[von] += 1
                grad[nach] += 1
        kandidaten = sorted((e for e in s if e in mit_bild), key=lambda e: (-grad[e], e))
        ergebnis[m] = kandidaten[:anzahl]
    return ergebnis


def vorschau(karten: list[tuple[float, float]], rahmen: list[tuple[float, float, float, float, str]],
             karte_b: float = 220, karte_h: float = 380) -> dict:
    """Die Miniatur des Unter-Boards: Rahmen und Kartenpunkte auf 0..1 gerechnet (Seitenverhältnis bleibt)."""
    xs = [x for x, _ in karten] + [r[0] for r in rahmen]
    ys = [y for _, y in karten] + [r[1] for r in rahmen]
    xe = [x + karte_b for x, _ in karten] + [r[0] + r[2] for r in rahmen]
    ye = [y + karte_h for _, y in karten] + [r[1] + r[3] for r in rahmen]
    if not xs:
        return {"seitenverhaeltnis": 1.0, "rahmen": [], "karten": []}
    x0, y0, x1, y1 = min(xs), min(ys), max(xe), max(ye)
    b, h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)

    def nx(v):
        return round((v - x0) / b, 4)

    def ny(v):
        return round((v - y0) / h, 4)

    schritt = max(1, len(karten) // VORSCHAU_KARTEN + (1 if len(karten) % VORSCHAU_KARTEN else 0))
    return {
        "seitenverhaeltnis": round(b / h, 4),
        "rahmen": [[nx(x), ny(y), round(rb / b, 4), round(rh / h, 4), farbe] for x, y, rb, rh, farbe in rahmen],
        "karten": [[nx(x), ny(y)] for x, y in karten[::schritt]],
    }
