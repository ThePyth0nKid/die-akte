"""Fundstellen, Seitenbild, Video-Meldung und Beweis-Stationen."""

import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from akte.models import Beleg, Board, BoardKarte, Entitaet, Quelle, Sicherung, Verbindung
from akte.permissions import REDAKTION_GRUPPE
from akte.rendern import (
    FundstelleMehrdeutig, _flach, _fund_im_dokument, _suchplaene, _zitat_stuecke, _zitat_suchtext, fundstelle_html,
    fundstelle_pdf,
)
from akte.sicherung import anhang_speichern, fundstelle_jetzt, seite_sichern

User = get_user_model()


def pdf_mit_seiten(*seiten: list[str], riesig: tuple[int, ...] = ()) -> bytes:
    """Kleinstes PDF, je Seite eine Liste von Textzeilen; pdfium repariert die Querverweise selbst.
    ``riesig``: Seitennummern mit übergroßem Format (die Suche überspringt sie, PDF_MAX_PIXEL)."""
    kinder = " ".join(f"{4 + 2 * n} 0 R" for n in range(len(seiten)))
    teile = [
        b"%PDF-1.4\n",
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        f"2 0 obj<</Type/Pages/Kids[{kinder}]/Count {len(seiten)}>>endobj\n".encode(),
        b"3 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n",
    ]
    for n, zeilen in enumerate(seiten):
        weitere = "".join(f" 0 -14 Td ({z}) Tj" for z in zeilen[1:])
        inhalt = f"BT /F1 12 Tf 60 700 Td ({zeilen[0]}) Tj{weitere} ET".encode("latin-1")
        seite, strom = 4 + 2 * n, 5 + 2 * n
        format_ = "0 0 595 4000" if n in riesig else "0 0 595 842"
        teile += [
            f"{seite} 0 obj<</Type/Page/Parent 2 0 R/MediaBox[{format_}]/Contents {strom} 0 R"
            "/Resources<</Font<</F1 3 0 R>>>>>>endobj\n".encode(),
            f"{strom} 0 obj<</Length {len(inhalt)}>>stream\n".encode() + inhalt + b"\nendstream endobj\n",
        ]
    teile.append(b"trailer<</Root 1 0 R>>\n%%EOF")
    return b"".join(teile)


def pdf_mit_text(text: str, *weitere_zeilen: str) -> bytes:
    """Kleinstes PDF mit einer Seite und einer oder mehreren Textzeilen."""
    return pdf_mit_seiten([text, *weitere_zeilen])


TRENNUNG = chr(0xFFFE)  # so liefert pdfium eine Silbentrennung am Zeilenende im Seitentext


ZITAT = "Bereits 2017 hatte Musterhafen das Programm Polarstern erworben"


