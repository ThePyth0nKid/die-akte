"""Zitat prüfen (POST /belege/<id>/pruefen/): synchron, klare Antwort, Bindestriche am Zeilenende, nur die eigene
Quell-URL, Werkzeuge dürfen prüfen."""

import hashlib
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from akte import abruf
from akte.abruf import Abruf, AbrufFehler
from akte.models import Beleg, Entitaet, Quelle, Sicherung, Status, Verbindung
from akte.permissions import REDAKTION_GRUPPE
from akte.rendern import _flach, fundstelle_pdf
from akte.sicherung import anhang_speichern
from akte.tests.test_fundstelle import pdf_mit_seiten, pdf_mit_text
from akte.zitatpruefung import html_zu_text, zitat_finden

User = get_user_model()
MARKE = chr(0xFFFE)  # so liefert pdfium einen Bindestrich am Zeilenende (ohne Umbruch dahinter)
SATZ = "Der Senat beauftragt die Nordlicht Analytik GmbH mit der Auswertung der Verkehrsdaten."
SEITE = (f"<!doctype html><html><head><title>Senat</title><script>var x = '{SATZ}';</script>"
         "<style>p{color:red}</style></head><body><nav>Start | Presse</nav>"
         f"<article><h1>Vergabe</h1><p>Vorab. {SATZ.replace('Nordlicht', '<b>Nordlicht</b>')}</p>"
         "<p>Die neue EU-<br>Verordnung gilt ab&nbsp;heute f&uuml;r alle.</p>" + "<p>Fülltext.</p>" * 40
         + "</article></body></html>")


class ZitatFindenTest(SimpleTestCase):
    def test_woertlich_und_angeglichen(self):
        text = "Vorab. „Der Senat beauftragt“ – so steht es im Bericht."
        self.assertIsNotNone(zitat_finden(text, '"Der Senat beauftragt" - so steht es'))
        self.assertIsNotNone(zitat_finden(text, "der senat BEAUFTRAGT"))
        self.assertIsNone(zitat_finden(text, "Der Senat hat beauftragt"))

    def test_bindestrich_am_zeilenende_aus_pdfium(self):
        # Recherche 14.10.2026: aus „EU-Verordnung“ wurde „EUVerordnung“, weil die Marke stets wegfiel.
        self.assertIsNotNone(zitat_finden(f"Die neue EU{MARKE}Verordnung gilt ab heute.", "Die neue EU-Verordnung gilt"))
        self.assertIsNotNone(zitat_finden(f"Pflege: Gesundheits{MARKE}und Pflegeberufe", "Gesundheits- und Pflegeberufe"))
        self.assertIsNotNone(zitat_finden(f"Die Bundes{MARKE}regierung hat zugestimmt.", "Die Bundesregierung hat"))
        self.assertIsNone(zitat_finden(f"Die neue EU{MARKE}Verordnung gilt.", "Die neue EU Verordnung gilt"))

    def test_bindestrich_am_zeilenende_im_text(self):
        self.assertIsNotNone(zitat_finden("Die neue EU-\r\nVerordnung gilt ab heute.", "Die neue EU-Verordnung gilt"))
        self.assertIsNotNone(zitat_finden("Die Bundes-\nregierung hat zugestimmt.", "Die Bundesregierung hat zugestimmt"))
        self.assertIsNotNone(zitat_finden("Gesundheits-\nund Pflegeberufe", "Gesundheits- und Pflegeberufe"))
        # Das Zitat selbst mit Umbruch (aus einem PDF kopiert) trifft den glatten Text.
        self.assertIsNotNone(zitat_finden("Die neue EU-Verordnung gilt ab heute.", "Die neue EU-\nVerordnung gilt"))

    def test_auslassung_reihenfolge_und_abstand(self):
        text = "Erstens wird geprüft. Dazwischen steht viel. Zweitens wird beschlossen."
        self.assertIsNotNone(zitat_finden(text, "Erstens wird geprüft. […] Zweitens wird beschlossen."))
        self.assertIsNone(zitat_finden(text, "Zweitens wird beschlossen. […] Erstens wird geprüft."))
        weit = "Erstens wird geprüft. " + "Fülltext ohne Bezug. " * 600 + "Zweitens wird beschlossen."
        self.assertIsNone(zitat_finden(weit, "Erstens wird geprüft. … Zweitens wird beschlossen."))

    def test_html_wird_text_ohne_skripte(self):
        text = html_zu_text(SEITE)
        self.assertNotIn("var x", text)
        self.assertNotIn("color:red", text)
        self.assertIn("Nordlicht Analytik", text)
        self.assertIsNotNone(zitat_finden(text, SATZ))
        self.assertIsNotNone(zitat_finden(text, "Die neue EU-Verordnung gilt ab heute für alle."))
        self.assertIsNotNone(zitat_finden(html_zu_text("<p>Bundes&shy;regierung stimmt zu</p>"),
                                          "Bundesregierung stimmt zu"))
        # Ein nicht geschlossenes <noscript> im Kopf verschluckt nicht den Rest der Seite.
        self.assertIn("Artikeltext", html_zu_text("<head><noscript><img src=x></head><body><p>Artikeltext</p>"))

    def test_fundstelle_pdf_findet_jetzt_auch_eu_verordnung(self):
        pdf = pdf_mit_text("Ab heute gilt die neue EU-", "Verordnung fuer alle Mitgliedstaaten.")
        self.assertIsNotNone(fundstelle_pdf(pdf, "Ab heute gilt die neue EU-Verordnung fuer alle Mitgliedstaaten"))
        self.assertEqual(_flach(f"EU{MARKE}Verordnung", "klebt")[0], "eu-verordnung")
        self.assertEqual(_flach(f"EU{MARKE}Verordnung")[0], "euverordnung")  # Standard unverändert


