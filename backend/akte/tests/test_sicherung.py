"""Beweissicherung: sicherer Abruf, Kopie mit Prüfsumme, archive.org, Anhänge, Auslieferung."""

import hashlib
import shutil
import socket
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from akte import abruf
from akte.abruf import AbrufFehler, erkenne, oeffentlich, pruefe_url
from akte.einstellungen import archiv_org_setzen
from akte.models import Board, BoardBeweis, Quelle, Sicherung
from akte.permissions import REDAKTION_GRUPPE
from akte.sicherung import anhang_speichern, lies_meta, quelle_sichern_jetzt

User = get_user_model()
PDF = b"%PDF-1.7\n" + b"x" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"y" * 200
HTML = (b'<!doctype html><html><head><title>Titel der Seite</title>'
        b'<meta property="og:site_name" content="Tagesschau">'
        b'<meta property="og:image" content="/bild.png"></head><body>Text</body></html>')


def adressen(*ips):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]


class AbrufTest(TestCase):
    def test_nur_oeffentliche_adressen(self):
        self.assertTrue(oeffentlich("93.184.216.34"))
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "fc00::1"):  # scrub:erlaubt (SSRF-Testadresse)
            self.assertFalse(oeffentlich(ip), ip)

    def test_pruefe_url_sperrt(self):
        with mock.patch("akte.abruf.socket.getaddrinfo", return_value=adressen("169.254.169.254")):
            with self.assertRaises(AbrufFehler):
                pruefe_url("http://metadata.example/")
        with mock.patch("akte.abruf.socket.getaddrinfo", return_value=adressen("93.184.216.34", "10.0.0.1")):  # scrub:erlaubt (SSRF-Testadresse)
            with self.assertRaises(AbrufFehler):
                pruefe_url("https://gemischt.example/")
        for url in ("file:///etc/passwd", "ftp://x.example/", "https://x.example:8443/", "javascript:alert(1)"):
            with self.assertRaises(AbrufFehler):
                pruefe_url(url)

    def test_weiterleitung_ins_interne_netz_wird_gestoppt(self):
        weiter = mock.Mock(is_redirect=True, headers={"Location": "http://intern.example/"}, status_code=302)

        def aufloesen(host, *a, **k):
            return adressen("10.1.2.3" if host == "intern.example" else "93.184.216.34")  # scrub:erlaubt (SSRF-Testadresse)

        with mock.patch("akte.abruf.socket.getaddrinfo", side_effect=aufloesen), \
             mock.patch.object(abruf.requests.Session, "get", return_value=weiter):
            with self.assertRaises(AbrufFehler):
                abruf.abrufen("https://aussen.example/")

    def test_erkennt_an_den_bytes(self):
        self.assertEqual(erkenne(PDF), "pdf")
        self.assertEqual(erkenne(PNG), "png")
        self.assertEqual(erkenne(HTML), "html")
        self.assertEqual(erkenne(b"<svg onload=alert(1)>"), "sonstiges")

    def test_meta(self):
        m = lies_meta(HTML.decode())
        self.assertEqual((m["titel"], m["herausgeber"], m["bild"]), ("Titel der Seite", "Tagesschau", "/bild.png"))