class RendernTest(TestCase):
    def test_suchtext(self):
        self.assertEqual(_zitat_suchtext("„Bereits 2017 hatte Musterhafen …“"), "Bereits 2017 hatte Musterhafen")
        lang = "Wort " * 40
        self.assertLessEqual(len(_zitat_suchtext(lang)), 90)

    def test_fundstelle_pdf_markiert(self):
        bild = fundstelle_pdf(pdf_mit_text(ZITAT), ZITAT)
        self.assertIsNotNone(bild)
        self.assertTrue(bild.startswith(b"\xff\xd8"))
        self.assertIsNone(fundstelle_pdf(pdf_mit_text(ZITAT), "Dieser Satz steht nirgends im Dokument"))

    def test_suchtext_endet_vor_auslassung(self):
        # 07.10.2026, Drs. 9/1234: „protokolliert. [“ blieb stehen, die Suche fand nichts.
        for zitat in ("Zudem werden Inhalte nicht protokolliert. […] Es gibt keine Pflicht",
                      "Zudem werden Inhalte nicht protokolliert. [...] Es gibt keine Pflicht"):
            self.assertEqual(_zitat_suchtext(zitat), "Zudem werden Inhalte nicht protokolliert.")

    def test_flach_trennung_umbruch_und_bindestrich(self):
        flach, index = _flach(f"Bren{TRENNUNG}de, im\r\nBund")
        self.assertEqual(flach, "brende, im bund")
        self.assertEqual(index[4], 5)  # „d“ steht im Original hinter der Trennung
        self.assertEqual(_flach("„Social-\r\nMedia“")[0], '"social- media"')
        self.assertEqual(_flach("Social-\r\nMedia", "klebt")[0], "social-media")
        self.assertEqual(_flach("Bundes-\r\nregierung", "weg")[0], "bundesregierung")

    def test_fundstelle_pdf_ueber_zeilenumbruch(self):
        # Parlaments-Drucksachen trennen am Zeilenende; pdfiums eigene Suche fand solche Zitate nicht.
        zitat = "Am 12. Oktober 2022 empfing der Minister Herrn Brende, im Bundesministerium"
        pdf = pdf_mit_text("Am 12. Oktober 2022 empfing der Minister Herrn Bren-", "de, im Bundesministerium fuer Wirtschaft.")
        self.assertIsNotNone(fundstelle_pdf(pdf, zitat))
        self.assertIsNotNone(fundstelle_pdf(pdf_mit_text("Bereits 2017 hatte Musterhafen", "das Programm Polarstern erworben"), ZITAT))
        self.assertIsNone(fundstelle_pdf(pdf, "Am 12. Oktober 2022 empfing der Minister Herrn Brende, im Kanzleramt"))

    def _fund(self, pdf: bytes, zitat: str):
        """(Seite, erstes Zeichen, markierter Text, Volltext der Seite) oder (None, -1, "", "")."""
        import pypdfium2 as pdfium

        dokument = pdfium.PdfDocument(pdf)
        try:
            fund = _fund_im_dokument(dokument, zitat)
            if not fund:
                return None, -1, "", ""
            nummer, start, anzahl = fund
            text = dokument[nummer].get_textpage()
            return (nummer, start, text.get_text_range(start, anzahl, force_this=True),
                    text.get_text_range(0, text.count_chars(), force_this=True))
        finally:
            dokument.close()

    def test_unscharfe_spanne_deckt_genau_das_zitat(self):
        zitat = "Am 12. Oktober 2022 empfing der Minister Herrn Brende, im Bundesministerium"
        nummer, _, spanne, voll = self._fund(pdf_mit_text("Vorher. Am 12. Oktober 2022 empfing der Minister Herrn Bren-",
                                                          "de, im Bundesministerium fuer Wirtschaft."), zitat)
        self.assertEqual(nummer, 0)
        self.assertIn(TRENNUNG, voll)  # pdfium liefert die Trennung am Zeilenende als U+FFFE (Punkt 4c)
        self.assertEqual(_flach(spanne, "weg")[0], _flach(zitat)[0])

    def test_zitat_auf_zwei_seiten_ist_mehrdeutig(self):
        # Seite 1 getrennt, Seite 2 glatt, beide mit demselben Wortlaut: nicht eindeutig → keine Fundstelle.
        zitat = "Am 12. Oktober 2022 empfing der Minister Herrn Brende, im Bundesministerium"
        pdf = pdf_mit_seiten(["Am 12. Oktober 2022 empfing der Minister Herrn Bren-", "de, im Bundesministerium."],
                             [zitat])
        self.assertIsNone(self._fund(pdf, zitat)[0])

    def test_auslassung_mit_kurzen_stuecken_ergibt_keine_fundstelle(self):
        # Review 07.10.2026 (HOCH): „Die Bundesregierung […] hat zugestimmt“ hätte die erste Stelle mit
        # „Die Bundesregierung“ markiert. Stücke unter 25 Zeichen tragen keine Fundstelle.
        pdf = pdf_mit_text("Die Bundesregierung hat den Antrag abgelehnt.",
                           "Die Bundesregierung hat nach langer Pruefung zugestimmt.")
        for zitat in ("Die Bundesregierung […] hat zugestimmt", "Die Bundesregierung ... hat zugestimmt"):
            self.assertEqual(_zitat_suchtext(zitat), "")
            self.assertIsNone(fundstelle_pdf(pdf, zitat))

    def test_auslassung_trifft_nur_die_vollstaendige_stelle(self):
        # Punkt 4a: Beide Absätze beginnen gleich, nur der zweite enthält auch das Stück nach der Auslassung.
        erster = "Die Bundesregierung hat den Antrag geprueft und abgelehnt."
        zweiter = "Die Bundesregierung hat den Antrag geprueft, beraten und am Ende ausdruecklich zugestimmt."
        nummer, start, spanne, voll = self._fund(
            pdf_mit_text(erster, zweiter),
            "Die Bundesregierung hat den Antrag geprueft […] und am Ende ausdruecklich zugestimmt")
        marke = "Die Bundesregierung hat den Antrag geprueft, beraten"  # nur im zweiten Absatz
        self.assertEqual(nummer, 0)
        self.assertGreaterEqual(start, voll.index(marke))  # nie der erste Absatz
        nummer, start, _, voll = self._fund(
            pdf_mit_text(erster, "Etwas anderes dazwischen.", zweiter),
            "Die Bundesregierung hat den Antrag geprueft, beraten […] und am Ende ausdruecklich zugestimmt")
        self.assertEqual(start, voll.index(marke))  # erstes Stück ist eindeutig → Markierung am Anfang

    def test_auslassung_ueber_den_seitenumbruch(self):
        # 07.10.2026: „[…]“ verbindet oft Stellen auf zwei Seiten (Drs. 9/1234 S. 3/4, UN-Resolution). Reihenfolge
        # im Dokument zählt; steht das zweite Stück nur VOR dem Anker, ist es kein Beleg für diese Stelle.
        anfang = "Zudem werden Gespraechsinhalte nicht protokolliert."
        weiter = "Es gibt seitens der Bundesregierung keine weiteren Erkenntnisse."
        zitat = f"{anfang} […] {weiter}"
        nummer, start, _, voll = self._fund(pdf_mit_seiten([anfang, "Seitenende."], ["Kopfzeile.", weiter]), zitat)
        self.assertEqual((nummer, start), (0, voll.index(anfang)))
        self.assertIsNone(self._fund(pdf_mit_seiten([weiter], [anfang]), zitat)[0])

    @staticmethod
    def _fuellseite(n: int) -> list[str]:
        return [f"Fuelltext auf Seite {n}, Zeile {k}, ohne jeden Bezug zum gesuchten Zitat und ohne Wiederholung." for k in range(10)]

    def test_folgestueck_zu_weit_weg(self):
        # Zweites Review 07.10.2026: Anker S. 1, Folgestück erst S. 30 → keine Fundstelle (Höchstdistanz).
        anfang = "Zudem werden Gespraechsinhalte nicht protokolliert."
        weiter = "Es gibt seitens der Bundesregierung keine weiteren Erkenntnisse."
        seiten = [[anfang]] + [self._fuellseite(n) for n in range(2, 30)] + [[weiter]]
        self.assertIsNone(self._fund(pdf_mit_seiten(*seiten), f"{anfang} […] {weiter}")[0])

    def test_fernstelle_bestaetigt_keine_falsche_ankerstelle(self):
        # Anker auf S. 1 und S. 20; das Folgestück steht nur gleich hinter dem auf S. 20. Ohne Höchstdistanz hätte es
        # auch S. 1 „bestätigt“ (mehrdeutig); mit ihr ist S. 20 eindeutig.
        anfang = "Zudem werden Gespraechsinhalte nicht protokolliert."
        weiter = "Es gibt seitens der Bundesregierung keine weiteren Erkenntnisse."
        seiten = [[anfang, "Anderer Satz."]] + [self._fuellseite(n) for n in range(2, 20)] + [[anfang, weiter]]
        nummer, start, _, voll = self._fund(pdf_mit_seiten(*seiten), f"{anfang} […] {weiter}")
        self.assertEqual((nummer, start), (19, voll.index(anfang)))

    def test_kopfzeile_auf_jeder_seite_als_stueck(self):
        # Erstes Stück ist eine Kopfzeile (auf jeder Seite) → als Anker mehrdeutig; Ersatz-Anker ist der Satz auf S. 3,
        # die Kopfzeile davor bestätigt ihn nur in Reichweite.
        kopf = "Resolution adopted by the General Assembly on 25 September 2015"
        satz = "We are announcing today seventeen goals with many associated targets."
        pdf = pdf_mit_seiten([kopf, "Erste Seite."], [kopf, "Zweite Seite."], [kopf, satz])
        nummer, start, _, voll = self._fund(pdf, f"{kopf} […] {satz}")
        self.assertEqual((nummer, start), (2, voll.index(satz)))

    def test_ersatz_anker_der_reihe_nach(self):
        kurz, mittel = "Die Regierung", "hat den Antrag ausfuehrlich geprueft"
        lang = "und am Ende nach langer Beratung ausdruecklich zugestimmt"
        plaene = _suchplaene(f"{kurz} […] {mittel} […] {lang}")
        self.assertEqual([p.anker for p in plaene], [lang, mittel])  # erstes Stück zu kurz → längstes, dann nächstes
        self.assertEqual(plaene[0].davor, (_flach(mittel)[0],))

    def test_zitat_nur_aus_auslassung_und_randzeichen(self):
        for zitat in ("…", "[…]", "„ … “"):
            self.assertEqual((_suchplaene(zitat), _zitat_suchtext(zitat)), ([], ""))
            self.assertIsNone(fundstelle_pdf(pdf_mit_text(ZITAT), zitat))
        self.assertEqual(_zitat_stuecke(f"”{ZITAT}’")[0], [ZITAT])

    def test_uebersprungene_seite_verlangt_bestaetigung(self):
        # Zweites Review 07.10.2026: Eindeutig heißt nur „auf den gelesenen Seiten“. Ist eine Seite zu groß und wurde
        # übersprungen, reicht ein kurzes Zitat ohne weiteres Stück nicht; ein langes mit bestätigtem Ende schon.
        self.assertIsNone(self._fund(pdf_mit_seiten([ZITAT], ["Riesige Seite."], riesig=(1,)), ZITAT)[0])
        lang = ("Der Ausschuss hat in seiner Sitzung am 12. Mai 2024 die Vorlage ausfuehrlich beraten und mit grosser "
                "Mehrheit beschlossen, das Verfahren einzustellen.")
        self.assertEqual(self._fund(pdf_mit_seiten([lang], ["Riesige Seite."], riesig=(1,)), lang)[0], 0)

    def _seite_nicht_treu(self, nummer: int):
        """Seite ``nummer`` so behandeln, als passten ihre Indizes nicht zum Volltext (z. B. Zeichen außerhalb der BMP)."""
        from akte import rendern

        original = rendern._Seite.__init__

        def init(seite, dokument, n):
            original(seite, dokument, n)
            if n == nummer:
                seite.treu = False

        return mock.patch.object(rendern._Seite, "__init__", init)

    def test_nicht_treue_seite_kurzes_zitat(self):
        # Drittes Review 07.10.2026: S. 2 nicht treu, dort steht das Zitat nur getrennt (unscharf, also unsichtbar).
        # Ohne Bestätigung durch weitere Stücke oder das Zitatende → keine Fundstelle.
        pdf = pdf_mit_seiten([ZITAT], ["Bereits 2017 hatte Musterhafen das Pro-", "gramm Polarstern erworben"])
        with self._seite_nicht_treu(1):
            self.assertIsNone(self._fund(pdf, ZITAT)[0])

    def test_nicht_treue_seite_verschluckt_kein_zweites_vorkommen(self):
        # Gleiches Zitat mit Folgestück auf S. 1 (treu) und S. 2 (nicht treu): S. 2 ist nicht prüfbar, bleibt aber
        # Kandidat → mehrdeutig → keine Fundstelle. Früher fiel S. 2 still heraus und S. 1 galt als eindeutig.
        anfang = "Zudem werden Gespraechsinhalte nicht protokolliert."
        weiter = "Es gibt seitens der Bundesregierung keine weiteren Erkenntnisse."
        pdf = pdf_mit_seiten([anfang, weiter], [anfang, weiter])
        with self._seite_nicht_treu(1):
            self.assertIsNone(self._fund(pdf, f"{anfang} […] {weiter}")[0])
        nummer, start, _, voll = self._fund(pdf_mit_seiten([anfang, weiter], ["Anderes."]), f"{anfang} […] {weiter}")
        self.assertEqual((nummer, start), (0, voll.index(anfang)))  # Gegenprobe: eine treue Stelle allein trifft

    def test_zwei_treffer_auf_derselben_seite(self):
        # Punkt 4b: gleicher Anfang zweimal auf einer Seite. Ohne Unterschied → keine Fundstelle; mit
        # unterschiedlichem Ende (Zitat länger als der Suchtext) entscheidet das Zitatende.
        kurz = "Bereits 2017 hatte Musterhafen das Programm Polarstern erworben"
        self.assertIsNone(self._fund(pdf_mit_text(kurz, "Dazwischen steht etwas.", kurz), kurz)[0])
        anfang = "Der Ausschuss hat in seiner Sitzung am 12. Mai 2024 die Vorlage ausfuehrlich beraten und mit grosser Mehrheit"
        falsch = f"{anfang} beschlossen, das Verfahren fortzusetzen, weil noch viele weitere Unterlagen fehlen."
        richtig = f"{anfang} beschlossen, das Verfahren einzustellen."
        nummer, start, _, voll = self._fund(pdf_mit_text(falsch, richtig), richtig)
        self.assertEqual((nummer, start), (0, voll.index(richtig)))

    def test_kurzer_suchtext_nur_exakt(self):
        # Unter 25 Zeichen wird nicht unscharf gesucht: „Herrn Brende“ träfe sonst beliebige Stellen.
        pdf = pdf_mit_text("empfing der Minister Herrn Bren-", "de, im Bundesministerium.")
        self.assertIsNone(fundstelle_pdf(pdf, "Minister Herrn Brende"))
        self.assertIsNotNone(fundstelle_pdf(pdf_mit_text("empfing der Minister Herrn Brende"), "Minister Herrn Brende"))


