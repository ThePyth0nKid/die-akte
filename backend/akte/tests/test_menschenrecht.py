"""Werkzeuge (Token) arbeiten zu, Menschen geben frei (akte/menschenrecht.py)."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from akte.models import Board, Entitaet, Status
from akte.permissions import REDAKTION_GRUPPE

User = get_user_model()


class MenschenrechtTest(TestCase):
    def setUp(self):
        self.konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        self.konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.werkzeug = APIClient()
        self.werkzeug.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.konto).key}")
        self.mensch = APIClient()
        self.mensch.force_authenticate(self.konto)

    def test_werkzeug_legt_nur_entwuerfe_an(self):
        r = self.werkzeug.post("/api/v1/akte/entitaeten/", {"name": "Nordlicht Analytik", "typ": "firma"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Entitaet.objects.get(pk=r.json()["id"]).status, Status.ENTWURF)
        r = self.werkzeug.post("/api/v1/akte/entitaeten/",
                               {"name": "Kranich Holding", "typ": "firma", "status": "freigegeben"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Entitaet.objects.filter(name="Kranich Holding").exists())

    def test_werkzeug_gibt_nicht_frei(self):
        e = Entitaet.objects.create(name="Nordlicht Analytik", slug="nordlicht", typ="firma")
        r = self.werkzeug.patch(f"/api/v1/akte/entitaeten/{e.id}/", {"status": "freigegeben"}, format="json")
        self.assertEqual(r.status_code, 403)
        e.refresh_from_db()
        self.assertEqual(e.status, Status.ENTWURF)
        # Entwürfe ändern darf das Werkzeug.
        r = self.werkzeug.patch(f"/api/v1/akte/entitaeten/{e.id}/", {"kurzbeschreibung": "Datenfirma"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_freigegebenes_bleibt_fuer_werkzeuge_gesperrt(self):
        e = Entitaet.objects.create(name="Nordlicht Analytik", slug="nordlicht", typ="firma",
                                    status=Status.FREIGEGEBEN)
        r = self.werkzeug.patch(f"/api/v1/akte/entitaeten/{e.id}/", {"kurzbeschreibung": "anders"}, format="json")
        self.assertEqual(r.status_code, 409)
        r = self.werkzeug.patch(f"/api/v1/akte/entitaeten/{e.id}/", {"status": "entwurf"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.werkzeug.delete(f"/api/v1/akte/entitaeten/{e.id}/").status_code, 409)
        self.assertTrue(Entitaet.objects.filter(pk=e.id).exists())

    def test_mensch_gibt_frei_und_aendert(self):
        e = Entitaet.objects.create(name="Nordlicht Analytik", slug="nordlicht", typ="firma")
        r = self.mensch.patch(f"/api/v1/akte/entitaeten/{e.id}/", {"status": "freigegeben"}, format="json")
        self.assertEqual(r.status_code, 200)
        r = self.mensch.patch(f"/api/v1/akte/entitaeten/{e.id}/", {"kurzbeschreibung": "anders"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_werkzeug_schaltet_kein_board_oeffentlich(self):
        r = self.werkzeug.post("/api/v1/akte/boards/", {"titel": "Musterhafen", "oeffentlich": True}, format="json")
        self.assertEqual(r.status_code, 403)
        board = Board.objects.create(titel="Musterhafen", slug="musterhafen")
        r = self.werkzeug.patch("/api/v1/akte/boards/musterhafen/", {"oeffentlich": True}, format="json")
        self.assertEqual(r.status_code, 403)
        board.refresh_from_db()
        self.assertFalse(board.oeffentlich)
        r = self.mensch.patch("/api/v1/akte/boards/musterhafen/", {"oeffentlich": True}, format="json")
        self.assertEqual(r.status_code, 200)
