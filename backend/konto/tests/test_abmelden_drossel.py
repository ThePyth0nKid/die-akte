"""Abmelden sperrt den Refresh-Token; Fehlversuche werden je Konto und Absender gebremst, Erfolge nicht gezählt."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

LOGIN = "/api/v1/auth/login/"
DREI_JE_MINUTE = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {
    **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "login_konto": "3/min"}}


class AbmeldenTest(TestCase):
    def setUp(self):
        cache.clear()
        get_user_model().objects.create_user("redaktion", "redaktion@example.org", "lang-genug-123")
        self.client = APIClient()

    def test_abgemeldeter_refresh_gilt_nie_wieder(self):
        refresh = self.client.post(LOGIN, {"login": "redaktion", "password": "lang-genug-123"},
                                   format="json").json()["refresh"]
        self.assertEqual(self.client.post("/api/v1/auth/logout/", {"refresh": refresh}, format="json").status_code, 204)
        antwort = self.client.post("/api/v1/auth/jwt/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(antwort.status_code, 401)

    def test_benutzter_refresh_gilt_nach_rotation_nicht_mehr(self):
        refresh = self.client.post(LOGIN, {"login": "redaktion", "password": "lang-genug-123"},
                                   format="json").json()["refresh"]
        self.assertEqual(self.client.post("/api/v1/auth/jwt/refresh/", {"refresh": refresh},
                                          format="json").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/auth/jwt/refresh/", {"refresh": refresh},
                                          format="json").status_code, 401)

    def test_abmelden_mit_unsinn_ist_kein_fehler(self):
        self.assertEqual(self.client.post("/api/v1/auth/logout/", {"refresh": "x"}, format="json").status_code, 204)


@override_settings(REST_FRAMEWORK=DREI_JE_MINUTE)
class FehlversucheTest(TestCase):
    def setUp(self):
        cache.clear()
        get_user_model().objects.create_user("redaktion", "redaktion@example.org", "lang-genug-123")
        get_user_model().objects.create_user("andere", "andere@example.org", "lang-genug-456")
        self.client = APIClient()

    def _login(self, login, passwort, **kopf):
        return self.client.post(LOGIN, {"login": login, "password": passwort}, format="json", **kopf).status_code

    def test_ratendes_konto_wird_gesperrt_andere_nicht(self):
        self.assertEqual([self._login("redaktion", "falsch") for _ in range(2)], [401, 401])
        # Name und E-Mail zählen gemeinsam: dasselbe Konto.
        self.assertEqual(self._login("REDAKTION@example.org", "falsch"), 401)
        self.assertEqual(self._login("redaktion", "lang-genug-123"), 429)
        self.assertEqual(self._login("andere", "lang-genug-456"), 200)

    def test_erfolge_zaehlen_nicht(self):
        self.assertEqual({self._login("redaktion", "lang-genug-123") for _ in range(6)}, {200})

    @override_settings(REST_FRAMEWORK={**DREI_JE_MINUTE, "NUM_PROXIES": 1})
    def test_anderer_absender_bleibt_frei(self):
        for _ in range(3):
            self._login("redaktion", "falsch", HTTP_X_FORWARDED_FOR="203.0.113.7")  # scrub:erlaubt (Doku-IP)
        self.assertEqual(self._login("redaktion", "lang-genug-123", HTTP_X_FORWARDED_FOR="203.0.113.7"), 429)  # scrub:erlaubt
        self.assertEqual(self._login("redaktion", "lang-genug-123", HTTP_X_FORWARDED_FOR="198.51.100.2"), 200)  # scrub:erlaubt

    def test_ohne_vertraute_proxys_zaehlt_kein_x_forwarded_for(self):
        for i in range(3):
            self._login("redaktion", "falsch", HTTP_X_FORWARDED_FOR=f"192.0.2.{i}")  # scrub:erlaubt (Doku-IPs)
        self.assertEqual(self._login("redaktion", "lang-genug-123", HTTP_X_FORWARDED_FOR="192.0.2.9"), 429)  # scrub:erlaubt

    def test_json_liste_ist_kein_serverfehler(self):
        self.assertEqual(self.client.post(LOGIN, ["x"], format="json").status_code, 400)
