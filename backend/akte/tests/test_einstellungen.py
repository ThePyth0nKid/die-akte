"""Einstellung archive.org: Standard aus, ein Mensch entscheidet, die Sicherung hält sich daran."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from akte.einstellungen import archiv_org_aktiv, archiv_org_setzen
from akte.models import Einstellungen, Quelle, Verlauf
from akte.permissions import REDAKTION_GRUPPE
from akte.sicherung import archive_org_sichern

User = get_user_model()
WEG = "/api/v1/akte/einstellungen/"


@override_settings(AKTE_ARCHIV_AKTIV=False)
class EinstellungenApiTest(TestCase):
    def setUp(self):
        self.konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        self.konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.mensch = APIClient()
        self.mensch.force_authenticate(self.konto)
        self.werkzeug = APIClient()
        self.werkzeug.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.konto).key}")

    def test_standard_ist_aus(self):
        with override_settings(AKTE_ARCHIV_AKTIV=False):
            self.assertEqual(self.mensch.get(WEG).json(), {"archiv_org": False})
        # Solange niemand entschieden hat, gilt .env; danach die Entscheidung.
        with override_settings(AKTE_ARCHIV_AKTIV=True):
            self.assertEqual(self.mensch.get(WEG).json(), {"archiv_org": True})
            archiv_org_setzen(False)
            self.assertEqual(self.mensch.get(WEG).json(), {"archiv_org": False})

    def test_mensch_schaltet_um_mit_verlauf(self):
        antwort = self.mensch.patch(WEG, {"archiv_org": True}, format="json")
        self.assertEqual((antwort.status_code, antwort.json()), (200, {"archiv_org": True}))
        self.assertTrue(archiv_org_aktiv())
        self.assertEqual(Einstellungen.objects.get().geaendert_von, self.konto)
        self.assertTrue(Verlauf.objects.filter(objekt_art="einstellungen", aktion="geaendert").exists())
        self.assertEqual(self.mensch.patch(WEG, {"archiv_org": False}, format="json").json(), {"archiv_org": False})
        self.assertEqual(Einstellungen.objects.count(), 1)

    def test_werkzeug_liest_aendert_aber_nicht(self):
        self.assertEqual(self.werkzeug.get(WEG).status_code, 200)
        antwort = self.werkzeug.patch(WEG, {"archiv_org": True}, format="json")
        self.assertEqual(antwort.status_code, 403)
        self.assertFalse(archiv_org_aktiv())
        self.assertFalse(Einstellungen.objects.exists())

    def test_ungueltige_eingaben(self):
        for daten in ({"archiv_org": "ja"}, {"archiv_org": 1}, {"archiv_org": None}, {"unbekannt": True}, ["x"]):
            self.assertEqual(self.mensch.patch(WEG, daten, format="json").status_code, 400, daten)
        self.assertFalse(Einstellungen.objects.exists())

    def test_nur_redaktion(self):
        fremd = User.objects.create_user("fremd", "fremd@example.org", "pw")
        c = APIClient()
        c.force_authenticate(fremd)
        self.assertEqual(c.get(WEG).status_code, 403)
        self.assertEqual(c.patch(WEG, {"archiv_org": True}, format="json").status_code, 403)
        self.assertIn(APIClient().get(WEG).status_code, (401, 403))
        self.assertFalse(archiv_org_aktiv())


class ArchivEinstellungWirktTest(TestCase):
    def test_aus_geht_nichts_an_archive_org(self):
        q = Quelle.objects.create(titel="A", url="https://x.example/a")
        with override_settings(AKTE_ARCHIV_AKTIV=True), mock.patch("akte.sicherung.requests") as netz:
            archiv_org_setzen(False)
            self.assertIsNone(archive_org_sichern(q))
        netz.get.assert_not_called()
        netz.post.assert_not_called()

    def test_an_geht_an_archive_org_auch_wenn_env_aus(self):
        q = Quelle.objects.create(titel="A", url="https://x.example/a")
        archiv = mock.Mock(status_code=200, url="https://web.archive.org/web/20261014/https://x.example/a", headers={})
        with override_settings(AKTE_ARCHIV_AKTIV=False), mock.patch("akte.sicherung.requests.get",
                                                                     return_value=archiv) as abruf, \
                mock.patch("akte.sicherung.pruefe_url"):
            archiv_org_setzen(True)
            s = archive_org_sichern(q)
        self.assertEqual(s.status, "fertig")
        abruf.assert_called_once()
