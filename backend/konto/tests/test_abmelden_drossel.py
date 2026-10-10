"""Abmelden sperrt den Refresh-Token; Fehlversuche werden je Konto gebremst, nicht je Absender."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from konto.views import KontoDrossel

LOGIN = "/api/v1/auth/login/"


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


class KontoDrosselTest(TestCase):
    def setUp(self):
        cache.clear()
        get_user_model().objects.create_user("redaktion", "redaktion@example.org", "lang-genug-123")
        get_user_model().objects.create_user("andere", "andere@example.org", "lang-genug-456")
        self.client = APIClient()

    def test_ratendes_konto_wird_gesperrt_andere_nicht(self):
        with mock.patch.object(KontoDrossel, "rate", "3/min", create=True):
            for _ in range(3):
                self.assertEqual(self.client.post(LOGIN, {"login": "redaktion", "password": "falsch"},
                                                  format="json").status_code, 401)
            self.assertEqual(self.client.post(LOGIN, {"login": "REDAKTION", "password": "falsch"},
                                              format="json").status_code, 429)
            # Gleicher Absender, anderes Konto: nicht betroffen.
            self.assertEqual(self.client.post(LOGIN, {"login": "andere", "password": "lang-genug-456"},
                                              format="json").status_code, 200)
