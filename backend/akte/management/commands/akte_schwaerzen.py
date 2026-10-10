"""Inhalte aus der Beweiskette schwärzen, etwa nach einer Unterlassungsverfügung oder einem berechtigten Löschwunsch.

    python manage.py akte_schwaerzen --faden 12            # alle Freigaben dieses Fadens
    python manage.py akte_schwaerzen --karte 7             # alle Freigaben dieser Karte
    python manage.py akte_schwaerzen --quelle 3            # alle Sicherungen dieser Quelle
    python manage.py akte_schwaerzen --ereignis <event_hash oder event_id>

Geschwärzt werden Salz und Inhalt. Die Kette bleibt gültig (die Zusage steht weiter darin), aber niemand kann den
Inhalt danach offenlegen oder erraten. Im Export erscheint das Ereignis unter ``geschwaerzt``. Ein geschwärzter Faden
oder eine geschwärzte Karte gilt als „verändert seit Freigabe“ und verschwindet aus der Lese-Ansicht, bis ein Mensch
neu unterschreibt. Das Objekt selbst bleibt; löschen geht in der Oberfläche.

Schwärzen lässt sich nicht rückgängig machen.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from akte.beweisschicht import schwaerzen
from akte.models import Ereignis


class Command(BaseCommand):
    help = "Inhalte aus der Beweiskette schwärzen (Salz und Inhalt löschen; die Kette bleibt gültig)."

    def add_arguments(self, parser):
        gruppe = parser.add_mutually_exclusive_group(required=True)
        gruppe.add_argument("--faden", type=int, help="ID des Fadens")
        gruppe.add_argument("--karte", type=int, help="ID der Karte (Entität)")
        gruppe.add_argument("--quelle", type=int, help="ID der Quelle (ihre Sicherungen)")
        gruppe.add_argument("--ereignis", help="event_hash oder event_id eines einzelnen Ereignisses")
        parser.add_argument("--ja", action="store_true", help="ohne Rückfrage")

    def handle(self, *args, **opts):
        if opts["faden"] is not None:
            qs = Ereignis.objects.filter(verbindung_id=opts["faden"])
        elif opts["karte"] is not None:
            qs = Ereignis.objects.filter(entitaet_id=opts["karte"])
        elif opts["quelle"] is not None:
            qs = Ereignis.objects.filter(sicherung__quelle_id=opts["quelle"])
        else:
            qs = Ereignis.objects.filter(Q(event_hash=opts["ereignis"]) | Q(event_id=opts["ereignis"]))
        ereignisse = list(qs.filter(geschwaerzt_am__isnull=True))
        if not ereignisse:
            raise CommandError("Nichts zu schwärzen (nicht gefunden oder schon geschwärzt).")
        for e in ereignisse:
            self.stdout.write(f"  #{e.position}  {e.typ}  {e.event_hash[:16]}…")
        if not opts["ja"] and input(f"{len(ereignisse)} Ereignisse unwiderruflich schwärzen? [ja/nein] ").strip() != "ja":
            raise CommandError("Abgebrochen.")
        anzahl = schwaerzen(ereignisse)
        self.stdout.write(self.style.SUCCESS(f"{anzahl} Ereignisse geschwärzt. Die Kette bleibt gültig."))
