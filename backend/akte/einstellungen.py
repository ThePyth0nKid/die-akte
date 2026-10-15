"""Einstellungen für die ganze Akte (eine Zeile in ``Einstellungen``), heute: archive.org ja oder nein.

Wirksam ist der gespeicherte Wert; solange niemand entschieden hat, gilt ``settings.AKTE_ARCHIV_AKTIV`` (Standard aus).
Ändern darf nur ein Mensch in der Oberfläche (``views.EinstellungenView``, beim ersten Konto ``konto.views``):
archive.org macht jede Quell-URL öffentlich, das entscheidet kein Werkzeug.

Die Prüfung fragt den Wert je Faden ab (Regel ``quelle_ohne_archiv``). Damit eine Wand mit vielen Fäden nicht eine
Abfrage je Faden kostet, merkt sich ``JeAnfrage`` (Middleware) den gespeicherten Wert für die Dauer einer Anfrage.
Außerhalb einer Anfrage (Hintergrund-Thread, Befehle) wird jedes Mal gelesen.
"""

from __future__ import annotations

import contextvars
import logging

from django.conf import settings
from django.db import DatabaseError, transaction

from .models import Einstellungen

logger = logging.getLogger(__name__)

_NICHT_GELESEN = object()
#: Gespeicherter Wert (None = nicht entschieden) für die laufende Anfrage; ``None`` außerhalb einer Anfrage.
_je_anfrage: contextvars.ContextVar[dict | None] = contextvars.ContextVar("akte_einstellungen", default=None)


def _gespeichert():
    merker = _je_anfrage.get()
    if merker is not None and merker.get("archiv_org", _NICHT_GELESEN) is not _NICHT_GELESEN:
        return merker["archiv_org"]
    try:
        # Eigener Sicherungspunkt: scheitert das Lesen (Postgres), bleibt die umgebende Transaktion benutzbar.
        with transaction.atomic():
            wert = Einstellungen.objects.filter(pk=1).values_list("archiv_org", flat=True).first()
    except DatabaseError:
        logger.warning("Akte: Einstellungen nicht lesbar, archive.org nach AKTE_ARCHIV_AKTIV", exc_info=True)
        return None
    if merker is not None:
        merker["archiv_org"] = wert
    return wert


def archiv_org_aktiv() -> bool:
    """Geht eine neue Sicherung zusätzlich an archive.org? Bei einem Datenbankfehler gilt die Einstellung aus .env."""
    gespeichert = _gespeichert()
    if gespeichert is None:
        return bool(getattr(settings, "AKTE_ARCHIV_AKTIV", False))
    return bool(gespeichert)


def archiv_org_setzen(wert: bool, nutzer=None) -> Einstellungen:
    """Entscheidung eines Menschen speichern (in der Transaktion des Aufrufers).

    Erst nach dem Commit: Lese-Cache und Stand erneuern (die Prüfung hängt daran, ``quelle_ohne_archiv``) und, wenn
    archive.org gerade eingeschaltet wurde, ältere Quellen ohne Archivkopie im Hintergrund nachsichern."""
    from . import lesecache

    vorher = archiv_org_aktiv()
    einst, _ = Einstellungen.objects.get_or_create(pk=1)
    einst.archiv_org = bool(wert)
    einst.geaendert_von = nutzer if nutzer is not None and getattr(nutzer, "is_authenticated", False) else None
    einst.save()
    merker = _je_anfrage.get()
    if merker is not None:
        merker["archiv_org"] = einst.archiv_org
    transaction.on_commit(lesecache.veraltet)
    if einst.archiv_org and not vorher:
        transaction.on_commit(_archiv_nachholen)
    return einst


def _archiv_nachholen() -> None:
    from .sicherung import archiv_nachholen_alle

    try:
        anzahl = archiv_nachholen_alle()
        if anzahl:
            logger.info("Akte: archive.org eingeschaltet, %s ältere Quellen werden nachgesichert", anzahl)
    except Exception:  # noqa: BLE001 — das Umschalten selbst ist gespeichert; Nachholen ist ein Zusatz
        logger.exception("Akte: Nachholen nach dem Einschalten von archive.org gescheitert")


def als_dict() -> dict:
    return {"archiv_org": archiv_org_aktiv()}


class JeAnfrage:
    """Middleware: Einstellungen höchstens einmal je Anfrage lesen (siehe Moduldoku)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        marke = _je_anfrage.set({})
        try:
            return self.get_response(request)
        finally:
            _je_anfrage.reset(marke)
