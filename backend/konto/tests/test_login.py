from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


class LoginTests(TestCase):
    def setUp(self):
        self.nutzer = get_user_model().objects.create_user("redaktion", "redaktion@example.org", "lang-genug-123")
        self.client = APIClient()

    def test_login_mit_benutzername(self):
        antwort = self.client.post("/api/v1/auth/login/", {"login": "redaktion", "password": "lang-genug-123"},
                                   format="json")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("access", antwort.json())
        self.assertIn("refresh", antwort.json())

    def test_login_mit_email(self):
        antwort = self.client.post("/api/v1/auth/login/",
                                   {"login": "REDAKTION@example.org", "password": "lang-genug-123"}, format="json")
        self.assertEqual(antwort.status_code, 200)

    def test_falsches_passwort(self):
        antwort = self.client.post("/api/v1/auth/login/", {"login": "redaktion", "password": "falsch"}, format="json")
        self.assertEqual(antwort.status_code, 401)

    def test_refresh(self):
        refresh = self.client.post("/api/v1/auth/login/", {"login": "redaktion", "password": "lang-genug-123"},
                                   format="json").json()["refresh"]
        antwort = self.client.post("/api/v1/auth/jwt/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("access", antwort.json())

    def test_jwt_oeffnet_akte(self):
        access = self.client.post("/api/v1/auth/login/", {"login": "redaktion", "password": "lang-genug-123"},
                                  format="json").json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.client.get("/api/v1/akte/boards/").status_code, 200)
