"""Anmeldung für die Web-Oberfläche: Benutzername oder E-Mail plus Passwort → JWT-Paar.

Die Web-Oberfläche legt die Tokens als httpOnly-Cookies ab (web/src/app/api/auth/*). Werkzeuge und der MCP-Server
benutzen stattdessen ein DRF-Token (``manage.py akte_token <konto>``).
"""

from __future__ import annotations

import hashlib

from django.contrib.auth import authenticate, get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


class KontoDrossel(SimpleRateThrottle):
    """Fehlversuche je Konto, nicht je Absender: Hinter dem Web-Proxy kommen alle Anmeldungen vom selben Absender.
    Eine Drossel nur je Absender sperrte alle aus, sobald einer rät; diese sperrt nur das geratene Konto."""

    scope = "login_konto"

    def get_cache_key(self, request, view):
        login = str(request.data.get("login") or "").strip().casefold()
        if not login:
            return None
        return self.cache_format % {"scope": self.scope,
                                    "ident": hashlib.sha256(login.encode("utf-8")).hexdigest()[:32]}


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle, KontoDrossel]
    throttle_scope = "login"

    def post(self, request):
        login = str(request.data.get("login") or "").strip()
        passwort = str(request.data.get("password") or "")
        if not login or not passwort:
            return Response({"detail": "Login und Passwort sind nötig."}, status=status.HTTP_400_BAD_REQUEST)

        benutzername = login
        if "@" in login:
            konto = get_user_model().objects.filter(email__iexact=login).only("username").first()
            if konto:
                benutzername = konto.get_username()
        nutzer = authenticate(request, username=benutzername, password=passwort)
        if nutzer is None or not nutzer.is_active:
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
