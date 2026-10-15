"""Erstes Konto im Browser: nur mit Einrichtungscode, nur solange es kein Redaktionskonto gibt, nie eine Übernahme."""

import io
import json
import os
import threading
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from akte.einstellungen import archiv_org_aktiv
from akte.models import Einstellungen
from akte.permissions import REDAKTION_GRUPPE

User = get_user_model()
WEG = "/api/v1/auth/einrichtung/"
CODE = "K7QM-2XPA"
GUT = {"code": CODE, "benutzername": "anna", "passwort": "ein-langes-gutes-passwort-2026", "archiv_org": False}
DREI_JE_MINUTE = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {
    **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "login_konto": "3/min"}}
GESAMT_DREI_JE_STUNDE = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {
    **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "einrichtung_gesamt": "3/hour"}}
LESEN_ZWEI_JE_MINUTE = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {
    **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "einrichtung_lesen": "2/min"}}
OFFEN = {"offen": True, "grund": "offen"}
KEIN_CODE = {"offen": False, "grund": "kein_code"}
EINGERICHTET = {"offen": False, "grund": "eingerichtet"}


@override_settings(AKTE_EINRICHTUNGSCODE=CODE, AKTE_ARCHIV_AKTIV=False)
class EinrichtungTest(TestCase):
    def setUp(self):
        cache.clear()  # Fehlversuche zählen sonst über Tests hinweg
        self.client = APIClient()

    def _post(self, **anders):
        return self.client.post(WEG, {**GUT, **anders}, format="json")

    def test_offen_nur_mit_code_und_ohne_redaktion(self):
        self.assertEqual(self.client.get(WEG).json(), OFFEN)
        with override_settings(AKTE_EINRICHTUNGSCODE=""):
            self.assertEqual(self.client.get(WEG).json(), KEIN_CODE)
        with override_settings(AKTE_EINRICHTUNGSCODE="ABC-123"):  # zu kurz: lieber zu als erratbar
            self.assertEqual(self.client.get(WEG).json(), KEIN_CODE)
        User.objects.create_superuser("chefin", "chefin@example.org", "egal-egal-egal-1")
        self.assertEqual(self.client.get(WEG).json(), EINGERICHTET)
        with override_settings(AKTE_EINRICHTUNGSCODE=""):  # „eingerichtet“ geht vor „kein Code“
            self.assertEqual(self.client.get(WEG).json(), EINGERICHTET)

    def test_inaktives_redaktionskonto_zaehlt_nicht(self):
        alt = User.objects.create_user("alt", "alt@example.org", "egal-egal-egal-1", is_active=False)
        alt.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.assertEqual(self.client.get(WEG).json(), OFFEN)

    @override_settings(REST_FRAMEWORK=LESEN_ZWEI_JE_MINUTE)
    def test_lesen_ist_locker_gedrosselt(self):
        self.assertEqual([self.client.get(WEG).status_code for _ in range(3)], [200, 200, 429])
        self.assertEqual(self._post().status_code, 201)  # eigener Zähler: das Anlegen bleibt frei

    @override_settings(REST_FRAMEWORK={**GESAMT_DREI_JE_STUNDE, "NUM_PROXIES": 1})
    def test_gesamtdeckel_ueber_alle_absender(self):
        for i in range(3):  # drei verschiedene Absender raten je einmal
            antwort = self.client.post(WEG, {**GUT, "code": "AAAA-BBBB"}, format="json",
                                       HTTP_X_FORWARDED_FOR=f"198.51.100.{i}")  # scrub:erlaubt (Doku-IPs)
            self.assertEqual(antwort.status_code, 403)
        antwort = self.client.post(WEG, GUT, format="json", HTTP_X_FORWARDED_FOR="203.0.113.9")  # scrub:erlaubt
        self.assertEqual(antwort.status_code, 429)
        self.assertRegex(antwort.json()["fehler"], r"gesperrt und geht in (60|59) Minuten wieder")  # echte Restzeit
        self.assertIn("akte_einrichten", antwort.json()["fehler"])
        self.assertFalse(User.objects.exists())

    def test_nur_json(self):
        # SR-F4: Ein Formular einer fremden Seite (application/x-www-form-urlencoded) kommt gar nicht erst an.
        antwort = self.client.post(WEG, GUT, format="multipart")
        self.assertEqual(antwort.status_code, 415)
        self.assertFalse(User.objects.exists())

    def test_fremde_herkunft_ohne_fehler_feld(self):
        for kopf in ({"HTTP_SEC_FETCH_SITE": "cross-site"}, {"HTTP_ORIGIN": "https://boese.beispiel.test"},
                     {"HTTP_ORIGIN": "null"}):
            antwort = self.client.post(WEG, GUT, format="json", **kopf)
            self.assertEqual(antwort.status_code, 403, kopf)
            self.assertNotIn("fehler", antwort.json())  # die Oberfläche erkennt die Herkunfts-Ablehnung daran
            self.assertNotIn("Einrichtungscode", str(antwort.json()))
        self.assertFalse(User.objects.exists())

    def test_eigene_herkunft_und_ohne_angaben_gehen_durch(self):
        # Wie die Next-Route der Oberfläche: application/json, ohne Origin, ohne fremdes Sec-Fetch-Site.
        antwort = self.client.post(WEG, GUT, format="json", HTTP_ORIGIN="http://testserver",
                                   HTTP_SEC_FETCH_SITE="same-origin", HTTP_SEC_FETCH_MODE="cors")
        self.assertEqual(antwort.status_code, 201, antwort.content)

    @override_settings(REST_FRAMEWORK=DREI_JE_MINUTE)
    def test_ipv6_zaehlt_je_64er_netz(self):
        for ende in ("1", "2", "3"):  # dieselbe Leitung, je Versuch eine neue Adresse
            antwort = self.client.post(WEG, {**GUT, "code": "AAAA-BBBB"}, format="json",
                                       REMOTE_ADDR=f"2001:db8:0:1::{ende}")  # scrub:erlaubt (Doku-Präfix)
            self.assertEqual(antwort.status_code, 403)
        gesperrt = self.client.post(WEG, GUT, format="json", REMOTE_ADDR="2001:db8:0:1::99")  # scrub:erlaubt
        self.assertEqual(gesperrt.status_code, 429)
        anderes_netz = self.client.post(WEG, GUT, format="json", REMOTE_ADDR="2001:db8:0:2::1")  # scrub:erlaubt
        self.assertEqual(anderes_netz.status_code, 201)

    def test_erstes_konto_mit_code_ohne_bindestrich_und_klein(self):
        antwort = self._post(code="k7qm2xpa", archiv_org=True)
        self.assertEqual(antwort.status_code, 201, antwort.content)
        self.assertEqual(antwort.json(), {"benutzername": "anna"})
        konto = User.objects.get(username="anna")
        self.assertTrue(konto.check_password(GUT["passwort"]))
        self.assertTrue(konto.groups.filter(name=REDAKTION_GRUPPE).exists())
        self.assertFalse(konto.is_staff or konto.is_superuser)
        self.assertTrue(archiv_org_aktiv())
        self.assertEqual(Einstellungen.objects.get().geaendert_von, konto)
        self.assertEqual(self.client.get(WEG).json(), EINGERICHTET)
        # Danach meldet sich das Konto ganz normal an.
        login = self.client.post("/api/v1/auth/login/", {"login": "anna", "password": GUT["passwort"]}, format="json")
        self.assertEqual(login.status_code, 200)

    def test_archiv_org_standard_nein(self):
        daten = {k: v for k, v in GUT.items() if k != "archiv_org"}
        self.assertEqual(self.client.post(WEG, daten, format="json").status_code, 201)
        self.assertIs(Einstellungen.objects.get().archiv_org, False)

    def test_zweites_mal_ist_409_auch_mit_richtigem_code(self):
        self.assertEqual(self._post().status_code, 201)
        antwort = self._post(benutzername="mallory")
        self.assertEqual(antwort.status_code, 409)
        self.assertEqual(antwort.json(), {"fehler": "Die Ultra-Akte ist schon eingerichtet. Bitte anmelden."})
        self.assertFalse(User.objects.filter(username="mallory").exists())

    def test_falscher_code_legt_nichts_an(self):
        antwort = self._post(code="AAAA-BBBB")
        self.assertEqual(antwort.status_code, 403)
        self.assertEqual(antwort.json(), {"fehler": "Einrichtungscode stimmt nicht."})
        self.assertFalse(User.objects.exists())
        for unsinn in ("", None, ["K7QM2XPA"], {"code": CODE}, "K7QM2XPAX", "ä" * 8):
            self.assertEqual(self._post(code=unsinn).status_code, 403, unsinn)
            cache.clear()
        self.assertFalse(User.objects.exists())

    def test_ohne_code_in_env_geschlossen(self):
        with override_settings(AKTE_EINRICHTUNGSCODE=""):
            antwort = self._post(code="")
        self.assertEqual(antwort.status_code, 403)
        self.assertIn("kein Einrichtungscode", antwort.json()["fehler"])
        self.assertFalse(User.objects.exists())

    def test_keine_uebernahme_eines_vorhandenen_kontos(self):
        mitglied = User.objects.create_user("Anna", "anna@example.org", "altes-passwort-bleibt-1")
        antwort = self._post(benutzername="anna")
        self.assertEqual(antwort.status_code, 400)
        self.assertIn("benutzername", antwort.json()["felder"])
        mitglied.refresh_from_db()
        self.assertTrue(mitglied.check_password("altes-passwort-bleibt-1"))
        self.assertFalse(mitglied.groups.exists())
        self.assertEqual(User.objects.count(), 1)

    def test_passwortregeln_auf_deutsch(self):
        antwort = self._post(passwort="kurz")
        self.assertEqual(antwort.status_code, 400)
        daten = antwort.json()
        self.assertIn("passwort", daten["felder"])
        self.assertTrue(any("zu kurz" in t for t in daten["felder"]["passwort"]), daten)
        self.assertFalse(User.objects.exists())
        self.assertEqual(self._post(passwort="1234567890123").status_code, 400)  # nur Ziffern
        self.assertEqual(self._post(passwort="").status_code, 400)
        self.assertEqual(self._post(passwort=12345678901).status_code, 400)
        self.assertEqual(self._post(passwort="x" * 5000).status_code, 400)

    def test_ungueltige_angaben(self):
        self.assertIn("benutzername", self._post(benutzername="  ").json()["felder"])
        self.assertIn("benutzername", self._post(benutzername="mit leerzeichen").json()["felder"])
        self.assertIn("archiv_org", self._post(archiv_org="ja").json()["felder"])
        self.assertEqual(self.client.post(WEG, ["x"], format="json").status_code, 403)
        self.assertFalse(User.objects.exists())

    @override_settings(REST_FRAMEWORK=DREI_JE_MINUTE)
    def test_fehlversuche_werden_gebremst(self):
        self.assertEqual([self._post(code="AAAA-BBBB").status_code for _ in range(3)], [403, 403, 403])
        antwort = self._post()  # auch der richtige Code wartet jetzt
        self.assertEqual(antwort.status_code, 429)
        self.assertFalse(User.objects.exists())

    def test_code_steht_nie_in_antwort_oder_log(self):
        with self.assertLogs("konto.views", level="INFO") as log:
            antworten = [self._post(code="AAAA-BBBB"), self._post(passwort="kurz"), self._post(), self._post()]
            antworten.append(self.client.get(WEG))
        for antwort in antworten:
            text = antwort.content.decode()
            self.assertNotIn("K7QM", text.upper())
        self.assertFalse(any("K7QM" in zeile.upper() for zeile in log.output), log.output)

    def test_gleichzeitige_zweite_anfrage_findet_das_erste_konto(self):
        # Die Prüfung innerhalb der Sperre zählt: vorher sah es noch frei aus, unter der Sperre nicht mehr.
        with mock.patch("akte.permissions.redaktion_eingerichtet", side_effect=[False, True]):
            antwort = self._post()
        self.assertEqual(antwort.status_code, 409)
        self.assertFalse(User.objects.filter(username="anna").exists())

    def test_anmeldung_wird_nicht_gebraucht_und_ignoriert(self):
        fremd = User.objects.create_user("fremd", "fremd@example.org", "egal-egal-egal-1")
        self.client.force_authenticate(fremd)
        self.assertEqual(self._post().status_code, 201)
        fremd.refresh_from_db()
        self.assertFalse(fremd.groups.exists())