class AbrufFristTest(SimpleTestCase):
    def test_frist_vorbei_ist_ein_abruffehler(self):
        with self.assertRaises(AbrufFehler):
            abruf._zeitlimit(time.monotonic() - 1)

    def test_troepfelnder_server_haelt_nicht_auf(self):
        # Eine künstliche Uhr: jeder Blick auf die Uhr ist eine Sekunde später; nach der Frist ist Schluss.
        uhr = iter(range(10_000))
        antwort = mock.Mock()
        antwort.raw.read1.return_value = b"x"  # ein Byte je Lesen, ohne Ende
        with mock.patch("akte.abruf.time.monotonic", side_effect=lambda: next(uhr)), self.assertRaises(AbrufFehler):
            for _ in abruf._stuecke(antwort, 5):
                pass
        self.assertLessEqual(antwort.raw.read1.call_count, 6)

    def test_kaputte_adressen_sind_abruffehler(self):
        for url in ("http://[::1", "http://x.example:99999/", "http://" + "a" * 70 + ".example/", "http:///ohne-host"):
            with self.assertRaises(AbrufFehler, msg=url):
                abruf.pruefe_url(url)
            with self.assertRaises(AbrufFehler, msg=url):
                abruf.pruefe_url(url, frist=time.monotonic() + 30)

    def test_dns_mit_frist(self):
        los = threading.Event()

        def haengt(*_a, **_k):
            los.wait(10)
            raise socket.gaierror("zu spät")

        with mock.patch("akte.abruf.socket.getaddrinfo", side_effect=haengt):
            try:
                with self.assertRaisesRegex(AbrufFehler, "nicht rechtzeitig"):
                    abruf.pruefe_url("https://langsam.beispiel.test/", frist=time.monotonic() + 0.05)
                with self.assertRaisesRegex(AbrufFehler, "Zeitlimit"):
                    abruf.pruefe_url("https://langsam.beispiel.test/", frist=time.monotonic() - 1)
            finally:
                los.set()


