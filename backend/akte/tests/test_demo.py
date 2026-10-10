"""Die Demo-Akte: legt alles über die eigene API an, prüft Fundstellen, unterschreibt Freigaben."""

import io

from akte_beweis import pruefen, trace_pruefen
from django.core.management import call_command
from django.test import TestCase, override_settings

from akte import beweisschicht
from akte.models import Board, Ereignis, Sicherung, Status, Verbindung


@override_settings(AKTE_SICHERUNG_AKTIV=True, ALLOWED_HOSTS=["localhost"])
class DemoTest(TestCase):
    def test_demo_vollstaendig_und_kette_gueltig(self):
        with self.captureOnCommitCallbacks(execute=True):
            call_command("akte_demo", stdout=io.StringIO())
        board = Board.objects.get(slug="demo-musterhafen")
        self.assertEqual(board.karten.count(), 8)
        self.assertEqual(Verbindung.objects.count(), 7)
        self.assertEqual(Verbindung.objects.filter(status=Status.FREIGEGEBEN).count(), 5)
        fundstellen = Sicherung.objects.filter(art="fundstelle")
        self.assertEqual(fundstellen.filter(status="fertig").count(), 6)
        self.assertEqual(fundstellen.filter(status="fehler").count(), 1)  # das absichtlich falsche Zitat
        self.assertEqual(Ereignis.objects.filter(typ="akte.freigabe").count(), 13)
        export = beweisschicht.export()
        self.assertTrue(trace_pruefen(export["trace"], export["buendel"], strikte_kette=True).gueltig)
        self.assertTrue(pruefen(export["trace"], export["offenlegung"]).gueltig)
        self.assertEqual(board.fahrten.count(), 1)
        self.assertEqual(board.rahmen.count(), 3)

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
