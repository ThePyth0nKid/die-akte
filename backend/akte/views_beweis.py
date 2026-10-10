"""API der Beweisschicht: Schlüssel, Freigabe und Widerruf mit Unterschrift, Export der Kette.

Schlüssel anmelden, Freigaben und Widerrufe unterschreiben geht nur mit Passwort-Anmeldung (Mensch in der
Oberfläche), nie mit einem Werkzeug-Token. Den Export lesen Redaktion und, wenn die Akte öffentlich ist, auch Besucher;
Besucher bekommen die Offenlegung nur für die jüngste Freigabe von Objekten, die öffentlich sichtbar sind, und für die
Sicherungen ihrer Quellen.
"""

from __future__ import annotations

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from . import beweisschicht, lesecache
from .beweisschicht import BeweisFehler, freigaben_prefetch, letzte_freigabe, veraendert_seit_freigabe
from .menschenrecht import per_werkzeug
from .models import Board, BoardKarte, Entitaet, Ereignis, Schluessel, SchluesselRolle, Status
from .permissions import ist_redaktion
from .pruefung import darf_oeffentlich, faeden_qs


def _nur_mensch(request):
    if not ist_redaktion(request.user):
        return Response({"detail": "Nur die Redaktion."}, status=status.HTTP_403_FORBIDDEN)
    if per_werkzeug(request):
        return Response({"detail": "Unterschreiben und Schlüssel anmelden nur als Mensch in der Oberfläche, "
                                   "nicht mit einem Werkzeug-Token."}, status=status.HTTP_403_FORBIDDEN)
    return None


def _fehler(f: BeweisFehler) -> Response:
    return Response({"detail": str(f), **f.daten}, status=f.status)


class _Mensch(APIView):
    authentication_classes = [JWTAuthentication, TokenAuthentication]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not getattr(settings, "AKTE_BEWEISSCHICHT", True):
            raise NotFound("Die Beweisschicht ist ausgeschaltet.")


class SchluesselView(_Mensch):
    def get(self, request):
        sperre = _nur_mensch(request)
        if sperre:
            return sperre
        eigene = Schluessel.objects.filter(nutzer=request.user, rolle=SchluesselRolle.MENSCH).order_by("-erstellt_am")
        return Response([{"kid": s.kid, "fingerabdruck": s.fingerabdruck, "oeffentlich": s.oeffentlich,
                          "erstellt_am": s.erstellt_am, "widerrufen_am": s.widerrufen_am} for s in eigene])

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
        return get_object_or_404(faeden_qs(), pk=pk)
    if art == "karte":
        return get_object_or_404(Entitaet.objects.prefetch_related(freigaben_prefetch()), pk=pk)
    raise BeweisFehler("objekt ist „karte“ oder „faden“.")


class FreigabeVorbereitenView(_Mensch):
    """``{"objekt": "faden"|"karte", "id": …, "kid": …, "ueberstimmungen": {code: Begründung}, "board": slug?}``.
    Mit ``board`` gelten dessen Prüfregeln (etwa eine strengere Stufe), sonst die allgemeinen."""

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
            board = get_object_or_404(Board, slug=str(d["board"])) if d.get("board") else None
            return Response(beweisschicht.freigabe_vorbereiten(
                request.user, objekt, art, str(d.get("kid", "")), {str(k): str(v) for k, v in ueber.items()}, board))
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


class WiderrufVorbereitenView(_Mensch):
    """``{"kid": <zu widerrufen>, "mit": <eigener gültiger Schlüssel, der unterschreibt>}``."""

    def post(self, request):
        sperre = _nur_mensch(request)
        if sperre:
            return sperre
        kid = str(request.data.get("kid", ""))
        try:
            return Response(beweisschicht.widerruf_vorbereiten(request.user, kid, str(request.data.get("mit") or kid)))
        except BeweisFehler as f:
            return _fehler(f)


class WiderrufAbschliessenView(_Mensch):
    def post(self, request):
        sperre = _nur_mensch(request)
        if sperre:
            return sperre
        try:
            e = beweisschicht.widerruf_abschliessen(request.user, str(request.data.get("event_id", "")),
                                                    str(request.data.get("signatur", "")))
        except BeweisFehler as f:
            return _fehler(f)
        except ValueError as f:
            return Response({"detail": f"Unterschrift unlesbar: {f}"}, status=400)
        return Response({"event_id": e.event_id, "event_hash": e.event_hash, "position": e.position}, status=201)


