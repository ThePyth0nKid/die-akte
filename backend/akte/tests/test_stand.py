"""Stand der Wand für die Live-Aktualisierung: billig, ohne Schreiben, ändert sich bei jeder Änderung."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from akte.models import (
    Board, BoardBeweis, BoardKarte, Entitaet, Quelle, Sicherung, SicherungStatus, Status, Verbindung,
)
from akte.permissions import REDAKTION_GRUPPE

User = get_user_model()


class StandTest(TestCase):
    def setUp(self):
        cache.clear()
        self.konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        self.konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.c = APIClient()
        self.c.force_authenticate(self.konto)
        self.board = Board.objects.create(titel="Musterhafen", slug="musterhafen")
        self.a = Entitaet.objects.create(name="Senat", slug="senat", typ="behoerde")
        self.b = Entitaet.objects.create(name="Nordlicht", slug="nordlicht", typ="firma")
        self.karte = BoardKarte.objects.create(board=self.board, entitaet=self.a)
        BoardKarte.objects.create(board=self.board, entitaet=self.b)
        self.quelle = Quelle.objects.create(titel="Drucksache", url="https://x.example/d.pdf")

    def stand(self, client=None, slug="musterhafen"):
        antwort = (client or self.c).get(f"/api/v1/akte/boards/{slug}/stand/")
        self.assertEqual(antwort.status_code, 200, antwort.content)
        self.assertEqual(set(antwort.json()), {"stand"})
        return antwort.json()["stand"]

    def assertGeaendert(self, vorher):
        nachher = self.stand()
        self.assertNotEqual(vorher, nachher)
        return nachher

    def test_bleibt_gleich_ohne_aenderung_und_schreibt_nichts(self):
        erster = self.stand()
        with CaptureQueriesContext(connection) as abfragen:
            self.assertEqual(self.stand(), erster)
        befehle = [q["sql"].split()[0].upper() for q in abfragen.captured_queries]
        self.assertLessEqual(len(befehle), 3, abfragen.captured_queries)
        self.assertFalse({"INSERT", "UPDATE", "DELETE"} & set(befehle))

    def test_aendert_sich_bei_jeder_aenderung_an_der_wand(self):
        s = self.stand()
        r = self.c.post("/api/v1/akte/boards/musterhafen/positionen/",
                        [{"art": "karte", "id": self.karte.id, "x": 500, "y": 40}], format="json")
        self.assertEqual(r.status_code, 204)
        s = self.assertGeaendert(s)
        self.c.post("/api/v1/akte/boards/musterhafen/aufraeumen/")
        s = self.assertGeaendert(s)
        v = self.c.post("/api/v1/akte/verbindungen/", {"von": self.a.id, "nach": self.b.id, "typ": "auftrag",
                                                        "belege": [{"quelle": self.quelle.id, "zitat_woertlich": "x"}]},
                        format="json").json()
        s = self.assertGeaendert(s)
        self.c.patch(f"/api/v1/akte/verbindungen/{v['id']}/", {"beschreibung": "beauftragt"}, format="json")
        s = self.assertGeaendert(s)
        self.c.post("/api/v1/akte/boards/musterhafen/zettel/", {"art": "frage", "text": "Wer?"}, format="json")
        s = self.assertGeaendert(s)
        self.c.post("/api/v1/akte/boards/musterhafen/rahmen/", {"titel": "Auftrag"}, format="json")
        s = self.assertGeaendert(s)
        self.c.patch(f"/api/v1/akte/entitaeten/{self.a.id}/", {"kurzbeschreibung": "Landesregierung"}, format="json")
        s = self.assertGeaendert(s)

    def test_aendert_sich_bei_werkstatt_dingen_die_leser_nicht_sehen(self):
        s = self.stand()
        self.c.post("/api/v1/akte/boards/musterhafen/fahrten/aus-beschreibung/",
                    {"titel": "K1", "stationen": [{"fokus": ["Senat"]}]}, format="json")
        s = self.assertGeaendert(s)
        BoardBeweis.objects.create(board=self.board, quelle=self.quelle)
        s = self.assertGeaendert(s)
        Board.objects.create(titel="Anderswo", slug="anderswo")  # andere Wand: unnötig, aber unschädlich neu
        self.stand()

    def test_aendert_sich_mit_dem_sicherungsstand_der_quellen(self):
        s = self.stand()
        Sicherung.objects.create(quelle=self.quelle, art="original", status=SicherungStatus.FEHLER, fehler="404")
        s = self.assertGeaendert(s)
        Sicherung.objects.create(quelle=self.quelle, art="original", status=SicherungStatus.FERTIG, sha256="a" * 64)
        self.assertGeaendert(s)

    def test_werkzeug_darf_abfragen(self):
        werkzeug = APIClient()
        werkzeug.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.konto).key}")
        self.assertEqual(self.stand(werkzeug), self.stand())

    def test_unbekanntes_board_ist_404(self):
        self.assertEqual(self.c.get("/api/v1/akte/boards/gibt-es-nicht/stand/").status_code, 404)

    def test_ohne_konto_und_ohne_oeffentliche_akte_zu(self):
        self.assertIn(APIClient().get("/api/v1/akte/boards/musterhafen/stand/").status_code, (401, 403))

    @override_settings(AKTE_MITGLIEDER_BOARDS="musterhafen")
    def test_mitglied_sieht_nur_den_stand_der_lese_ansicht(self):
        mitglied = APIClient()
        mitglied.force_authenticate(User.objects.create_user("mitglied", "m@example.org", "pw"))
        self.assertEqual(mitglied.get("/api/v1/akte/boards/anderswo/stand/").status_code, 404)
        Board.objects.create(titel="Geheim", slug="geheim")
        self.assertEqual(mitglied.get("/api/v1/akte/boards/geheim/stand/").status_code, 404)
        s = self.stand(mitglied)
        # Ein Entwurf ist für Mitglieder unsichtbar: Ihr Stand verrät nicht, dass die Redaktion arbeitet.
        e = Entitaet.objects.create(name="Entwurf GmbH", slug="entwurf", typ="firma")
        BoardKarte.objects.create(board=self.board, entitaet=e)
        self.assertEqual(self.stand(mitglied), s)
        # Was Mitglieder sehen, ändert ihn.
        Entitaet.objects.filter(pk=self.a.pk).update(status=Status.FREIGEGEBEN)
        from akte import lesecache

        lesecache.veraltet()
        self.assertNotEqual(self.stand(mitglied), s)

    @override_settings(AKTE_MITGLIEDER_BOARDS="musterhafen")
    def test_fingerabdruck_einmal_je_version(self):
        # SR9: JSON und Hash der ganzen Lese-Ansicht nur einmal je Cache-Version, nicht bei jeder Abfrage.
        from unittest import mock

        from akte import lesecache

        mitglied = APIClient()
        mitglied.force_authenticate(User.objects.create_user("mitglied", "m@example.org", "pw"))
        with mock.patch("akte.lesecache._hash", wraps=lesecache._hash) as rechnen:
            erster = self.stand(mitglied)
            for _ in range(5):
                self.assertEqual(self.stand(mitglied), erster)
            self.assertEqual(rechnen.call_count, 1)
            lesecache.veraltet()
            self.stand(mitglied)
            self.assertEqual(rechnen.call_count, 2)

    @override_settings(AKTE_OEFFENTLICH_AKTIV=True)
    def test_besucher_einer_oeffentlichen_wand(self):
        Board.objects.filter(pk=self.board.pk).update(oeffentlich=True)
        besucher = APIClient()
        s = self.stand(besucher)
        self.assertEqual(self.stand(besucher), s)
        Verbindung.objects.create(von=self.a, nach=self.b, typ="auftrag")  # Entwurf: unsichtbar
        self.assertEqual(self.stand(besucher), s)