@override_settings(AKTE_EINRICHTUNGSCODE=CODE, AKTE_ARCHIV_AKTIV=False)
class GleichzeitigTest(TransactionTestCase):
    """Zwei Menschen (oder ein Mensch mit Doppelklick) richten gleichzeitig ein: genau ein Konto entsteht."""

    def test_zwei_gleichzeitige_einrichtungen(self):
        cache.clear()
        start = threading.Barrier(2)
        ergebnisse: dict[str, int] = {}

        def einrichten(name):
            try:
                start.wait(5)
                antwort = APIClient().post(WEG, {**GUT, "benutzername": name}, format="json")
                ergebnisse[name] = antwort.status_code
            finally:
                connection.close()

        threads = [threading.Thread(target=einrichten, args=(n,)) for n in ("anna", "berta")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(sorted(ergebnisse.values()), [201, 409], ergebnisse)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Group.objects.filter(name=REDAKTION_GRUPPE).count(), 1)


class EinrichtenBefehlTest(TestCase):
    def test_falls_keins_tut_nichts_bei_vorhandener_redaktion(self):
        konto = User.objects.create_user("anna", "anna@example.org", "ein-langes-gutes-passwort-2026")
        konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        aus = io.StringIO()
        call_command("akte_einrichten", "--falls-keins", "--benutzer", "zweite", stdout=aus)
        self.assertIn("nichts zu tun", aus.getvalue())
        self.assertFalse(User.objects.filter(username="zweite").exists())

    def test_falls_keins_legt_an_wenn_noch_keins_da(self):
        with mock.patch.dict(os.environ, {"AKTE_PASSWORT": "ein-langes-gutes-passwort-2026"}):
            call_command("akte_einrichten", "--falls-keins", "--benutzer", "anna", stdout=io.StringIO())
        self.assertTrue(User.objects.get(username="anna").groups.filter(name=REDAKTION_GRUPPE).exists())


