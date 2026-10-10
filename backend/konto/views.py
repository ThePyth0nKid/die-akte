"""Anmeldung für die Web-Oberfläche: Benutzername oder E-Mail plus Passwort → JWT-Paar.

Die Web-Oberfläche legt die Tokens als httpOnly-Cookies ab (web/src/app/api/auth/*). Werkzeuge und der MCP-Server
benutzen stattdessen ein DRF-Token (``manage.py akte_token <konto>``).
"""

from __future__ import annotations

import hashlib

from django.contrib.auth import authenticate, get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


class Fehlversuche:
    """Fehlgeschlagene Anmeldungen je Konto UND Absender (Rate ``login_konto``).

    Nur je Absender sperrte hinter dem Web-Proxy alle zugleich aus; nur je Konto könnte jeder ein fremdes Konto
    aussperren. Gezählt werden nur Fehlversuche, nach dem Auflösen der E-Mail auf den Benutzernamen (sonst zählten
    Name und Adresse doppelt). Den Absender liefert DRF (``NUM_PROXIES`` = ``AKTE_VERTRAUTE_PROXYS``).
    """

    def __init__(self, request, view, benutzername: str):
        anzahl, dauer = SimpleRateThrottle.parse_rate(None, api_settings.DEFAULT_THROTTLE_RATES.get("login_konto"))
        self.grenze, self.dauer = anzahl, dauer
        ident = ScopedRateThrottle().get_ident(request)
        roh = f"{benutzername.casefold()}|{ident}".encode("utf-8")
        self.schluessel = "akte-login-fehl:" + hashlib.sha256(roh).hexdigest()[:32]

    def gesperrt(self) -> bool:
        return self.grenze is not None and int(cache.get(self.schluessel) or 0) >= self.grenze

    def zaehlen(self) -> None:
        if self.grenze is None:
            return
        if not cache.add(self.schluessel, 1, self.dauer):
            try:
                cache.incr(self.schluessel)
            except ValueError:  # gerade abgelaufen
                cache.add(self.schluessel, 1, self.dauer)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        daten = request.data if isinstance(request.data, dict) else {}
        login = str(daten.get("login") or "").strip()
        passwort = str(daten.get("password") or "")
        if not login or not passwort:
            return Response({"detail": "Login und Passwort sind nötig."}, status=status.HTTP_400_BAD_REQUEST)

        benutzername = login
        if "@" in login:
            konto = get_user_model().objects.filter(email__iexact=login).only("username").first()
            if konto:
                benutzername = konto.get_username()
        fehl = Fehlversuche(request, self, benutzername)
        if fehl.gesperrt():
            return Response({"detail": "Zu viele Fehlversuche. Bitte in einer Minute erneut."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        nutzer = authenticate(request, username=benutzername, password=passwort)
        if nutzer is None or not nutzer.is_active:
            fehl.zaehlen()
            return Response({"detail": "Anmeldung fehlgeschlagen."}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(nutzer)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})


class LogoutView(APIView):
    """Abmelden: Der Refresh-Token kommt auf die Sperrliste und gilt nie wieder (auch nicht aus einer Kopie)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        try:
            RefreshToken(str(request.data.get("refresh") or "")).blacklist()
        except TokenError:
            pass  # schon ungültig oder abgelaufen: Ziel erreicht
        return Response(status=status.HTTP_204_NO_CONTENT)
