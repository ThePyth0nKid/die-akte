"""Der Import legt alles als Entwurf an und ist wiederholbar."""

import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from akte.models import Beleg, Board, Entitaet, Status, Verbindung

START = {
    "board": {"titel": "Nordlicht", "slug": "nordlicht"},
    "quellen": [{"schluessel": "verfgh", "titel": "VerfGH 2 VR 12/24", "url": "https://verfgh.beispiel.test/x",
                 "abgerufen_am": "2026-09-19", "guete": "primaer"}],
    "entitaeten": [
        {"schluessel": "nordlicht", "typ": "firma", "name": "Nordlicht", "x": 0, "y": 0},
        {"schluessel": "musterhafen", "typ": "behoerde", "name": "Polizei Musterhafen", "x": 400, "y": 0},
    ],
    "verbindungen": [{"von": "musterhafen", "nach": "nordlicht", "typ": "auftrag", "beschreibung": "kauft Polarstern",
                      "start": "2017-01-01", "aktuell": True,
                      "belege": [{"quelle": "verfgh", "zitat_woertlich": "Bereits 2017 …", "fundstelle": "Rn. 7"}]}],
}


class ImportTest(TestCase):
    def test_import_legt_entwurf_an_und_ist_wiederholbar(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "start.json"
            pfad.write_text(json.dumps(START), encoding="utf-8")
            call_command("akte_import", str(pfad))
            call_command("akte_import", str(pfad))
        self.assertEqual(Entitaet.objects.count(), 2)
        self.assertEqual(Verbindung.objects.count(), 1)
        self.assertEqual(Beleg.objects.count(), 1)
        self.assertEqual(Board.objects.get(slug="nordlicht").karten.count(), 2)
        self.assertFalse(Entitaet.objects.exclude(status=Status.ENTWURF).exists())

    def _laden(self, *verbindungen):
        paket = {**START, "verbindungen": [{**START["verbindungen"][0], **v} for v in verbindungen]}
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "paket.json"
            pfad.write_text(json.dumps(paket), encoding="utf-8")
            call_command("akte_import", str(pfad), stdout=io.StringIO())

    def test_zeitraum_mit_start_bis_aktuell(self):
        # G70: Startdatum, Ende („bis“) und „besteht noch“ kommen mit dem Import, nicht von Hand danach.
        self._laden({"start": "2017-01-01", "bis": "2020-12-31", "aktuell": False},
                    {"beschreibung": "berät", "typ": "lobby", "start": "2021-03-01", "aktuell": True})
        alt = Verbindung.objects.get(beschreibung="kauft Polarstern")
        neu = Verbindung.objects.get(beschreibung="berät")
        self.assertEqual((str(alt.start), str(alt.ende), alt.aktuell), ("2017-01-01", "2020-12-31", False))
        self.assertEqual((str(neu.start), neu.ende, neu.aktuell), ("2021-03-01", None, True))

    def test_ungueltiger_zeitraum_schreibt_nichts(self):
        for falsch in ({"start": "2017"}, {"start": "01.03.2021"}, {"bis": "2021-02-30", "aktuell": False},
                       {"aktuell": "ja"}, {"bis": "2020-12-31", "aktuell": True},
                       {"start": "2021-01-01", "bis": "2020-12-31", "aktuell": False},
                       {"bis": "2020-12-31", "ende": "2019-01-01", "aktuell": False}):
            with self.assertRaises(CommandError, msg=falsch):
                self._laden(falsch)
        self.assertFalse(Verbindung.objects.exists())
        self.assertFalse(Entitaet.objects.exists())

    def test_leeres_bis_zaehlt_wie_keines(self):
        # PR14: wie im MCP-Client: „bis“ leer, „ende“ gesetzt → kein Widerspruch, „ende“ gilt.
        self._laden({"start": "2017-01-01", "bis": "", "ende": "2020-12-31", "aktuell": False})
        self.assertEqual(str(Verbindung.objects.get().ende), "2020-12-31")

    def test_zu_langes_zitat_bricht_ab(self):
        with self.assertRaisesRegex(CommandError, "5000"):
            self._laden({"belege": [{"quelle": "verfgh", "zitat_woertlich": "x" * 5001}]})
        self.assertFalse(Verbindung.objects.exists())
