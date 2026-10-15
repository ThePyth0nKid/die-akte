"""Bild einer Karte: fremde Adresse über http(s) oder ein Bild, das die Akte selbst ausliefert (/static/akte/…).

Die Oberfläche schickt ``bild_url`` beim Speichern einer Notiz unverändert zurück. Ein eigener Pfad muss deshalb
dieselbe Prüfung bestehen wie eine Adresse aus dem Netz, sonst ließe sich die Karte nach dem Setzen nicht mehr ändern.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from akte.models import bild_adresse
from akte.permissions import REDAKTION_GRUPPE

GUT = [
    "",
    "https://upload.wikimedia.org/wikipedia/commons/a/ab/Bild.jpg",
    "http://example.org/bild.png",
    "/static/akte/demo/erika-mustermann.webp",
    "/static/akte/demo/senat-wappen.svg",
    "/static/akte/eigene_bilder/karte-1.png",
    "/static/akte/foto.jpeg",
]

SCHLECHT = [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "data:image/png;base64,iVBORw0KGgo=",
    "ftp://example.org/bild.png",
    "//example.org/bild.png",
    "/static/akte/../admin/css/base.css",
    "/static/akte/demo/../../x.webp",
    "/static/akte//demo/x.webp",
    "/static/akte/demo/x.webp?v=1",
    "/static/akte/demo/x.webp#oben",
    "/static/akte/demo/x.webp\n",
    "/static/akte/demo/x.gif",
    "/static/akte/demo/x.WEBP",
    "/static/akte/demo/x.html",
    "/static/akte/demo/.webp",
    "/static/admin/img/icon.svg",
    "/media/x.webp",
    "/api/v1/akte/boards/",
    "static/akte/demo/x.webp",
    "/static/akte/demo/x y.webp",
    "/static/akte/demo/ü.webp",
    "/static/akte\\demo\\x.webp",
]


class BildAdresseTest(SimpleTestCase):
    def test_erlaubt(self):
        for wert in GUT:
            with self.subTest(wert=wert):
                bild_adresse(wert)

    def test_abgelehnt(self):
        for wert in SCHLECHT:
            with self.subTest(wert=wert), self.assertRaises(ValidationError):
                bild_adresse(wert)


class BildAdresseApiTest(TestCase):
    def setUp(self):
        konto = get_user_model().objects.create_user("redaktion", password="x")
        konto.groups.add(Group.objects.get_or_create(name=REDAKTION_GRUPPE)[0])
        self.api = APIClient()
        self.api.force_authenticate(konto)

    def anlegen(self, bild_url):
        return self.api.post("/api/v1/akte/entitaeten/", {
            "name": "Rechnungshof Musterhafen", "typ": "behoerde", "bild_url": bild_url,
            "bild_nachweis": "KI-Bild · erfundenes Gebäude"}, format="json")

    def test_eigenes_bild_beim_anlegen_und_unveraendert_zurueck(self):
        pfad = "/static/akte/demo/rechnungshof.webp"
        r = self.anlegen(pfad)
        self.assertEqual(r.status_code, 201, r.content)
        # So speichert die Notizleiste: alle Felder zurück, das Bild unverändert.
        e = r.json()
        r = self.api.patch(f"/api/v1/akte/entitaeten/{e['id']}/", {
            "name": e["name"], "typ": e["typ"], "kurzbeschreibung": "prüft die Haushaltsführung",
            "bild_url": e["bild_url"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["bild_url"], pfad)

    def test_schaedliche_adresse_wird_abgelehnt(self):
        for wert in ("javascript:alert(1)", "/static/akte/../x.webp", "data:image/svg+xml,<svg/>"):
            with self.subTest(wert=wert):
                r = self.anlegen(wert)
                self.assertEqual(r.status_code, 400)
                self.assertIn("bild_url", r.json())
