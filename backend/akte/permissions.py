"""Wer an der Akte arbeiten darf.

Stufe 1: nur die Redaktion (Superuser oder Gruppe ``akte_redaktion``). Eine eigene
Gruppe statt eines neuen Feldes am Nutzer, damit die App keine Migration im
``users``-Modell braucht und parallele Zweige sich nicht stören.
"""

import logging

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

REDAKTION_GRUPPE = "akte_redaktion"


def ist_redaktion(user) -> bool:
    if not (user and user.is_authenticated):
        return False
    return user.is_superuser or user.groups.filter(name=REDAKTION_GRUPPE).exists()


def redaktionskonten():
    """Alle aktiven Konten, die an der Akte arbeiten dürfen (Redaktionsgruppe oder Superuser), nach Namen.

    Eine Wahrheit für die Einrichtung (``redaktion_eingerichtet``), ``akte_konten`` und ``akte_token`` ohne Namen
    (die Starter fragen darüber, welches Konto der Agent bekommt)."""
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    return (get_user_model().objects.filter(Q(is_superuser=True) | Q(groups__name=REDAKTION_GRUPPE), is_active=True)
            .distinct().order_by("username"))


def redaktion_eingerichtet() -> bool:
    """Gibt es schon ein aktives Konto, das an der Akte arbeiten darf (Redaktionsgruppe oder Superuser)?

    Solange nicht, ist die Einrichtung des ersten Kontos offen (``konto.views.EinrichtungView``,
    ``akte_einrichten --falls-keins``). Superuser zählen mit: Sie dürfen dasselbe wie die Redaktion.
    """
    return redaktionskonten().exists()


def mitglieder_boards() -> set[str]:
    """Slugs der Boards, die jedes eingeloggte Konto lesen darf (``AKTE_MITGLIEDER_BOARDS``).

    Leer = aus. Der Schalter ist eine Umgebungsvariable, damit die Lese-Ansicht ohne neuen
    Build zugeht. Wer Konten ohne Einladung zulässt, muss „Mitglied“ rechtlich wie
    öffentlich behandeln.
    """
    roh = getattr(settings, "AKTE_MITGLIEDER_BOARDS", "") or ""
    return {s.strip() for s in roh.split(",") if s.strip()}


def oeffentliche_boards() -> set[str]:
    """Slugs der Boards, die jeder ohne Konto lesen darf: ``Board.oeffentlich`` UND der Schalter
    ``AKTE_OEFFENTLICH_AKTIV`` (Umgebungsvariable, leer = zu).

    Sie bekommen dieselbe Lese-Ansicht wie Mitglieder (``wand_fuer_mitglieder``), nicht die
    strenge Einzelfreigabe der ``OeffentlicheWandView``: Besucher sollen alles sehen, was belegt
    ist, aber nichts bearbeiten.
    """
    if not getattr(settings, "AKTE_OEFFENTLICH_AKTIV", False):
        return set()
    from .models import Board  # hier, sonst zieht permissions beim Import die Modelle

    return set(Board.objects.filter(oeffentlich=True).values_list("slug", flat=True))


def lese_boards(user) -> set[str]:
    """Was ein Konto ohne Redaktionsrecht lesen darf: öffentliche Boards, eingeloggt dazu die Mitglieder-Boards."""
    offen = oeffentliche_boards()
    if user and user.is_authenticated:
        return offen | mitglieder_boards()
    return offen


class IstRedaktion(BasePermission):
    message = "Die Akte ist bisher nur für die Redaktion offen."

    def has_permission(self, request, view):
        return ist_redaktion(request.user)


class LesenMitgliedSonstRedaktion(BasePermission):
    """Lesen für jedes eingeloggte Konto (und ohne Konto, solange die öffentliche Akte an ist),
    alles andere nur die Redaktion.

    Welche Boards jemand sieht und welche Felder er bekommt, entscheidet die View
    (``lese_boards()`` und ``wand_fuer_mitglieder``). Nur an den zwei Board-Endpunkten.
    """

    message = IstRedaktion.message

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            if request.user and request.user.is_authenticated:
                return True
            return bool(getattr(settings, "AKTE_OEFFENTLICH_AKTIV", False))
        return ist_redaktion(request.user)


class MitgliedLesenThrottle(UserRateThrottle):
    """Deckel nur für Mitglieder; die Redaktion (und ihre Werkzeuge) bleibt ungebremst.

    Kein zusätzlicher Deckel je IP: Die Web-Oberfläche ruft über den Next.js-Proxy ab, der die
    Besucher-IP nicht weitergibt; ein IP-Deckel träfe alle Mitglieder gemeinsam. Restrisiko:
    viele neue Konten (GitHub/Discord ohne Einladung) umgehen den Deckel je Konto.
    """

    scope = "akte_mitglied"

    def get_rate(self):
        # Fällt auf einen festen Wert zurück, wenn die Rate fehlt (die Test-Settings leeren alle Raten).
        return self.THROTTLE_RATES.get(self.scope, "300/hour")

    def allow_request(self, request, view):
        # Besucher ohne Konto zählt ``AkteOeffentlichThrottle`` (je IP), nicht dieser Deckel.
        if ist_redaktion(request.user) or not request.user.is_authenticated:
            return True
        return super().allow_request(request, view)


class AkteOeffentlichThrottle(AnonRateThrottle):
    """Deckel je IP für Besucher ohne Konto. Die Web-Seite ruft dafür direkt bei der API ab
    (nicht über den Next.js-Proxy), sonst teilten sich alle Besucher eine IP.

    Großzügig, weil Mobilfunknetze viele Menschen hinter einer IP bündeln (CGNAT). Die Last
    fängt der Cache der Lese-Ansicht ab, nicht der Deckel.
    """

    scope = "akte_oeffentlich"

    def get_rate(self):
        return self.THROTTLE_RATES.get(self.scope, "120/min")

    def get_ident(self, request):
        """Die echte Besucher-IP. Kopfzeilen schreibt jeder Besucher mit; ihnen wird nur so weit geglaubt, wie die
        Einstellungen es sagen, sonst hätte ein Angreifer je Anfrage einen frischen Deckel.

        * ``AKTE_CLIENT_IP_HEADER`` (z. B. ``CF-Connecting-IP``): nur setzen, wenn ein vorgeschalteter Dienst genau
          diesen Kopf selbst schreibt und Fremdwerte überschreibt.
        * ``AKTE_VERTRAUTE_PROXYS`` (Zahl, Standard 0): so viele eigene Proxys hängen sich an X-Forwarded-For an; die
          IP davor zählt. Bei 0 zählt nur die Verbindungsadresse.
        """
        kopf = getattr(settings, "AKTE_CLIENT_IP_HEADER", "")
        if kopf:
            wert = request.META.get("HTTP_" + kopf.upper().replace("-", "_"), "").strip()
            if wert:
                return wert
        proxys = int(getattr(settings, "AKTE_VERTRAUTE_PROXYS", 0) or 0)
        kette = [teil.strip() for teil in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if teil.strip()]
        if proxys > 0 and len(kette) >= proxys:
            return kette[-proxys]
        return request.META.get("REMOTE_ADDR", "")

    def allow_request(self, request, view):
        if request.user and request.user.is_authenticated:
            return True
        try:
            return super().allow_request(request, view)
        except Exception:  # noqa: BLE001 — Redis weg: lieber ohne Deckel lesen als die Akte mit 500 abschalten
            logging.getLogger(__name__).warning("Akte: Drossel ohne Cache, lasse durch", exc_info=True)
            return True

