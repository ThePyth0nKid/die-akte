"""Was nur ein Mensch darf.

Werkzeuge und Agenten (Anmeldung mit DRF-Token, z. B. über die CLI oder den MCP-Server) arbeiten der Redaktion zu:
Sie legen Entwürfe an und ändern Entwürfe. Dem Menschen in der Oberfläche (Anmeldung mit Passwort, JWT im Cookie)
bleibt vorbehalten:

* freigeben, Freigegebenes ändern oder löschen, Quellen freigegebener Fäden ändern,
* ein Board öffentlich schalten, ein veröffentlichtes Board ändern (Karten, Zettel, Rahmen, Mappen), Boards löschen,
* eine Person als öffentliche Person kennzeichnen (sonst erscheint sie nur mit Initialen),
* Meinungs-Zettel schreiben (sie sind in der Lese-Ansicht sichtbar).

Grund: Die Akte macht Aussagen über Personen. Die Maschine darf schnell recherchieren und vorschlagen, entscheiden
und veröffentlichen tut ein Mensch, der dafür geradesteht.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Q
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import APIException, PermissionDenied

from .models import Status, ZettelArt


class Konflikt(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Freigegebenes ändert nur ein Mensch in der Oberfläche."
    default_code = "freigegeben"


def per_werkzeug(request) -> bool:
    """Angemeldet mit einem Werkzeug-Token (CLI, MCP) statt mit Passwort in der Oberfläche?"""
    return isinstance(getattr(request, "auth", None), Token)


def _status_von(daten: dict) -> str | None:
    wert = daten.get("status")
    return str(wert) if wert is not None else None


def _mit_unterschrift() -> bool:
    return bool(getattr(settings, "AKTE_BEWEISSCHICHT", True) and getattr(settings, "AKTE_SIGNIERTE_FREIGABE", True))


UNTERSCHRIFT = ("Freigeben heißt unterschreiben: in der Oberfläche „Freigeben“ wählen "
                "(API: /api/v1/akte/beweis/freigabe/vorbereiten/ und /abschliessen/).")


def pruefe_anlegen(request, modell, daten: dict) -> dict:
    """Vor dem Anlegen: Werkzeuge legen nur Entwürfe an und schalten nichts öffentlich."""
    if not per_werkzeug(request):
        if _mit_unterschrift() and _status_von(daten) == Status.FREIGEGEBEN:
            raise Konflikt(UNTERSCHRIFT)
        return {}
    gewuenscht = _status_von(daten)
    if gewuenscht not in (None, Status.ENTWURF):
        raise PermissionDenied("Werkzeuge legen nur Entwürfe an. Freigeben tut ein Mensch in der Oberfläche.")
    if daten.get("oeffentlich"):
        raise PermissionDenied("Ein Board öffentlich schalten darf nur ein Mensch in der Oberfläche.")
    if daten.get("regeln"):
        raise PermissionDenied("Die Prüfregeln eines Boards ändert nur ein Mensch in der Oberfläche.")
    return {"status": Status.ENTWURF} if _hat_status(modell) else {}


def nach_aenderung(objekt) -> list:
    """Nach dem Speichern: Weicht ein freigegebenes Objekt vom unterschriebenen Inhalt ab, ist es wieder Entwurf.

    Das gilt auch für Fäden, die davon abhängen: Eine umbenannte Karte oder eine geänderte Quelle ändert, was mit
    den Fäden unterschrieben wurde. Gibt die zurückgesetzten Objekte zurück.
    """
    from . import lesecache
    from .beweisschicht import veraendert_seit_freigabe
    from .models import Entitaet, Quelle, Verbindung
    from .pruefung import faeden_qs

    zurueck = []
    art = "faden" if isinstance(objekt, Verbindung) else "karte" if isinstance(objekt, Entitaet) else ""
    if art and getattr(objekt, "status", None) == Status.FREIGEGEBEN and veraendert_seit_freigabe(objekt, art):
        zurueck.append(objekt)
    abhaengig = Verbindung.objects.none()
    if isinstance(objekt, Entitaet):
        abhaengig = faeden_qs().filter(Q(von=objekt) | Q(nach=objekt), status=Status.FREIGEGEBEN)
    elif isinstance(objekt, Quelle):
        abhaengig = faeden_qs().filter(status=Status.FREIGEGEBEN, belege__quelle=objekt).distinct()
    zurueck += [v for v in abhaengig if veraendert_seit_freigabe(v, "faden")]
    for o in zurueck:
        type(o).objects.filter(pk=o.pk).update(status=Status.ENTWURF)
        o.status = Status.ENTWURF
    if zurueck:
        lesecache.veraltet()
    return zurueck


def pruefe_aendern(request, instanz, daten: dict) -> None:
    """Vor dem Ändern: Freigegebenes bleibt für Werkzeuge gesperrt, der Status ist Menschensache, und auch ein
    Mensch gibt nur mit Unterschrift frei."""
    if not per_werkzeug(request):
        if (_mit_unterschrift() and _status_von(daten) == Status.FREIGEGEBEN
                and getattr(instanz, "status", None) != Status.FREIGEGEBEN):
            raise Konflikt(UNTERSCHRIFT)
        return
    if "regeln" in daten:
        raise PermissionDenied("Die Prüfregeln eines Boards ändert nur ein Mensch in der Oberfläche.")
    if getattr(instanz, "status", None) == Status.FREIGEGEBEN:
        raise Konflikt()
    if _belegt_freigegebenes(instanz):
        raise Konflikt("Diese Quelle belegt einen freigegebenen Faden. Ändern nur ein Mensch in der Oberfläche.")
    if daten.get("oeffentliche_person") and not getattr(instanz, "oeffentliche_person", True):
        raise PermissionDenied("Ob jemand eine öffentliche Person ist, entscheidet ein Mensch in der Oberfläche.")
    gewuenscht = _status_von(daten)
    if gewuenscht is not None and gewuenscht != getattr(instanz, "status", gewuenscht):
        raise PermissionDenied("Den Status ändert nur ein Mensch in der Oberfläche.")
    if daten.get("oeffentlich") and not getattr(instanz, "oeffentlich", False):
        raise PermissionDenied("Ein Board öffentlich schalten darf nur ein Mensch in der Oberfläche.")


def pruefe_loeschen(request, instanz) -> None:
    from .models import Board

    if not per_werkzeug(request):
        return
    if isinstance(instanz, Board):
        raise PermissionDenied("Boards löscht nur ein Mensch in der Oberfläche.")
    if getattr(instanz, "status", None) == Status.FREIGEGEBEN or _belegt_freigegebenes(instanz):
        raise Konflikt("Freigegebenes löscht nur ein Mensch in der Oberfläche.")


def _belegt_freigegebenes(instanz) -> bool:
    from .models import Quelle, Verbindung

    return isinstance(instanz, Quelle) and Verbindung.objects.filter(
        belege__quelle=instanz, status=Status.FREIGEGEBEN).exists()


def veroeffentlicht(board) -> bool:
    """Sieht jemand außerhalb der Redaktion dieses Board (öffentlich oder Mitglieder-Board)?"""
    from .permissions import mitglieder_boards

    return bool(board.oeffentlich) or board.slug in mitglieder_boards()


def pruefe_board_werkzeug(request, slug: str) -> None:
    """Werkzeuge ändern kein veröffentlichtes Board: was dort liegt, entscheidet ein Mensch."""
    if not per_werkzeug(request):
        return
    from .models import Board

    board = Board.objects.filter(slug=slug).only("slug", "oeffentlich").first()
    if board is not None and veroeffentlicht(board):
        raise PermissionDenied("Ein veröffentlichtes Board ändert nur ein Mensch in der Oberfläche. Werkzeuge "
                               "arbeiten auf einem Arbeits-Board; Fahrten und Anordnung sind erlaubt.")


def pruefe_zettel(request, *arten: str) -> None:
    """Meinungs-Zettel stehen in der Lese-Ansicht. Schreiben, ändern und löschen nur ein Mensch."""
    if per_werkzeug(request) and ZettelArt.MEINUNG in arten:
        raise PermissionDenied("Meinungs-Zettel schreibt nur ein Mensch. Werkzeuge legen Notizen oder Fragen an.")


def _hat_status(modell) -> bool:
    return any(f.name == "status" for f in modell._meta.get_fields())
