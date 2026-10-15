"""Board-Kennungen, die die Oberfläche selbst belegt (`/akte/einrichten`), bekommt keine Wand."""

import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework.test import APIClient

from akte.models import Board
from akte.permissions import REDAKTION_GRUPPE

User = get_user_model()


class SlugReserviertTest(TestCase):
    def setUp(self):
        konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.c = APIClient()
        self.c.force_authenticate(konto)

    def test_wunsch_slug_einrichten_ist_ein_400(self):
        antwort = self.c.post("/api/v1/akte/boards/", {"titel": "X", "slug": "einrichten"}, format="json")
        self.assertEqual(antwort.status_code, 400, antwort.content)
        self.assertIn("slug", antwort.json())
        self.assertFalse(Board.objects.filter(slug="einrichten").exists())

    def test_titel_einrichten_bekommt_freie_kennung(self):
        antwort = self.c.post("/api/v1/akte/boards/", {"titel": "Einrichten"}, format="json")
        self.assertEqual(antwort.status_code, 201, antwort.content)
        self.assertEqual(antwort.json()["slug"], "einrichten-2")

    def test_umbenennen_auf_einrichten_ist_ein_400(self):
        Board.objects.create(titel="Wand", slug="wand")
        antwort = self.c.patch("/api/v1/akte/boards/wand/", {"slug": "einrichten"}, format="json")
        self.assertEqual(antwort.status_code, 400, antwort.content)

    def test_import_mit_slug_einrichten_bricht_ab(self):
        paket = {"board": {"slug": "einrichten", "titel": "X"}}
        with tempfile.TemporaryDirectory() as ordner:
            datei = Path(ordner) / "paket.json"
            datei.write_text(json.dumps(paket), encoding="utf-8")
            with self.assertRaisesRegex(CommandError, "Oberfläche"):
                call_command("akte_import", str(datei))
        self.assertFalse(Board.objects.filter(slug="einrichten").exists())

    def test_gross_geschrieben_ist_auch_reserviert(self):
        # PR13: „Einrichten“ ist dieselbe Kennung für Menschen; die Prüfung vergleicht ohne Groß/Klein.
        antwort = self.c.post("/api/v1/akte/boards/", {"titel": "X", "slug": "Einrichten"}, format="json")
        self.assertEqual(antwort.status_code, 400, antwort.content)
        self.assertFalse(Board.objects.filter(slug__iexact="einrichten").exists())

    def test_systempruefung_warnt_vor_altem_board(self):
        # CR-9: ein Board aus 0.1 mit dieser Kennung (am Validator vorbei angelegt) – beim Start steht der Weg im Log.
        from akte.checks import board_kennung_reserviert

        self.assertEqual(board_kennung_reserviert(databases=["default"]), [])
        Board.objects.create(titel="Alt", slug="Einrichten")
        warnungen = board_kennung_reserviert(databases=["default"])
        self.assertEqual([w.id for w in warnungen], ["akte.W001"])
        self.assertIn("einrichten-alt", warnungen[0].hint)
        self.assertEqual(board_kennung_reserviert(databases=None), [])  # ohne Datenbank-Prüfung: nichts

    def test_validator_am_modellfeld(self):
        from django.core.exceptions import ValidationError

        for slug in ("einrichten", "EINRICHTEN"):
            with self.assertRaises(ValidationError):
                Board(titel="X", slug=slug).full_clean()
        Board(titel="X", slug="einrichten-2").full_clean()
