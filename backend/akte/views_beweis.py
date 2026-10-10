"""API der Beweisschicht: Schlüssel, Freigabe mit Unterschrift, Export der Kette.

Schlüssel anmelden und Freigaben unterschreiben geht nur mit Passwort-Anmeldung (Mensch in der Oberfläche),
nie mit einem Werkzeug-Token. Den Export lesen Redaktion und, wenn die Akte öffentlich ist, auch Besucher; Besucher
bekommen die Offenlegung nur für Objekte, die öffentlich sichtbar sind.
"""

from __future__ import annotations

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from . import beweisschicht
from .beweisschicht import BeweisFehler
from .menschenrecht import per_werkzeug
from .models import Board, Entitaet, Ereignis, Schluessel, SchluesselRolle, Verbindung
from .permissions import ist_redaktion
from .pruefung import darf_oeffentlich


def _nur_mensch(request):
    if not ist_redaktion(request.user):
        return Response({"detail": "Nur die Redaktion."}, status=status.HTTP_403_FORBIDDEN)
    if per_werkzeug(request):
        return Response({"detail": "Unterschreiben und Schlüssel anmelden nur als Mensch in der Oberfläche, "
                                   "nicht mit einem Werkzeug-Token."}, status=status.HTTP_403_FORBIDDEN)
    return None


def _fehler(f: BeweisFehler) -> Response:
    return Response({"detail": str(f)}, status=f.status)


class _Mensch(APIView):
    authentication_classes = [JWTAuthentication, TokenAuthentication]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not getattr(settings, "AKTE_BEWEISSCHICHT", True):
            from rest_framework.exceptions import NotFound

            raise NotFound("Die Beweisschicht ist ausgeschaltet.")


class SchluesselView(_Mensch):
    def get(self, request):
        sperre = _nur_mensch(request)
        if sperre:
            return sperre
        eigene = Schluessel.objects.filter(nutzer=request.user, rolle=SchluesselRolle.MENSCH).order_by("-erstellt_am")
        return Response([{"kid": s.kid, "fingerabdruck": s.fingerabdruck, "erstellt_am": s.erstellt_am,
                          "widerrufen_am": s.widerrufen_am} for s in eigene])

    def post(self, request):
        sperre = _nur_mensch(request)
        if sperre:
            return sperre
        try:
            s = beweisschicht.schluessel_anmelden(request.user, str(request.data.get("oeffentlich", "")))
        except BeweisFehler as f:
            return _fehler(f)
        except ValueError as f:
            return Response({"detail": f"Schlüssel ungültig: {f}"}, status=400)
        return Response({"kid": s.kid, "fingerabdruck": s.fingerabdruck}, status=201)


def _objekt(art: str, pk: int):
    if art == "faden":
        return get_object_or_404(Verbindung.objects.select_related("von", "nach").prefetch_related(
            "belege__quelle__sicherungen", "ueberstimmungen"), pk=pk)
    if art == "karte":
        return get_object_or_404(Entitaet, pk=pk)
    raise BeweisFehler("objekt ist „karte“ oder „faden“.")


class FreigabeVorbereitenView(_Mensch):
    def post(self, request):
        sperre = _nur_mensch(request)
        if sperre:
            return sperre
        d = request.data
        try:
            art = str(d.get("objekt", ""))
            objekt = _objekt(art, int(d.get("id", 0)))
            ueber = d.get("ueberstimmungen") or {}
            if not isinstance(ueber, dict):
                raise BeweisFehler("ueberstimmungen ist ein Objekt {code: Begründung}.")
            return Response(beweisschicht.freigabe_vorbereiten(request.user, objekt, art, str(d.get("kid", "")),
                                                               {str(k): str(v) for k, v in ueber.items()}))
        except BeweisFehler as f:
            return _fehler(f)
        except (TypeError, ValueError):
            return Response({"detail": "objekt, id und kid angeben."}, status=400)


class FreigabeAbschliessenView(_Mensch):
    def post(self, request):
        sperre = _nur_mensch(request)
        if sperre:
            return sperre
        try:
            e = beweisschicht.freigabe_abschliessen(request.user, str(request.data.get("event_id", "")),
                                                    str(request.data.get("signatur", "")), _objekt)
        except BeweisFehler as f:
            return _fehler(f)
        except ValueError as f:
            return Response({"detail": f"Unterschrift unlesbar: {f}"}, status=400)
        return Response({"event_id": e.event_id, "event_hash": e.event_hash, "position": e.position}, status=201)


class ExportView(APIView):
    """Die ganze Kette mit Schlüsselbündel. Offenlegung: Redaktion alles, Besucher nur Öffentliches."""

    authentication_classes = [JWTAuthentication, TokenAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        if not getattr(settings, "AKTE_BEWEISSCHICHT", True):
            return Response({"detail": "Die Beweisschicht ist ausgeschaltet."}, status=404)
        if ist_redaktion(request.user):
            return Response(beweisschicht.export())
        if not getattr(settings, "AKTE_OEFFENTLICH_AKTIV", False):
            return Response({"detail": "Nicht öffentlich."}, status=403)
        return Response(beweisschicht.export(_oeffentlich_offenlegbar()))


def _oeffentlich_offenlegbar():
    """Welche Ereignisse Besucher offengelegt bekommen: Fäden und Karten, die öffentlich sichtbar sind, und die
    Sicherungen ihrer Quellen. Nie Inhalte mit dem vollen Namen einer Privatperson (die Zusage bleibt verdeckt)."""
    boards = list(Board.objects.filter(oeffentlich=True).prefetch_related("karten"))
    auf_board = {b.pk: {k.entitaet_id for k in b.karten.all()} for b in boards}
    faeden, karten, quellen = set(), set(), set()
    for e in Ereignis.objects.filter(typ="akte.freigabe").select_related("verbindung__von", "verbindung__nach",
                                                                          "entitaet"):
        if e.verbindung_id:
            v = e.verbindung
            if v.von.ist_privatperson or v.nach.ist_privatperson:
                continue
            if any(v.von_id in auf_board[b.pk] and v.nach_id in auf_board[b.pk] and darf_oeffentlich(v, b)
                   for b in boards):
                faeden.add(e.pk)
                quellen.update(v.belege.values_list("quelle_id", flat=True))
        elif e.entitaet_id and not e.entitaet.ist_privatperson:
            if any(e.entitaet_id in ids for ids in auf_board.values()):
                karten.add(e.pk)

    def offenlegen(e: Ereignis) -> bool:
        if e.pk in faeden or e.pk in karten:
            return True
        return e.typ == "akte.sicherung" and e.sicherung_id is not None and e.sicherung.quelle_id in quellen

    return offenlegen