class _MitSpeicher(TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.einstellung = override_settings(AKTE_SPEICHER_LOKAL=self.ordner, AKTE_R2_BUCKET="")
        self.einstellung.enable()

    def tearDown(self):
        self.einstellung.disable()
        shutil.rmtree(self.ordner, ignore_errors=True)


class SicherungTest(_MitSpeicher):
    def setUp(self):
        super().setUp()
        # archive.org ist seit 0.2 von Haus aus aus; diese Tests prüfen den Weg mit eingeschaltetem archive.org.
        archiv_org_setzen(True)

    def test_seite_mit_vorschau_und_archive_org(self):
        q = Quelle.objects.create(titel="Artikel", url="https://www.tagesschau.de/a")

        def holen(url, max_bytes=None, frist=None):
            return abruf.Abruf(url, 200, "", PNG if url.endswith(".png") else HTML)

        archiv = mock.Mock(status_code=200, url="https://web.archive.org/web/20260924/https://www.tagesschau.de/a", headers={})
        with mock.patch("akte.sicherung.abrufen", side_effect=holen), \
             mock.patch("akte.sicherung.requests.get", return_value=archiv):
            quelle_sichern_jetzt(q)
        q.refresh_from_db()
        original = q.sicherungen.get(art="original")
        self.assertEqual(original.status, "fertig")
        self.assertEqual(original.sha256, hashlib.sha256(HTML).hexdigest())
        self.assertEqual(q.herausgeber, "Tagesschau")
        self.assertTrue(q.sicherungen.filter(art="vorschau", status="fertig").exists())
        self.assertTrue(q.archiv_url.startswith("https://web.archive.org/web/"))

    def test_fehler_wird_festgehalten_statt_zu_werfen(self):
        q = Quelle.objects.create(titel="Weg", url="https://weg.example/")
        with mock.patch("akte.sicherung.abrufen", side_effect=AbrufFehler("Die Seite antwortet mit 404.")), \
             mock.patch("akte.sicherung.requests.get", side_effect=abruf.requests.ConnectionError()):
            quelle_sichern_jetzt(q)
        self.assertEqual(set(q.sicherungen.values_list("art", "status")), {("original", "fehler"), ("archive_org", "fehler")})

    def test_gedrosseltes_archive_org_nimmt_vorhandenen_schnappschuss(self):
        q = Quelle.objects.create(titel="A", url="https://x.example/a")
        gedrosselt = mock.Mock(status_code=429, url="https://web.archive.org/save/https://x.example/a", headers={})
        vorhanden = mock.Mock()
        vorhanden.json.return_value = {"archived_snapshots": {"closest": {
            "available": True, "url": "http://web.archive.org/web/20250101000000/https://x.example/a"}}}
        with mock.patch("akte.sicherung.requests.get", side_effect=[gedrosselt, vorhanden]), \
             mock.patch("akte.sicherung.pruefe_url"):
            from akte.sicherung import archive_org_sichern

            s = archive_org_sichern(q)
        q.refresh_from_db()
        self.assertEqual(s.status, "fertig")
        self.assertEqual(q.archiv_url, "https://web.archive.org/web/20250101000000/https://x.example/a")
        self.assertIn("Älterer Schnappschuss", s.fehler)

    def test_gleiche_datei_liegt_einmal(self):
        a = Quelle.objects.create(titel="A")
        b = Quelle.objects.create(titel="B")
        s1 = anhang_speichern(a, PDF, "a.pdf")
        s2 = anhang_speichern(b, PDF, "b.pdf")
        self.assertEqual(s1.schluessel, s2.schluessel)

    def test_anhang_nur_pdf_und_bilder(self):
        q = Quelle.objects.create(titel="X")
        with self.assertRaises(ValueError):
            anhang_speichern(q, HTML, "seite.html")


class SicherungApiTest(_MitSpeicher):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.redakteur = User.objects.create_user(username="redaktion", email="redaktion@example.org", password="pw")
        self.redakteur.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.client.force_authenticate(self.redakteur)

    def test_neue_quelle_stoesst_sicherung_an(self):
        with override_settings(AKTE_SICHERUNG_AKTIV=True), \
             mock.patch("akte.tasks.quelle_sichern.delay") as anstoss, \
             self.captureOnCommitCallbacks(execute=True):
            antwort = self.client.post("/api/v1/akte/quellen/", {"titel": "T", "url": "https://x.example/"}, format="json")
        self.assertEqual(antwort.status_code, 201)
        anstoss.assert_called_once_with(antwort.json()["id"])

    def test_quelle_aus_datei_landet_als_beweis_auf_dem_board(self):
        Board.objects.create(titel="P", slug="p")
        antwort = self.client.post("/api/v1/akte/quellen/aus-datei/", {
            "datei": SimpleUploadedFile("screenshot.png", PNG, content_type="image/png"),
            "board": "p", "x": "100", "y": "200",
        }, format="multipart")
        self.assertEqual(antwort.status_code, 201, antwort.content)
        daten = antwort.json()
        self.assertIsNotNone(daten["stand"]["vorschau"])
        beweis = BoardBeweis.objects.get()
        self.assertEqual((beweis.x, beweis.y), (100.0, 200.0))
        wand = self.client.get("/api/v1/akte/boards/p/").json()
        self.assertEqual(len(wand["beweise"]), 1)

    def test_falsche_datei_wird_abgelehnt(self):
        antwort = self.client.post("/api/v1/akte/quellen/aus-datei/", {
            "datei": SimpleUploadedFile("boese.pdf", b"<html><script>alert(1)</script>", content_type="application/pdf"),
        }, format="multipart")
        self.assertEqual(antwort.status_code, 400)

    def test_html_kopie_kommt_als_text(self):
        q = Quelle.objects.create(titel="Seite", url="https://x.example/")
        with mock.patch("akte.sicherung.abrufen", return_value=abruf.Abruf("https://x.example/", 200, "", HTML)), \
             mock.patch("akte.sicherung.requests.get", side_effect=abruf.requests.ConnectionError()), \
             mock.patch("akte.sicherung.vorschau_sichern"):
            quelle_sichern_jetzt(q)
        s = Sicherung.objects.get(art="original")
        antwort = self.client.get(f"/api/v1/akte/sicherungen/{s.id}/datei/")
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(antwort["Content-Type"].startswith("text/plain"))
        self.assertIn("attachment", antwort["Content-Disposition"])

    def test_datei_nur_fuer_redaktion(self):
        q = Quelle.objects.create(titel="A")
        s = anhang_speichern(q, PDF, "a.pdf")
        fremd = User.objects.create_user(username="fremd", email="fremd@example.org", password="pw")
        c = APIClient()
        c.force_authenticate(fremd)
        self.assertEqual(c.get(f"/api/v1/akte/sicherungen/{s.id}/datei/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/v1/akte/sicherungen/{s.id}/datei/").content, PDF)
