"""Weg finden — wie hängt X mit Y zusammen?

Breitensuche über alle Fäden, richtungslos: „Mustermann gründete Nordlicht“ verbindet
beide Karten in beide Richtungen. Die Akte bleibt klein (Hunderte, nicht Millionen
Fäden), deshalb liegt der Graph einmal im Speicher; eine rekursive SQL-Abfrage
lohnt sich erst, wenn das nicht mehr stimmt.
"""

from collections import deque

from .models import Verbindung


def finde_weg(von_id: int, nach_id: int, max_tiefe: int = 4, aussagearten=None, queryset=None):
    """Kürzester Weg als ``(entitaet_ids, verbindung_ids)`` oder ``None``.

    ``aussagearten`` schränkt auf z. B. nur belegte Fäden ein; ``queryset`` erlaubt
    der öffentlichen Ansicht, vorher alles Unveröffentlichbare herauszunehmen.
    """
    if von_id == nach_id:
        return [von_id], []

    faeden = queryset if queryset is not None else Verbindung.objects.all()
    if aussagearten:
        faeden = faeden.filter(aussageart__in=aussagearten)

    nachbarn: dict[int, list[tuple[int, int]]] = {}
    for v_id, a, b in faeden.values_list("id", "von_id", "nach_id"):
        nachbarn.setdefault(a, []).append((b, v_id))
        nachbarn.setdefault(b, []).append((a, v_id))

    herkunft: dict[int, tuple[int, int] | None] = {von_id: None}
    schlange = deque([(von_id, 0)])
    while schlange:
        knoten, tiefe = schlange.popleft()
        if tiefe >= max_tiefe:
            continue
        for nachbar, v_id in nachbarn.get(knoten, ()):
            if nachbar in herkunft:
                continue
            herkunft[nachbar] = (knoten, v_id)
            if nachbar == nach_id:
                return _zurueck(herkunft, nach_id)
            schlange.append((nachbar, tiefe + 1))
    return None


def _zurueck(herkunft, ziel):
    knoten_ids, faden_ids = [ziel], []
    schritt = herkunft[ziel]
    while schritt is not None:
        vorher, v_id = schritt
        knoten_ids.append(vorher)
        faden_ids.append(v_id)
        schritt = herkunft[vorher]
    return list(reversed(knoten_ids)), list(reversed(faden_ids))
