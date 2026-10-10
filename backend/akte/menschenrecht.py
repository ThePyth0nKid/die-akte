"""Was nur ein Mensch darf.

Werkzeuge und Agenten (Anmeldung mit DRF-Token, z. B. über die CLI oder den MCP-Server) arbeiten der Redaktion zu:
Sie legen Entwürfe an und ändern Entwürfe. Freigeben, Freigegebenes ändern oder löschen und ein Board öffentlich
schalten bleibt dem Menschen in der Oberfläche vorbehalten (Anmeldung mit Passwort, JWT im Cookie).

Grund: Die Akte macht Aussagen über Personen. Die Maschine darf schnell recherchieren und vorschlagen, entscheiden
und veröffentlichen tut ein Mensch, der dafür geradesteht.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import APIException, PermissionDenied

from .models import Status


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


def nach_aenderung(objekt) -> bool:
    """Nach dem Speichern: Weicht ein freigegebenes Objekt vom unterschriebenen Inhalt ab, ist es wieder Entwurf.
    Gibt True zurück, wenn der Status zurückgesetzt wurde."""
    from .beweisschicht import veraendert_seit_freigabe
    from .models import Entitaet, Verbindung

    art = "faden" if isinstance(objekt, Verbindung) else "karte" if isinstance(objekt, Entitaet) else ""
    if art and getattr(objekt, "status", None) == Status.FREIGEGEBEN and veraendert_seit_freigabe(objekt, art):
        type(objekt).objects.filter(pk=objekt.pk).update(status=Status.ENTWURF)
        objekt.status = Status.ENTWURF
        return True
    return False


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
    gewuenscht = _status_von(daten)
    if gewuenscht is not None and gewuenscht != getattr(instanz, "status", gewuenscht):
        raise PermissionDenied("Den Status ändert nur ein Mensch in der Oberfläche.")
    if daten.get("oeffentlich") and not getattr(instanz, "oeffentlich", False):
        raise PermissionDenied("Ein Board öffentlich schalten darf nur ein Mensch in der Oberfläche.")


def pruefe_loeschen(request, instanz) -> None:
    if per_werkzeug(request) and getattr(instanz, "status", None) == Status.FREIGEGEBEN:
        raise Konflikt("Freigegebenes löscht nur ein Mensch in der Oberfläche.")


def _hat_status(modell) -> bool:
    return any(f.name == "status" for f in modell._meta.get_fields())