class SucheGrenzenTest(SimpleTestCase):
    def test_frist_gilt_in_der_suche(self):
        from akte.zitatpruefung import _ZeitUm

        text = "ab " * 5000
        with self.assertRaises(_ZeitUm):
            zitat_finden(text, "ab ab ab ab ab ab […] zz zz zz zz zz zz", frist=0)

    def test_angleichen_prueft_die_frist_selbst(self):
        # Der Vorab-Schätzer lässt den Text durch (frist in 60 s); die Uhr springt dann: _flach bricht selbst ab.
        from akte.zitatpruefung import _Suche, _ZeitUm

        uhr = iter([0.0] + [1000.0] * 10)
        with mock.patch("akte.zitatpruefung.time.monotonic", side_effect=lambda: next(uhr)), \
                mock.patch("akte.rendern.time.monotonic", return_value=1000.0), self.assertRaises(_ZeitUm):
            _Suche("wort " * 50_000, frist=60.0).finden([["zz"]])

    def test_viele_haeufige_teile_ohne_explosion(self):
        # Früher: jede Stelle jedes Teils neu probiert (exponentiell). Jetzt Teil für Teil, jede Stelle einmal.
        text = "eins zwei drei " * 3000
        zitat = " […] ".join(["eins zwei drei"] * 19 + ["kommt nicht vor"])
        self.assertIsNone(zitat_finden(text, zitat, frist=time.monotonic() + 60))
        treffer = zitat_finden(text, " […] ".join(["eins zwei drei"] * 20), frist=time.monotonic() + 60)
        self.assertEqual(treffer[0], 0)

    def test_spaetere_stelle_eines_teils_wird_auch_versucht(self):
        # Der erste Treffer von „B“ liegt zu weit vor „C“; erst die zweite Stelle von „B“ erreicht „C“.
        b, c = "Zweiter Teil des Zitats steht hier.", "Dritter Teil des Zitats steht dort."
        text = f"Erster Teil des Zitats. {b} " + "x" * 5000 + f" {b} " + "y" * 5000 + f" {c}"
        self.assertIsNotNone(zitat_finden(text, f"Erster Teil des Zitats. […] {b} […] {c}"))


