"""Der Import legt alles als Entwurf an und ist wiederholbar."""

import json
import tempfile
from pathlib import Path

from django.core.management import call_command
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
