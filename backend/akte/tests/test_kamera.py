"""Kamera-Rechnung für Fahrten aus einer Beschreibung."""

from django.test import SimpleTestCase

from akte.kamera import FORMATE, FUELLUNG, ZOOM_MAX, bild_fuer, format_name, karten_rechteck


class KameraTest(SimpleTestCase):
    def test_formate_und_schreibweisen(self):
        self.assertEqual(format_name("16x9"), "16:9")
        self.assertEqual(format_name("9:16"), "9:16")
        self.assertEqual(format_name("oben"), "oben")
        self.assertEqual(format_name("1x1"), "1:1")
        self.assertIsNone(format_name("4:3"))

    def test_fokus_fuellt_die_sichere_flaeche(self):
        rechtecke = [karten_rechteck(0, 0), karten_rechteck(400, 0)]
        for name, (breite, hoehe) in FORMATE.items():
            with self.subTest(format=name):
                b = bild_fuer(rechtecke, name)
                umriss_b = (620 + 28) * b.zoom
                umriss_h = (380 + 28) * b.zoom
                fuellung = max(umriss_b / breite, umriss_h / hoehe)
                self.assertAlmostEqual(fuellung, FUELLUNG, delta=0.01)
                self.assertLessEqual(umriss_b, breite)
                self.assertLessEqual(umriss_h, hoehe)

    def test_einzelne_karte_ohne_bild_wird_nah_gerahmt(self):
        b = bild_fuer([karten_rechteck(0, 0, mit_bild=False)], "16:9")
        self.assertEqual(b.zoom, ZOOM_MAX)
        self.assertGreater(26 * b.zoom, 40)  # Kartentitel über 40 px

    def test_mittelpunkt(self):
        b = bild_fuer([(0, 0, 200, 100), (800, 400, 200, 100)], "16:9")
        self.assertEqual((b.x, b.y), (500, 250))
