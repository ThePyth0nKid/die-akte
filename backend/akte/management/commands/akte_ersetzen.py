"""Alle Daten der Akte durch eine Fixture ersetzen (z. B. eine zweite Instanz auf einen exportierten Stand bringen).

    python manage.py akte_ersetzen stand.json --trocken
    python manage.py akte_ersetzen stand.json --ja

Warum ein eigener Befehl: ``loaddata`` überschreibt nur nach ID und löscht nichts. Es blieben sonst alte Rahmen
stehen (``gruppen`` legt Rahmen neu an) und daneben Beweis-Stücke, die es im neuen Stand nicht mehr gibt.
Hier passiert alles in EINER Transaktion: löschen, laden, zählen. Scheitert etwas, bleibt der alte Stand.
``--trocken`` macht dasselbe und rollt am Ende zurück. Der Verlauf (wer hat wann was geändert) bleibt stehen.
Vorher sichern: ``python manage.py dumpdata akte > akte_vorher.json``.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from akte.models import (
    Beleg,
    Board,
    BoardBeweis,
    BoardKarte,
    Entitaet,
    Fahrt,
    Mappe,
    Quelle,
    Rahmen,
    Sicherung,
    Station,
    Verbindung,
    Zettel,
)

# Reihenfolge: Abhängiges zuerst (Beleg → Quelle ist PROTECT).
LOESCHEN = [Station, Fahrt, Sicherung, BoardBeweis, Beleg, Mappe, Zettel, Rahmen, BoardKarte, Board, Verbindung,
            Quelle, Entitaet]
ZAEHLEN = [Board, Entitaet, Verbindung, Beleg, Quelle, BoardKarte, Rahmen, Zettel, Mappe, BoardBeweis, Fahrt]


class _Zurueckrollen(Exception):
    pass


def zaehlen() -> dict[str, int]:
    return {m.__name__: m.objects.count() for m in ZAEHLEN}


class Command(BaseCommand):
    help = "Ersetzt alle Akte-Daten durch eine Fixture, in einer Transaktion."

    def add_arguments(self, parser):
        parser.add_argument("fixture")
        parser.add_argument("--trocken", action="store_true", help="Alles durchspielen und zurückrollen.")
        parser.add_argument("--ja", action="store_true", help="Wirklich ersetzen.")

    def handle(self, fixture, trocken, ja, **_):
        if not (trocken or ja):
            raise CommandError("Ohne --trocken oder --ja ändert der Befehl nichts. Vorher: dumpdata akte sichern.")
        self.stdout.write(f"Vorher: {zaehlen()}")
        try:
            with transaction.atomic():
                for modell in LOESCHEN:
                    modell.objects.all().delete()
                call_command("loaddata", fixture, verbosity=0)
                nachher = zaehlen()
                boards = sorted(Board.objects.values_list("slug", "oeffentlich"))
                if trocken:
                    raise _Zurueckrollen
        except _Zurueckrollen:
            self.stdout.write(f"Trocken (zurückgerollt), so würde es: {nachher}")
            self.stdout.write(f"Boards (slug, öffentlich): {boards}")
            return
        self.stdout.write(self.style.SUCCESS(f"Ersetzt: {nachher}"))
        self.stdout.write(f"Boards (slug, öffentlich): {boards}")