class _Basis(TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.einst = override_settings(AKTE_SPEICHER_LOKAL=self.ordner, AKTE_R2_BUCKET="")
        self.einst.enable()
        self.konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        self.konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.c = APIClient()
        self.c.force_authenticate(self.konto)
        self.a = Entitaet.objects.create(name="Senat", slug="senat", typ="behoerde")
        self.b = Entitaet.objects.create(name="Nordlicht", slug="nordlicht", typ="firma")

    def tearDown(self):
        self.einst.disable()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def beleg(self, quelle, zitat=SATZ):
        v = Verbindung.objects.create(von=self.a, nach=self.b, typ="auftrag")
        return Beleg.objects.create(verbindung=v, quelle=quelle, zitat_woertlich=zitat)

    def pruefen(self, beleg, client=None, **daten):
        antwort = (client or self.c).post(f"/api/v1/akte/belege/{beleg.id}/pruefen/", daten, format="json")
        self.assertEqual(antwort.status_code, 200, antwort.content)
        daten = antwort.json()
        self.assertEqual(set(daten), {"ergebnis", "grund", "fundstelle"})
        self.assertIn(daten["ergebnis"], ("gefunden", "nicht_gefunden", "nicht_pruefbar"))
        self.assertTrue(daten["grund"])
        return daten

    def pdf_quelle(self, pdf: bytes) -> Quelle:
        q = Quelle.objects.create(titel="Drucksache 9/1234")
        anhang_speichern(q, pdf, "drs.pdf")
        return q


class PdfPruefenTest(_Basis):
    def test_gefunden_mit_seite_und_pruefsumme(self):
        pdf = pdf_mit_seiten(["Erste Seite."], ["Vorab.", SATZ])
        daten = self.pruefen(self.beleg(self.pdf_quelle(pdf)))
        self.assertEqual(daten["ergebnis"], "gefunden", daten)
        self.assertEqual(daten["fundstelle"]["seite"], 2)
        self.assertEqual(daten["fundstelle"]["sha256"], hashlib.sha256(pdf).hexdigest())
        self.assertIn("Nordlicht Analytik", daten["fundstelle"]["auszug"])
        self.assertIn("Seite 2", daten["grund"])

    def test_eu_verordnung_ueber_den_zeilenumbruch(self):
        pdf = pdf_mit_text("Ab heute gilt die neue EU-", "Verordnung fuer alle Mitgliedstaaten.")
        daten = self.pruefen(self.beleg(self.pdf_quelle(pdf), "die neue EU-Verordnung fuer alle Mitgliedstaaten"))
        self.assertEqual(daten["ergebnis"], "gefunden", daten)

    def test_zitat_ueber_den_seitenumbruch(self):
        pdf = pdf_mit_seiten(["Am Ende der Seite steht die EU-"], ["Verordnung fuer alle Mitgliedstaaten."])
        daten = self.pruefen(self.beleg(self.pdf_quelle(pdf), "die EU-Verordnung fuer alle Mitgliedstaaten"))
        self.assertEqual((daten["ergebnis"], daten["fundstelle"]["seite"]), ("gefunden", 1))

    def test_nicht_gefunden_mit_hilfreichem_grund(self):
        q = self.pdf_quelle(pdf_mit_text(SATZ))
        daten = self.pruefen(self.beleg(q, "Der Senat beauftragt die Nordlicht Analytik GmbH mit der Auswertung aller "
                                           "Daten der Stadt."))
        self.assertEqual(daten["ergebnis"], "nicht_gefunden")
        self.assertIsNone(daten["fundstelle"])
        self.assertIn("Anfang", daten["grund"])
        daten = self.pruefen(self.beleg(q, "Die Stadt hat niemals einen solchen Auftrag erteilt."))
        self.assertEqual(daten["ergebnis"], "nicht_gefunden")
        self.assertIn("steht so nicht", daten["grund"])

    def test_gescanntes_pdf_ist_nicht_pruefbar(self):
        daten = self.pruefen(self.beleg(self.pdf_quelle(pdf_mit_text(" "))))
        self.assertEqual(daten["ergebnis"], "nicht_pruefbar")
        self.assertIn("keinen lesbaren Text", daten["grund"])

    def test_beschaedigte_kopie_ist_nicht_pruefbar(self):
        q = self.pdf_quelle(pdf_mit_text(SATZ))
        s = Sicherung.objects.get(quelle=q, art="anhang")
        (Path(self.ordner) / s.schluessel).write_bytes(pdf_mit_text("Etwas ganz anderes."))
        daten = self.pruefen(self.beleg(q))
        self.assertEqual(daten["ergebnis"], "nicht_pruefbar")
        self.assertIn("Prüfsumme", daten["grund"])

    def test_bild_ist_nicht_pruefbar(self):
        q = Quelle.objects.create(titel="Screenshot")
        anhang_speichern(q, b"\x89PNG\r\n\x1a\n" + b"y" * 200, "bild.png")
        self.assertEqual(self.pruefen(self.beleg(q))["ergebnis"], "nicht_pruefbar")

    def test_ohne_zitat_zu_kurz_ohne_kopie(self):
        q = self.pdf_quelle(pdf_mit_text(SATZ))
        self.assertIn("kein wörtliches Zitat", self.pruefen(self.beleg(q, ""))["grund"])
        self.assertIn("zu kurz", self.pruefen(self.beleg(q, "Der Senat"))["grund"])
        self.assertEqual(self.pruefen(self.beleg(q, "[…]"))["ergebnis"], "nicht_pruefbar")
        leer = Quelle.objects.create(titel="Nur ein Titel")
        daten = self.pruefen(self.beleg(leer))
        self.assertEqual(daten["ergebnis"], "nicht_pruefbar")
        self.assertIn("weder einen Link", daten["grund"])

    def test_aendert_nichts_am_beleg(self):
        beleg = self.beleg(self.pdf_quelle(pdf_mit_text(SATZ)))
        vorher = (beleg.zitat_woertlich, beleg.fundstelle, beleg.verbindung.status)
        sicherungen = Sicherung.objects.count()
        self.pruefen(beleg)
        beleg.refresh_from_db()
        self.assertEqual((beleg.zitat_woertlich, beleg.fundstelle, beleg.verbindung.status), vorher)
        self.assertEqual(beleg.verbindung.status, Status.ENTWURF)
        self.assertEqual(Sicherung.objects.count(), sicherungen)  # mit gesicherter Kopie wird nichts geladen


class RechteTest(_Basis):
    def test_werkzeug_darf_pruefen(self):
        werkzeug = APIClient()
        werkzeug.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.konto).key}")
        self.assertEqual(self.pruefen(self.beleg(self.pdf_quelle(pdf_mit_text(SATZ))), werkzeug)["ergebnis"],
                         "gefunden")

    def test_nur_redaktion(self):
        beleg = self.beleg(self.pdf_quelle(pdf_mit_text(SATZ)))
        fremd = APIClient()
        fremd.force_authenticate(User.objects.create_user("fremd", "fremd@example.org", "pw"))
        self.assertEqual(fremd.post(f"/api/v1/akte/belege/{beleg.id}/pruefen/").status_code, 403)
        self.assertIn(APIClient().post(f"/api/v1/akte/belege/{beleg.id}/pruefen/").status_code, (401, 403))
        self.assertEqual(self.c.post("/api/v1/akte/belege/999999/pruefen/").status_code, 404)


