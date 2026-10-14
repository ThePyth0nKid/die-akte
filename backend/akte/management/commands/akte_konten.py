"""Welche Konten dürfen an der Akte arbeiten? Für Starter-Skripte, maschinenlesbar.

    python manage.py akte_konten            # je Konto eine Zeile „KONTO:name“
    python manage.py akte_konten --json     # {"konten": ["anna", …]}

Gezählt werden aktive Konten der Redaktionsgruppe und aktive Superuser, genau wie bei der Einrichtung
(``permissions.redaktionskonten``). Gibt nur Namen aus, nie Passwörter oder Tokens.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from akte.permissions import redaktionskonten


class Command(BaseCommand):
    help = "Listet die aktiven Konten, die an der Akte arbeiten dürfen (Redaktion oder Superuser)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="als JSON-Objekt {\"konten\": [...]}")

    def handle(self, *args, **opts):
        namen = list(redaktionskonten().values_list("username", flat=True))
        if opts["json"]:
            self.stdout.write(json.dumps({"konten": namen}, ensure_ascii=False))
            return
        for name in namen:
            self.stdout.write(f"KONTO:{name}")
