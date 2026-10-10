"""Die Akte ohne Konto.

Besucher sollen alles Belegte sehen, aber nichts bearbeiten. Besucher ohne Konto bekommen
die Lese-Ansicht der Mitglieder für Boards mit ``oeffentlich=True``, solange ``AKTE_OEFFENTLICH_AKTIV`` an ist.
Wichtigster Test: ``test_mappe_zu_nicht_oeffentlichem_board_ohne_spuren`` (Falk/Brandt bleiben gesperrt,
obwohl die Hauptwand Mappen dorthin hat).
"""

import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from akte.models import Board, Mappe, VerbindungTyp, Zettel, ZettelArt

from .test_mappen import entitaet, faden, legen, quelle

User = get_user_model()
WAND = "/api/v1/akte/boards/{}/"


@override_settings(AKTE_OEFFENTLICH_AKTIV=True, AKTE_MITGLIEDER_BOARDS="")
class OeffentlichLesenTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.haupt = Board.objects.create(titel="Die Hauptwand", slug="hauptwand", oeffentlich=True)
        self.pal = Board.objects.create(titel="Nordlicht", slug="nordlicht", oeffentlich=True)
        self.falk = Board.objects.create(titel="Die Falk-Akten", slug="falk")
        self.mustermann = entitaet("Max Mustermann")
        self.kranich = entitaet("Erika Kranich")
        self.privat = entitaet("Tom Klein", oeffentlich=False)
        self.geheim = entitaet("Otto Falk")
        legen(self.haupt, self.mustermann)
        legen(self.pal, self.mustermann, self.kranich, self.privat)
        legen(self.falk, self.geheim, self.mustermann)
        q = quelle()
        faden(self.mustermann, self.kranich, q)
        faden(self.mustermann, self.privat, q, typ=VerbindungTyp.SONSTIGES)
        faden(self.mustermann, self.geheim, q)
        Mappe.objects.create(board=self.haupt, ziel=self.pal)
        Mappe.objects.create(board=self.haupt, ziel=self.falk)
        Zettel.objects.create(board=self.pal, art=ZettelArt.MEINUNG, text="Wir sind dagegen.")
        Zettel.objects.create(board=self.pal, art=ZettelArt.FRAGE, text="Hat Tom Klein Geld bekommen?")
        Zettel.objects.create(board=self.pal, art=ZettelArt.NOTIZ, text="Interne Vermutung")

    def test_liest_oeffentliches_board_ohne_konto(self):
        r = self.client.get(WAND.format("nordlicht"))
        self.assertEqual(r.status_code, 200)
        w = r.json()
        self.assertFalse(w["darf_bearbeiten"])
        self.assertEqual({k["entitaet_detail"]["name"] for k in w["karten"]}, {"Max Mustermann", "Erika Kranich", "T. K."})
        self.assertEqual(len(w["faeden"]), 2)
        self.assertEqual(w["fahrten"], [])
        self.assertEqual(w["beweise"], [])

    def test_nur_meinungs_zettel(self):
        w = self.client.get(WAND.format("nordlicht")).json()
        self.assertEqual([(z["art"], z["text"]) for z in w["zettel"]], [("meinung", "Wir sind dagegen.")])
        text = json.dumps(w)
        self.assertNotIn("Interne Vermutung", text)
        self.assertNotIn("Tom Klein", text)

    def test_mappe_zu_nicht_oeffentlichem_board_ohne_spuren(self):
        w = self.client.get(WAND.format("hauptwand")).json()
        self.assertEqual([m["ziel"] for m in w["mappen"]], ["nordlicht"])
        text = json.dumps(w).lower()
        self.assertNotIn("falk", text)
        pw = self.client.get(WAND.format("nordlicht")).json()
        nr_mustermann = next(k["id"] for k in pw["karten"] if k["entitaet_detail"]["name"] == "Max Mustermann")
        self.assertEqual([b["slug"] for b in pw["auch_in"][str(nr_mustermann)]], ["hauptwand"])
        self.assertNotIn("falk", json.dumps(pw).lower())

    def test_nicht_oeffentliches_board_bleibt_zu(self):
        self.assertEqual(self.client.get(WAND.format("falk")).status_code, 404)

    def test_liste_zeigt_nur_oeffentliche(self):
        r = self.client.get("/api/v1/akte/boards/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({b["slug"] for b in r.json()}, {"hauptwand", "nordlicht"})
        self.assertTrue(all(b["darf_bearbeiten"] is False for b in r.json()))
        self.assertNotIn("oeffentlich", r.json()[0])

    def test_schreiben_bleibt_redaktion(self):
        self.assertIn(self.client.post("/api/v1/akte/boards/", {"titel": "X"}, format="json").status_code, (401, 403))
        self.assertIn(self.client.patch(WAND.format("nordlicht"), {"titel": "X"}, format="json").status_code, (401, 403))
        self.assertIn(self.client.delete(WAND.format("nordlicht")).status_code, (401, 403))
        self.assertIn(self.client.get("/api/v1/akte/entitaeten/?q=Mustermann").status_code, (401, 403))
        self.pal.refresh_from_db()
        self.assertEqual(self.pal.titel, "Nordlicht")

    def test_schalter_aus_alles_zu(self):
        with self.settings(AKTE_OEFFENTLICH_AKTIV=False):
            self.assertIn(self.client.get(WAND.format("nordlicht")).status_code, (401, 403))
            self.assertIn(self.client.get("/api/v1/akte/boards/").status_code, (401, 403))

    def test_zurueckgezogenes_board_lebt_nicht_im_cache(self):
        self.assertEqual(self.client.get(WAND.format("hauptwand")).status_code, 200)
        self.pal.oeffentlich = False
        self.pal.save()
        self.assertEqual(self.client.get(WAND.format("nordlicht")).status_code, 404)
        w = self.client.get(WAND.format("hauptwand")).json()
        self.assertEqual(w["mappen"], [])

    def test_aenderung_gilt_sofort_trotz_cache(self):
        self.assertIn("Erika Kranich", json.dumps(self.client.get(WAND.format("nordlicht")).json()))
        self.kranich.oeffentliche_person = False
        self.kranich.save()
        text = json.dumps(self.client.get(WAND.format("nordlicht")).json())
        self.assertNotIn("Erika Kranich", text)
        self.assertIn("E. K.", text)

    def test_cache_ausfall_bricht_nicht(self):
        from unittest import mock

        with mock.patch("akte.lesecache.cache.get", side_effect=ConnectionError("redis weg")),                 mock.patch("akte.lesecache.cache.set", side_effect=ConnectionError("redis weg")):
            r = self.client.get(WAND.format("nordlicht"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["karten"]), 3)

    def test_drossel_zaehlt_echte_ip_nicht_den_ganzen_header(self):
        from unittest import mock

        from akte.permissions import AkteOeffentlichThrottle

        with mock.patch.object(AkteOeffentlichThrottle, "get_rate", return_value="2/min"):
            # Eingestellter Kopf eines vorgeschalteten Dienstes zählt, die gefälschte Kette nicht.
            with override_settings(AKTE_CLIENT_IP_HEADER="CF-Connecting-IP"):
                codes = [self.client.get(WAND.format("nordlicht"), HTTP_CF_CONNECTING_IP="203.0.113.7",
                                         HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 198.51.100.1").status_code  # scrub:erlaubt
                         for i in range(3)]
            self.assertEqual(codes, [200, 200, 429])
            # Ein eigener Proxy: das letzte Glied der Kette, nicht der gefälschte Anfang.
            cache.clear()
            with override_settings(AKTE_VERTRAUTE_PROXYS=1):
                codes = [self.client.get(WAND.format("nordlicht"),
                                         HTTP_X_FORWARDED_FOR=f"10.9.9.{i}, 198.51.100.9").status_code  # scrub:erlaubt
                         for i in range(3)]
            self.assertEqual(codes, [200, 200, 429])
            # Ohne Einstellung wird keinem Kopf geglaubt: ein gefälschter CF-Kopf öffnet keinen neuen Deckel.
            cache.clear()
            codes = [self.client.get(WAND.format("nordlicht"), HTTP_CF_CONNECTING_IP=f"203.0.113.{i}",
                                     REMOTE_ADDR="198.51.100.20").status_code for i in range(3)]
            self.assertEqual(codes, [200, 200, 429])

    def test_mitglied_sieht_oeffentliche_und_mitglieder_boards(self):
        intern = Board.objects.create(titel="Nur Mitglieder", slug="mitglieder")
        self.client.force_authenticate(User.objects.create_user(username="m", email="mitglied@example.org", password="pw"))
        with self.settings(AKTE_MITGLIEDER_BOARDS="mitglieder"):
            slugs = {b["slug"] for b in self.client.get("/api/v1/akte/boards/").json()}
            self.assertEqual(slugs, {"hauptwand", "nordlicht", "mitglieder"})
            self.assertEqual(self.client.get(WAND.format(intern.slug)).status_code, 200)
        self.assertEqual(self.client.get(WAND.format("falk")).status_code, 404)


class AkteErsetzenTest(TestCase):
    """Das Ersetzen: alles weg, Fixture rein, in einer Transaktion; ``--trocken`` ändert nichts."""

    def setUp(self):
        import tempfile
        from io import StringIO
        from pathlib import Path

        from django.core.management import call_command

        self.call_command = call_command
        neu = Board.objects.create(titel="Neu", slug="hauptwand", oeffentlich=True)
        legen(neu, entitaet("Max Mustermann"))
        self.ordner = tempfile.TemporaryDirectory()
        self.fixture = Path(self.ordner.name) / "akte.json"
        puffer = StringIO()
        call_command("dumpdata", "akte", stdout=puffer)
        self.fixture.write_text(puffer.getvalue(), encoding="utf-8")
        # Der „alte Stand“: andere Wand, Rahmen, die in der Fixture nicht vorkommen.
        Board.objects.all().delete()
        alt = Board.objects.create(titel="Alt", slug="nordlicht")
        legen(alt, entitaet("Erika Kranich"))
        alt.rahmen.create(titel="Veraltet", x=0, y=0, breite=10, hoehe=10)

    def tearDown(self):
        self.ordner.cleanup()

    def test_ohne_schalter_nichts(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.call_command("akte_ersetzen", str(self.fixture))
        self.assertTrue(Board.objects.filter(slug="nordlicht").exists())

    def test_trocken_rollt_zurueck(self):
        self.call_command("akte_ersetzen", str(self.fixture), "--trocken", stdout=__import__("io").StringIO())
        self.assertEqual(list(Board.objects.values_list("slug", flat=True)), ["nordlicht"])

    def test_ersetzt_alles(self):
        from akte.models import Entitaet, Rahmen

        self.call_command("akte_ersetzen", str(self.fixture), "--ja", stdout=__import__("io").StringIO())
        self.assertEqual(list(Board.objects.values_list("slug", "oeffentlich")), [("hauptwand", True)])
        self.assertFalse(Rahmen.objects.exists())
        self.assertEqual(list(Entitaet.objects.values_list("name", flat=True)), ["Max Mustermann"])
