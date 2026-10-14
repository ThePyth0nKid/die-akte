"""SR-F3/F4: Fehlversuch-Zähler mit festem Fenster in der Datenbank; Anmeldung nur per JSON und gleicher Herkunft."""

from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from akte import zaehler
from akte.models import Zaehler

LOGIN = "/api/v1/auth/login/"
DREI_JE_MINUTE = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {
    **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "login_konto": "3/min"}}


class ZaehlerTest(TestCase):
    def test_fenster_bleibt_beim_hochzaehlen(self):
        t0 = timezone.now()
        with mock.patch("akte.zaehler.timezone.now", return_value=t0):
            zaehler.erhoehen("x", 60)
        with mock.patch("akte.zaehler.timezone.now", return_value=t0 + timedelta(seconds=50)):
            stand = zaehler.erhoehen("x", 60)
        self.assertEqual(stand.anzahl, 2)
        self.assertEqual(Zaehler.objects.get(schluessel="x").ablauf, t0 + timedelta(seconds=60))  # nicht verschoben
        with mock.patch("akte.zaehler.timezone.now", return_value=t0 + timedelta(seconds=61)):
            self.assertEqual(zaehler.stand("x").anzahl, 0)  # abgelaufen
            self.assertEqual(zaehler.erhoehen("x", 60).anzahl, 1)  # neues Fenster

    def test_abgelaufene_zeilen_werden_aufgeraeumt(self):
        t0 = timezone.now()
        Zaehler.objects.create(schluessel="alt", anzahl=5, ablauf=t0 - timedelta(hours=2))
        zaehler.erhoehen("neu", 60)
        self.assertFalse(Zaehler.objects.filter(schluessel="alt").exists())

    def test_wartezeit_in_worten(self):
        self.assertEqual(zaehler.wartezeit(42), "in 42 Sekunden")
        self.assertEqual(zaehler.wartezeit(61), "in 2 Minuten")
        self.assertEqual(zaehler.wartezeit(60), "in einer Minute")
        self.assertEqual(zaehler.wartezeit(3600), "in 60 Minuten")


class LoginHerkunftTest(TestCase):
    def setUp(self):
        get_user_model().objects.create_user("redaktion", "redaktion@example.org", "lang-genug-123")
        self.client = APIClient()

    def test_nur_json(self):
        antwort = self.client.post(LOGIN, {"login": "redaktion", "password": "lang-genug-123"}, format="multipart")
        self.assertEqual(antwort.status_code, 415)

    def test_fremde_herkunft(self):
        for kopf in ({"HTTP_SEC_FETCH_SITE": "cross-site"}, {"HTTP_ORIGIN": "https://boese.beispiel.test"}):
            antwort = self.client.post(LOGIN, {"login": "redaktion", "password": "lang-genug-123"}, format="json",
                                       **kopf)
            self.assertEqual(antwort.status_code, 403, kopf)

    @override_settings(CSRF_TRUSTED_ORIGINS=["http://localhost:8080"])
    def test_vertraute_und_eigene_herkunft(self):
        for herkunft in ("http://localhost:8080", "http://testserver"):
            antwort = self.client.post(LOGIN, {"login": "redaktion", "password": "lang-genug-123"}, format="json",
                                       HTTP_ORIGIN=herkunft)
            self.assertEqual(antwort.status_code, 200, herkunft)

    @override_settings(REST_FRAMEWORK=DREI_JE_MINUTE)
    def test_sperre_nennt_die_echte_restzeit(self):
        for _ in range(3):
            self.client.post(LOGIN, {"login": "redaktion", "password": "falsch"}, format="json")
        antwort = self.client.post(LOGIN, {"login": "redaktion", "password": "lang-genug-123"}, format="json")
        self.assertEqual(antwort.status_code, 429)
        self.assertRegex(antwort.json()["detail"], r"Bitte in (\d+ Sekunden|einer Minute) erneut")