class HtmlFundstelleTest(SimpleTestCase):
    """Webseiten-Weg mit echtem Chromium: nur Adressprüfung und Seitenaufbau sind ersetzt, die Mehrdeutigkeit kommt aus
    dem JavaScript in ``_MARKIEREN``. Ohne installierten Chromium wird übersprungen."""

    _chromium: bool | None = None

    def setUp(self):
        if HtmlFundstelleTest._chromium is None:
            try:
                from playwright.sync_api import sync_playwright

                from akte.rendern import _browser_schleife

                with _browser_schleife(), sync_playwright() as pw:
                    pw.chromium.launch().close()
                HtmlFundstelleTest._chromium = True
            except Exception:  # noqa: BLE001 — kein Browser in dieser Umgebung
                HtmlFundstelleTest._chromium = False
        if not HtmlFundstelleTest._chromium:
            self.skipTest("Playwright-Chromium nicht installiert")

    def _html(self, inhalt: str, zitat: str):
        def seite_bauen(pw, url, proxy):
            browser = pw.chromium.launch()
            seite = browser.new_page(viewport={"width": 1280, "height": 900})
            seite.set_content(inhalt)
            return browser, seite

        with mock.patch("akte.rendern.pruefe_url"), mock.patch("akte.rendern._browser_seite", side_effect=seite_bauen):
            return fundstelle_html("https://x.example/", zitat)

    def test_eindeutig_markiert_mehrdeutig_meldet(self):
        satz = "Die Bundesregierung hat am Ende ausdruecklich zugestimmt."
        self.assertTrue(self._html(f"<p>Vorher.</p><p>{satz}</p>", satz).startswith(b"\xff\xd8"))
        with self.assertRaises(FundstelleMehrdeutig):
            self._html(f"<p>{satz}</p><p>Mitte</p><p>{satz}</p>", satz)
        self.assertIsNone(self._html("<p>Nichts davon.</p>", satz))
        self.assertIsNone(self._html(f"<p>{satz}</p>", "Die Bundesregierung […] zugestimmt"))  # Stücke zu kurz