class KontenBefehlTest(TestCase):
    """Starter fragen über ``akte_konten`` und ``akte_token`` ohne Namen: Redaktion ODER Superuser, nur aktive (CR2)."""

    def _konten(self) -> list[str]:
        aus = io.StringIO()
        call_command("akte_konten", "--json", stdout=aus)
        return json.loads(aus.getvalue())["konten"]

    def _token(self, *args) -> str:
        aus = io.StringIO()
        call_command("akte_token", *args, stdout=aus)
        return aus.getvalue().strip()

    def test_superuser_allein_bekommt_den_token(self):
        User.objects.create_superuser("chefin", "chefin@example.org", "egal-egal-egal-1")
        User.objects.create_user("mitglied", "m@example.org", "egal-egal-egal-1")
        self.assertEqual(self._konten(), ["chefin"])
        self.assertEqual(len(self._token()), 40)
        aus = io.StringIO()
        call_command("akte_konten", stdout=aus)
        self.assertEqual(aus.getvalue().split(), ["KONTO:chefin"])

    def test_ohne_namen_nur_bei_genau_einem_konto(self):
        with self.assertRaisesRegex(CommandError, "noch kein Konto"):
            self._token()
        gruppe = Group.objects.create(name=REDAKTION_GRUPPE)
        for name in ("anna", "berta"):
            User.objects.create_user(name, f"{name}@example.org", "egal-egal-egal-1").groups.add(gruppe)
        inaktiv = User.objects.create_user("carla", "carla@example.org", "egal-egal-egal-1", is_active=False)
        inaktiv.groups.add(gruppe)
        self.assertEqual(self._konten(), ["anna", "berta"])
        with self.assertRaisesRegex(CommandError, "mehrere Konten: anna, berta"):
            self._token()
        self.assertEqual(len(self._token("berta")), 40)
        with self.assertRaisesRegex(CommandError, "deaktiviert"):
            self._token("carla")