class ExportDrossel(AnonRateThrottle):
    """Besucher ohne Konto: Der Export ist teuer, wenn der Cache gerade ungültig ist."""

    scope = "akte_export"

    def get_rate(self):
        return self.THROTTLE_RATES.get(self.scope, "10/min")


class ExportView(APIView):
    """Die ganze Kette mit Schlüsselbündel. Offenlegung: Redaktion alles, Besucher nur Öffentliches (fünf Minuten im
    Cache, jede Änderung macht ihn ungültig).

    Der Trace enthält immer alle Ereignisse (Zeit, Art, Schlüssel), auch zu nicht öffentlichen Objekten: Nur die
    ganze Kette lässt sich auf Lücken prüfen. Inhalte stehen dort nur als Zusage."""

    authentication_classes = [JWTAuthentication, TokenAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [ExportDrossel]

    def get(self, request):
        if not getattr(settings, "AKTE_BEWEISSCHICHT", True):
            return Response({"detail": "Die Beweisschicht ist ausgeschaltet."}, status=404)
        if ist_redaktion(request.user):
            return Response(beweisschicht.export())
        if not getattr(settings, "AKTE_OEFFENTLICH_AKTIV", False):
            return Response({"detail": "Nicht öffentlich."}, status=403)
        return Response(lesecache.holen("beweis:export", set(),
                                        lambda: beweisschicht.export(_oeffentlich_offenlegbar())))


def _oeffentlich_offenlegbar():
    """Welche Ereignisse Besucher offengelegt bekommen.

    Je Objekt nur die jüngste Freigabe (frühere Fassungen, etwa vor einer Korrektur, bleiben verdeckt), und nur für
    Fäden und Karten, die auf einem öffentlichen Board sichtbar sind: freigegeben, unverändert, Faden besteht die
    Prüfung des Boards und ist dort nicht ausgeblendet. Dazu die Sicherungen ihrer Quellen. Nie Inhalte mit dem
    vollen Namen einer Privatperson (deren Zusage bleibt verdeckt).
    """
    boards = list(Board.objects.filter(oeffentlich=True).prefetch_related("ausgeblendete_verbindungen"))
    auf_board: dict[int, set[int]] = {b.pk: set() for b in boards}
    for board_id, entitaet_id in BoardKarte.objects.filter(board__in=boards).values_list("board_id", "entitaet_id"):
        auf_board[board_id].add(entitaet_id)
    alle = set().union(*auf_board.values()) if auf_board else set()
    offen: set[int] = set()
    quellen: set[int] = set()

    karten = Entitaet.objects.filter(pk__in=alle, status=Status.FREIGEGEBEN).prefetch_related(freigaben_prefetch())
    for e in karten:
        if e.ist_privatperson or veraendert_seit_freigabe(e, "karte"):
            continue
        letzte = letzte_freigabe(e)
        if letzte is not None:
            offen.add(letzte.pk)

    faeden = faeden_qs().filter(status=Status.FREIGEGEBEN, von_id__in=alle, nach_id__in=alle)
    for v in faeden:
        if v.von.ist_privatperson or v.nach.ist_privatperson:
            continue
        sichtbar = any(
            v.von_id in auf_board[b.pk] and v.nach_id in auf_board[b.pk]
            and v.pk not in {x.pk for x in b.ausgeblendete_verbindungen.all()} and darf_oeffentlich(v, b)
            for b in boards
        )
        letzte = letzte_freigabe(v) if sichtbar else None
        if letzte is not None:
            offen.add(letzte.pk)
            quellen.update(b.quelle_id for b in v.belege.all())

    offen.update(Ereignis.objects.filter(typ="akte.sicherung", sicherung__quelle_id__in=quellen)
                 .exclude(sicherung__art="video_lokal")  # ältere Ketten: lokaler Pfad, vom Server nie gesehen
                 .values_list("pk", flat=True))
    return lambda ereignis: ereignis.pk in offen