@override_settings(AKTE_SICHERUNG_AKTIV=True)
class WebseitePruefenTest(_Basis):
    URL = "https://senat.beispiel.test/presse/vergabe"

    def test_text_der_seite_ohne_browser_und_original_gesichert(self):
        q = Quelle.objects.create(titel="Pressemitteilung", url=self.URL)
        with mock.patch("akte.zitatpruefung.abrufen", return_value=Abruf(self.URL, 200, "", SEITE.encode())) as laden:
            daten = self.pruefen(self.beleg(q))
        self.assertEqual(daten["ergebnis"], "gefunden", daten)
        self.assertIsNone(daten["fundstelle"]["seite"])
        self.assertIn("Webseite", daten["grund"])
        laden.assert_called_once()
        self.assertEqual(laden.call_args.args, (self.URL,))
        self.assertIsNotNone(laden.call_args.kwargs.get("frist"))
        self.assertEqual(q.sicherungen.filter(art="original", status="fertig").count(), 1)
        # Ein zweites Mal liest die Akte ihre Kopie und lädt nichts.
        with mock.patch("akte.zitatpruefung.abrufen") as laden:
            self.assertEqual(self.pruefen(self.beleg(q))["ergebnis"], "gefunden")
        laden.assert_not_called()

    def test_adresse_aus_der_anfrage_wird_nie_geladen(self):
        q = Quelle.objects.create(titel="Pressemitteilung", url=self.URL)
        with mock.patch("akte.zitatpruefung.abrufen", return_value=Abruf(self.URL, 200, "", SEITE.encode())) as laden:
            self.pruefen(self.beleg(q), url="http://metadaten.intern.beispiel.test/latest/meta-data/",
                         quelle_url="http://intern.beispiel.test/")
        self.assertEqual([aufruf.args for aufruf in laden.call_args_list], [(self.URL,)])

    def test_quelle_im_eigenen_netz_wird_nicht_abgerufen(self):
        q = Quelle.objects.create(titel="Intern", url="http://intern.beispiel.test/geheim")
        privat = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))]  # scrub:erlaubt (SSRF-Testadresse)
        with mock.patch("akte.abruf.socket.getaddrinfo", return_value=privat), \
                mock.patch.object(abruf.requests.Session, "get") as netz:
            daten = self.pruefen(self.beleg(q))
        self.assertEqual(daten["ergebnis"], "nicht_pruefbar")
        self.assertIn("nicht abrufbar", daten["grund"])
        netz.assert_not_called()
        self.assertFalse(q.sicherungen.exists())

    def test_seite_nicht_erreichbar(self):
        q = Quelle.objects.create(titel="Weg", url=self.URL)
        with mock.patch("akte.zitatpruefung.abrufen", side_effect=AbrufFehler("Die Seite antwortet mit 404.")):
            daten = self.pruefen(self.beleg(q))
        self.assertEqual(daten["ergebnis"], "nicht_pruefbar")
        self.assertIn("404", daten["grund"])

    def test_seite_ohne_text_ist_nicht_pruefbar(self):
        q = Quelle.objects.create(titel="App", url=self.URL)
        leer = b"<!doctype html><html><body><div id='app'></div><script>laden()</script></body></html>"
        with mock.patch("akte.zitatpruefung.abrufen", return_value=Abruf(self.URL, 200, "", leer)):
            daten = self.pruefen(self.beleg(q))
        self.assertEqual(daten["ergebnis"], "nicht_pruefbar")
        self.assertIn("JavaScript", daten["grund"])

    def test_seite_mit_anderem_wortlaut(self):
        q = Quelle.objects.create(titel="Pressemitteilung", url=self.URL)
        with mock.patch("akte.zitatpruefung.abrufen", return_value=Abruf(self.URL, 200, "", SEITE.encode())):
            daten = self.pruefen(self.beleg(q, "Der Senat lehnt jede Zusammenarbeit mit Nordlicht ab."))
        self.assertEqual(daten["ergebnis"], "nicht_gefunden")
        self.assertIn("JavaScript", daten["grund"])  # Hinweis auf die Grenze des Verfahrens

    def test_viele_gleichzeitige_abrufe_warten_nicht_ewig(self):
        q = Quelle.objects.create(titel="Pressemitteilung", url=self.URL)
        besetzt = mock.Mock()
        besetzt.acquire.return_value = False
        with mock.patch("akte.zitatpruefung._abrufe", besetzt), mock.patch("akte.zitatpruefung.abrufen") as laden:
            daten = self.pruefen(self.beleg(q))
        self.assertEqual(daten["ergebnis"], "nicht_pruefbar")
        self.assertIn("andere Quellen", daten["grund"])
        laden.assert_not_called()

    def test_vorhandene_kopie_wird_nie_ergaenzt(self):
        # E4: Die gesicherte Kopie ist gerade nicht lesbar (Datei fehlt). Geprüft wird am frisch geladenen Original,
        # abgelegt wird es nicht: Worauf sich der Beleg stützt, ändert eine Prüfung nicht.
        q = Quelle.objects.create(titel="Pressemitteilung", url=self.URL)
        Sicherung.objects.create(quelle=q, art="original", status="fertig", sha256="c" * 64,
                                 schluessel="beweise/" + "c" * 64 + ".html", mime="text/html")
        with mock.patch("akte.zitatpruefung.abrufen", return_value=Abruf(self.URL, 200, "", SEITE.encode())):
            daten = self.pruefen(self.beleg(q))
        self.assertEqual(daten["ergebnis"], "gefunden")
        self.assertIn("nicht gesichert", daten["grund"])
        self.assertEqual(q.sicherungen.count(), 1)

    def test_zu_viele_teile(self):
        q = Quelle.objects.create(titel="Pressemitteilung", url=self.URL)
        zitat = " […] ".join(f"Teil Nummer {i} des Zitats" for i in range(21))
        with mock.patch("akte.zitatpruefung.abrufen") as laden:
            daten = self.pruefen(self.beleg(q, zitat))
        self.assertEqual(daten["ergebnis"], "nicht_pruefbar")
        self.assertIn("zu viele Auslassungen", daten["grund"])
        laden.assert_not_called()

    def test_zitat_hoechstens_5000_zeichen(self):
        q = Quelle.objects.create(titel="Pressemitteilung", url=self.URL)
        antwort = self.c.post("/api/v1/akte/verbindungen/", {
            "von": self.a.id, "nach": self.b.id, "typ": "auftrag",
            "belege": [{"quelle": q.id, "zitat_woertlich": "x" * 5001}]}, format="json")
        self.assertEqual(antwort.status_code, 400)
        self.assertIn("5000", str(antwort.json()))

    @override_settings(AKTE_SICHERUNG_AKTIV=False)
    def test_ohne_beweissicherung_wird_nur_geprueft(self):
        q = Quelle.objects.create(titel="Pressemitteilung", url=self.URL)
        with mock.patch("akte.zitatpruefung.abrufen", return_value=Abruf(self.URL, 200, "", SEITE.encode())):
            daten = self.pruefen(self.beleg(q))
        self.assertEqual(daten["ergebnis"], "gefunden")
        self.assertIn("nicht gesichert", daten["grund"])
        self.assertFalse(q.sicherungen.exists())
