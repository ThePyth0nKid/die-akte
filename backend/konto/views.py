"""Anmeldung für die Web-Oberfläche: Benutzername oder E-Mail plus Passwort → JWT-Paar.

Die Web-Oberfläche legt die Tokens als httpOnly-Cookies ab (web/src/app/api/auth/*). Werkzeuge und der MCP-Server
benutzen stattdessen ein DRF-Token (``manage.py akte_token <konto>``).

Dazu das erste Konto im Browser (``EinrichtungView``): nur solange es kein Redaktionskonto gibt und nur mit dem
Einrichtungscode aus ``.env``. Ein Agent kann (und soll) kein verdecktes Passwort ins Terminal tippen; der Mensch legt
sein Konto selbst im Browser an.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


logger = logging.getLogger(__name__)


def _absender(request) -> str:
    """Absender für Fehlversuch-Zähler. IPv6 zählt je /64: ein Anschluss bekommt meist ein ganzes /64-Netz und
    könnte sonst je Versuch eine neue Adresse nehmen."""
    ident = ScopedRateThrottle().get_ident(request)
    try:
        adresse = ipaddress.ip_address(ident)
    except ValueError:
        return ident
    if adresse.version == 6:
        if adresse.ipv4_mapped:
            return str(adresse.ipv4_mapped)
        return str(ipaddress.ip_network(f"{adresse}/64", strict=False))
    return str(adresse)


class _Fenster:
    """Zähler mit festem Fenster in der Datenbank (``akte.zaehler``): atomar, Ablauf bleibt beim Hochzählen."""

    schluessel = ""
    grenze: int | None = None
    dauer: int = 60

    def _stand(self):
        from akte import zaehler

        return zaehler.stand(self.schluessel)

    def gesperrt(self) -> bool:
        return self.grenze is not None and self._stand().anzahl >= self.grenze

    def zaehlen(self) -> None:
        from akte import zaehler

        if self.grenze is not None:
            zaehler.erhoehen(self.schluessel, self.dauer)

    def wartezeit(self) -> str:
        """Die echte Restzeit des Fensters in Worten („in 42 Sekunden“)."""
        from akte import zaehler

        return zaehler.wartezeit(self._stand().rest_sekunden())


class Fehlversuche(_Fenster):
    """Fehlgeschlagene Anmeldungen je Konto UND Absender (Rate ``login_konto``).

    Nur je Absender sperrte hinter dem Web-Proxy alle zugleich aus; nur je Konto könnte jeder ein fremdes Konto
    aussperren. Gezählt werden nur Fehlversuche, nach dem Auflösen der E-Mail auf den Benutzernamen (sonst zählten
    Name und Adresse doppelt). Den Absender liefert DRF (``NUM_PROXIES`` = ``AKTE_VERTRAUTE_PROXYS``), IPv6 je /64.
    """

    def __init__(self, request, view, benutzername: str, art: str = "login"):
        self.grenze, self.dauer = SimpleRateThrottle.parse_rate(
            None, api_settings.DEFAULT_THROTTLE_RATES.get("login_konto"))
        roh = f"{benutzername.casefold()}|{_absender(request)}".encode("utf-8")
        self.schluessel = f"akte-{art}-fehl:" + hashlib.sha256(roh).hexdigest()[:32]


class EinrichtungGesamtdeckel(_Fenster):
    """Falsche Einrichtungscodes über ALLE Absender (Rate ``einrichtung_gesamt``, Standard 30 je Stunde).

    Wer von vielen Adressen aus rät, kommt so insgesamt nur auf 30 Versuche je Stunde; bei 32^8 möglichen Codes ist
    Raten damit aussichtslos. Der Preis: Ein Angreifer kann die Einrichtung eine Stunde lang blockieren; der Mensch
    legt sein Konto dann über den Notweg an (``akte_einrichten``)."""

    schluessel = "akte-einrichtung-fehl:gesamt"

    def __init__(self):
        rate = api_settings.DEFAULT_THROTTLE_RATES.get("einrichtung_gesamt") or "30/hour"
        self.grenze, self.dauer = SimpleRateThrottle.parse_rate(None, rate)


def _fremde_herkunft(request) -> bool:
    """Kommt die Anfrage erkennbar von einer fremden Seite? Nur was der Browser selbst mitschickt, zählt:
    ``Sec-Fetch-Site`` (``cross-site``) und ``Origin`` (nicht diese Akte, nicht ``CSRF_TRUSTED_ORIGINS``). Fehlen
    beide (Werkzeuge, der Web-Proxy der Oberfläche), ist das kein Grund zur Ablehnung."""
    seite = request.META.get("HTTP_SEC_FETCH_SITE", "").strip().lower()
    if seite and seite not in ("same-origin", "same-site", "none"):
        return True
    herkunft = request.META.get("HTTP_ORIGIN", "").strip().rstrip("/").lower()
    if not herkunft:
        return False
    if herkunft == "null":
        return True
    erlaubt = {o.strip().rstrip("/").lower() for o in getattr(settings, "CSRF_TRUSTED_ORIGINS", [])}
    try:
        erlaubt.add(f"{request.scheme}://{request.get_host()}".lower())
    except Exception:  # noqa: BLE001 — unzulässiger Host: dann zählt nur die Liste
        pass
    return herkunft not in erlaubt


FREMDE_HERKUNFT = "Anfrage von fremder Herkunft abgelehnt."


class LoginView(APIView):
    """Anmeldung: nur JSON, nur aus der eigenen Oberfläche (``_fremde_herkunft``)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    parser_classes = [JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        if _fremde_herkunft(request):
            return Response({"detail": FREMDE_HERKUNFT}, status=status.HTTP_403_FORBIDDEN)
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
            return Response({"detail": f"Zu viele Fehlversuche. Bitte {fehl.wartezeit()} erneut."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        nutzer = authenticate(request, username=benutzername, password=passwort)
        if nutzer is None or not nutzer.is_active:
            fehl.zaehlen()
            return Response({"detail": "Anmeldung fehlgeschlagen."}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(nutzer)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})


#: Mindestlänge des Einrichtungscodes (ohne Bindestrich). Der Starter erzeugt 8 Zeichen aus 32 (40 Bit); ein
#: kürzerer Code in .env hält die Einrichtung geschlossen, statt sie leicht erratbar zu machen.
CODE_MIN = 8


def _code_normal(wert: str) -> str:
    """„abcd-efgh“, „ABCD EFGH“ und „ABCDEFGH“ sind derselbe Code."""
    return "".join(str(wert).split()).replace("-", "").upper()


_zu_kurz_gemeldet: list[bool] = []


def _einrichtungscode() -> str:
    """Der Code aus .env, angeglichen; leer = Einrichtung im Browser geschlossen. Wird nie ausgegeben oder geloggt."""
    code = _code_normal(getattr(settings, "AKTE_EINRICHTUNGSCODE", "") or "")
    if code and len(code) < CODE_MIN:
        if not _zu_kurz_gemeldet:  # einmal je Prozess, die Oberfläche fragt oft
            _zu_kurz_gemeldet.append(True)
            logger.warning("Akte: AKTE_EINRICHTUNGSCODE ist kürzer als %s Zeichen; die Einrichtung im Browser "
                           "bleibt zu.", CODE_MIN)
        return ""
    return code


def einrichtung_grund() -> str:
    """``eingerichtet`` (es gibt ein aktives Redaktionskonto), ``kein_code`` (kein gültiger Code in .env) oder
    ``offen``. „eingerichtet“ geht vor: Dann ist der Code ohnehin bedeutungslos."""
    from akte.permissions import redaktion_eingerichtet

    if redaktion_eingerichtet():
        return "eingerichtet"
    return "offen" if _einrichtungscode() else "kein_code"


def einrichtung_offen() -> bool:
    return einrichtung_grund() == "offen"


def _fehler(text: str, status_code: int, felder: dict | None = None) -> Response:
    daten = {"fehler": text}
    if felder:
        daten["felder"] = felder
    return Response(daten, status=status_code)


SCHON_EINGERICHTET = "Die Ultra-Akte ist schon eingerichtet. Bitte anmelden."
NAME_VERGEBEN = "Diesen Benutzernamen gibt es schon."


class EinrichtungLesenDrossel(AnonRateThrottle):
    """Lockere Drossel für ``GET`` (die Oberfläche und der Starter fragen oft), eigener Zähler je Absender."""

    scope = "einrichtung_lesen"

    def get_rate(self):
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope) or "120/min"


class EinrichtungView(APIView):
    """Erstes Redaktionskonto im Browser.

    ``GET`` → ``{"offen": bool, "grund": "offen" | "kein_code" | "eingerichtet"}``. Der Code selbst geht nie hinaus.
    ``POST {"code", "benutzername", "passwort", "archiv_org"}`` → ``201 {"benutzername"}``; legt Gruppe, Konto,
    Mitgliedschaft und die Einstellung archive.org in einer Transaktion an.

    Schutz: Ohne Code in .env ist die Einrichtung zu. Sie geht nur, solange es kein Redaktionskonto gibt (nie für
    einen vorhandenen Namen: keine Übernahme). Der Code wird zeitkonstant verglichen (``hmac.compare_digest``),
    Fehlversuche werden je Absender (IPv6 je /64) gezählt und gebremst wie beim Login, dazu ein Deckel über alle
    Absender (``EinrichtungGesamtdeckel``). Zwei gleichzeitige Anfragen legen nie zwei Konten an: Die zweite wartet
    auf die Sperre der Redaktionsgruppe und findet dann das erste Konto (409).
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    parser_classes = [JSONParser]
    throttle_scope = "login"

    def get_throttles(self):
        if self.request.method == "GET":
            return [EinrichtungLesenDrossel()]
        return [ScopedRateThrottle()]

    def get(self, request):
        grund = einrichtung_grund()
        return Response({"offen": grund == "offen", "grund": grund})

    def post(self, request):
        from akte.einstellungen import archiv_org_setzen
        from akte.permissions import REDAKTION_GRUPPE, redaktion_eingerichtet

        if _fremde_herkunft(request):
            # Absichtlich ohne „fehler“: Die Oberfläche erkennt die Herkunfts-Ablehnung daran (und markiert dann nicht
            # das Code-Feld). Nur JSON (``parser_classes``): ein Formular einer fremden Seite bekommt 415.
            return Response({"detail": FREMDE_HERKUNFT}, status=status.HTTP_403_FORBIDDEN)
        daten = request.data if isinstance(request.data, dict) else {}
        soll = _einrichtungscode()
        if redaktion_eingerichtet():
            return _fehler(SCHON_EINGERICHTET, status.HTTP_409_CONFLICT)
        if not soll:
            return _fehler("Die Einrichtung im Browser ist aus: Es ist kein Einrichtungscode gesetzt. Starte die Akte "
                           "mit dem Starter (START-AKTE), dann gibt es einen.", status.HTTP_403_FORBIDDEN)
        gesamt = EinrichtungGesamtdeckel()
        if gesamt.gesperrt():
            return _fehler(f"Zu viele falsche Einrichtungscodes. Die Einrichtung im Browser ist gesperrt und geht "
                           f"{gesamt.wartezeit()} wieder. Der Notweg ohne Code: docker compose exec api python "
                           "manage.py akte_einrichten", status.HTTP_429_TOO_MANY_REQUESTS)
        fehl = Fehlversuche(request, self, "", art="einrichtung")
        if fehl.gesperrt():
            return _fehler(f"Zu viele Fehlversuche. Bitte {fehl.wartezeit()} erneut.", status.HTTP_429_TOO_MANY_REQUESTS)
        eingabe = _code_normal(daten.get("code") or "")
        if not hmac.compare_digest(eingabe.encode("utf-8"), soll.encode("utf-8")):
            fehl.zaehlen()
            gesamt.zaehlen()
            logger.warning("Akte: Einrichtung mit falschem Code abgelehnt")
            return _fehler("Einrichtungscode stimmt nicht.", status.HTTP_403_FORBIDDEN)

        benutzername = str(daten.get("benutzername") or "").strip()
        passwort = daten.get("passwort")
        archiv_org = daten.get("archiv_org", False)
        felder: dict[str, list[str]] = {}
        User = get_user_model()
        konto = User(username=benutzername)
        if not benutzername:
            felder["benutzername"] = ["Bitte einen Benutzernamen angeben."]
        else:
            try:
                konto.clean_fields(exclude=[f.name for f in User._meta.fields if f.name != User.USERNAME_FIELD])
            except ValidationError as fehler:
                felder["benutzername"] = list(fehler.message_dict.get(User.USERNAME_FIELD, fehler.messages))
        if not isinstance(passwort, str) or not passwort:
            felder["passwort"] = ["Bitte ein Passwort angeben."]
        elif len(passwort) > 4096:
            felder["passwort"] = ["Das Passwort ist zu lang (höchstens 4096 Zeichen)."]
        else:
            try:
                validate_password(passwort, konto)
            except ValidationError as fehler:
                felder["passwort"] = list(fehler.messages)
        if not isinstance(archiv_org, bool):
            felder["archiv_org"] = ["Bitte Ja (true) oder Nein (false) angeben."]
        if felder:
            return _fehler("Bitte die markierten Angaben prüfen.", status.HTTP_400_BAD_REQUEST, felder)

        name_vergeben = _fehler(f"{NAME_VERGEBEN} Bitte einen anderen wählen.", status.HTTP_400_BAD_REQUEST,
                                {"benutzername": [NAME_VERGEBEN]})
        with transaction.atomic():
            try:
                # Eigener Sicherungspunkt: legen zwei Anfragen die Gruppe gleichzeitig an, verliert eine hier und
                # nimmt die Gruppe der anderen (get_or_create liest nach dem Konflikt neu).
                with transaction.atomic():
                    gruppe, _ = Group.objects.get_or_create(name=REDAKTION_GRUPPE)
            except IntegrityError:
                gruppe = Group.objects.get(name=REDAKTION_GRUPPE)
            # Sperre: Zwei gleichzeitige Einrichtungen warten aufeinander (Postgres); SQLite schreibt ohnehin nur
            # eine Transaktion zugleich (transaction_mode IMMEDIATE). Erst unter der Sperre prüfen.
            Group.objects.select_for_update().filter(pk=gruppe.pk).first()
            if redaktion_eingerichtet():
                return _fehler(SCHON_EINGERICHTET, status.HTTP_409_CONFLICT)
            if User.objects.filter(**{f"{User.USERNAME_FIELD}__iexact": benutzername}).exists():
                return name_vergeben
            konto.set_password(passwort)
            try:
                with transaction.atomic():
                    konto.save()
            except IntegrityError:  # derselbe Name, gleichzeitig von außerhalb angelegt
                return name_vergeben
            konto.groups.add(gruppe)
            archiv_org_setzen(archiv_org, konto)
        logger.info("Akte: erstes Redaktionskonto im Browser angelegt")
        return Response({"benutzername": konto.get_username()}, status=status.HTTP_201_CREATED)


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