class _Speicher(TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.einst = override_settings(AKTE_SPEICHER_LOKAL=self.ordner, AKTE_R2_BUCKET="")
        self.einst.enable()

    def tearDown(self):
        self.einst.disable()
        shutil.rmtree(self.ordner, ignore_errors=True)


class FundstelleTest(_Speicher):
    def _beleg(self, quelle, zitat=ZITAT):
        a = Entitaet.objects.create(name="Land Musterhafen", slug="musterhafen", typ="behoerde")
        b = Entitaet.objects.create(name="Nordlicht", slug="nordlicht", typ="firma")
        v = Verbindung.objects.create(von=a, nach=b, typ="auftrag")
        return Beleg.objects.create(verbindung=v, quelle=quelle, zitat_woertlich=zitat)

    def test_pdf_fundstelle_ohne_browser(self):
        q = Quelle.objects.create(titel="VerfGH")
        anhang_speichern(q, pdf_mit_text(ZITAT), "urteil.pdf")
        beleg = self._beleg(q)
        self.assertEqual(fundstelle_jetzt(beleg), "pdf")
        s = Sicherung.objects.get(art="fundstelle")
        self.assertEqual((s.status, s.beleg_id, s.mime), ("fertig", beleg.id, "image/jpeg"))

    def test_webseite_geht_an_den_browser(self):
        q = Quelle.objects.create(titel="Seite", url="https://x.example/")
        self.assertEqual(fundstelle_jetzt(self._beleg(q)), "browser")

    def test_seitenbild_und_pdf(self):
        q = Quelle.objects.create(titel="Seite", url="https://x.example/")
        import io

        from PIL import Image

        puffer = io.BytesIO()
        Image.new("RGB", (1280, 4000), (240, 240, 240)).save(puffer, "JPEG")
        with mock.patch("akte.rendern.seite_rendern", return_value=(puffer.getvalue(), b"%PDF-1.4 x")):
            seite_sichern(q)
        self.assertEqual(sorted(q.sicherungen.values_list("art", flat=True)), ["screenshot", "seite_pdf", "vorschau"])
        self.assertLess(q.sicherungen.get(art="vorschau").bytes, 60_000)

    def test_browserfehler_wird_festgehalten(self):
        q = Quelle.objects.create(titel="Seite", url="https://x.example/")
        with mock.patch("akte.rendern.seite_rendern", side_effect=RuntimeError("Timeout")):
            seite_sichern(q)
        self.assertEqual(q.sicherungen.get().status, "fehler")


class ApiTest(_Speicher):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        u = User.objects.create_user(username="redaktion", email="redaktion@example.org", password="pw")
        u.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.client.force_authenticate(u)

    def test_video_meldung(self):
        q = Quelle.objects.create(titel="Larsen", url="https://www.youtube.com/watch?v=AbCdEfGhIjK")
        falsch = self.client.post(f"/api/v1/akte/quellen/{q.id}/video-lokal/", {"pfad": "/archiv/x.mp4", "sha256": "abc"}, format="json")
        self.assertEqual(falsch.status_code, 400)
        gut = self.client.post(f"/api/v1/akte/quellen/{q.id}/video-lokal/", {
            "pfad": "/archiv/akte/4/larsen.mp4", "sha256": "a" * 64, "bytes": 1000, "zeitmarke": "70:31"},
            format="json")
        self.assertEqual(gut.status_code, 201)
        self.assertEqual(q.sicherungen.get().art, "video_lokal")

    def test_fahrt_mit_beweis_station(self):
        board = Board.objects.create(titel="P", slug="p")
        e = Entitaet.objects.create(name="VerfGH", slug="verfgh", typ="behoerde")
        BoardKarte.objects.create(board=board, entitaet=e)
        q = Quelle.objects.create(titel="Urteil vom 16.02.2023, 2 VR 12/24")
        antwort = self.client.post("/api/v1/akte/boards/p/fahrten/aus-beschreibung/", {
            "titel": "K6", "stationen": [{"fokus": ["VerfGH"], "beweis": "2 VR 12/24", "zitat": ZITAT}]}, format="json")
        self.assertEqual(antwort.status_code, 201, antwort.content)
        station = antwort.json()["stationen"][0]
        self.assertEqual((station["beweis_quelle"], station["beweis_zitat"]), (q.id, ZITAT))
        falsch = self.client.post("/api/v1/akte/boards/p/fahrten/aus-beschreibung/", {
            "titel": "K7", "stationen": [{"fokus": [], "beweis": "gibt es nicht"}]}, format="json")
        self.assertEqual(falsch.status_code, 400)

    def test_fahrt_mit_falschen_zahlen_ist_400(self):
        board = Board.objects.create(titel="Q", slug="q")
        e = Entitaet.objects.create(name="X", slug="x", typ="firma")
        BoardKarte.objects.create(board=board, entitaet=e)
        for station in ({"fokus": ["X"], "dauer_ms": "abc"}, {"fokus": ["X"], "zoom": "abc"}, {"fokus": ["X"], "dauer_ms": None}):
            antwort = self.client.post("/api/v1/akte/boards/q/fahrten/aus-beschreibung/",
                                       {"titel": "F", "stationen": [station]}, format="json")
            self.assertEqual(antwort.status_code, 400, station)
