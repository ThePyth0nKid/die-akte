"""Die Demo-Akte: legt alles über die eigene API an, prüft Fundstellen, unterschreibt Freigaben."""

import io

from akte_beweis import pruefen, trace_pruefen
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import TestCase, override_settings

from akte import beweisschicht
from akte.management.commands.akte_demo import BILDER, KARTEN
from akte.models import Aussageart, Board, Entitaet, Ereignis, Sicherung, Status, Verbindung


@override_settings(AKTE_SICHERUNG_AKTIV=True, ALLOWED_HOSTS=["localhost"])
class DemoTest(TestCase):
    def test_demo_vollstaendig_und_kette_gueltig(self):
        with self.captureOnCommitCallbacks(execute=True):
            call_command("akte_demo", stdout=io.StringIO())
        board = Board.objects.get(slug="demo-musterhafen")
        self.assertEqual(board.karten.count(), 9)
        self.assertEqual(Verbindung.objects.count(), 9)
        self.assertEqual(Verbindung.objects.filter(status=Status.FREIGEGEBEN).count(), 6)
        # Alle drei Faden-Arten; der Verdacht bleibt Entwurf.
        arten = dict(Verbindung.objects.values_list("aussageart", "status").exclude(aussageart=Aussageart.BELEGT))
        self.assertEqual(arten, {Aussageart.VERDACHT: Status.ENTWURF, Aussageart.MEINUNG: Status.FREIGEGEBEN})
        fundstellen = Sicherung.objects.filter(art="fundstelle")
        self.assertEqual(fundstellen.filter(status="fertig").count(), 8)
        self.assertEqual(fundstellen.filter(status="fehler").count(), 1)  # das absichtlich falsche Zitat
        self.assertEqual(Ereignis.objects.filter(typ="akte.freigabe").count(), 15)
        export = beweisschicht.export()
        self.assertTrue(trace_pruefen(export["trace"], export["buendel"], strikte_kette=True).gueltig)
        self.assertTrue(pruefen(export["trace"], export["offenlegung"]).gueltig)
        self.assertEqual(board.fahrten.count(), 1)
        self.assertEqual(board.rahmen.count(), 3)

    def test_bilder_liegen_bei_und_sind_gekennzeichnet(self):
        with self.captureOnCommitCallbacks(execute=True):
            call_command("akte_demo", stdout=io.StringIO())
        namen = {schl: name for schl, name, *_ in KARTEN}
        for schl, (pfad, nachweis) in BILDER.items():
            with self.subTest(karte=schl):
                self.assertIsNotNone(finders.find(pfad.removeprefix("/static/")), f"{pfad} fehlt")
                e = Entitaet.objects.get(name=namen[schl])
                self.assertEqual((e.bild_url, e.bild_nachweis), (pfad, nachweis))
                # Fotos sind KI-Bilder und so gekennzeichnet; Logos und Wappen sind eigene Zeichnungen (SVG).
                self.assertRegex(nachweis, r"^KI-Bild · erfundene(s)? \w+$" if pfad.endswith(".webp")
                                 else r"^(Logo|Wappen): .*\(erfunden\) · eigene Zeichnung$")
        # Die Privatperson bleibt mit Absicht ohne Bild.
        self.assertEqual(Entitaet.objects.get(name="Thea Beispiel").bild_url, "")
        # Das Bild gehört zum unterschriebenen Inhalt: nach dem Anlegen ist keine Karte „seit der Freigabe verändert“.
        self.assertFalse(any(beweisschicht.veraendert_seit_freigabe(e, "karte") for e in Entitaet.objects.all()))

    def test_zweimal_braucht_neu(self):
        out = io.StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("akte_demo", stdout=out)
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("akte_demo", stdout=out)
        with self.captureOnCommitCallbacks(execute=True):
            call_command("akte_demo", "--neu", stdout=out)
        self.assertEqual(Board.objects.filter(slug="demo-musterhafen").count(), 1)
