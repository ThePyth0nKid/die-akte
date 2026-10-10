"""Erster Start: Redaktionsgruppe anlegen und ein Konto für die Redaktion einrichten.

    python manage.py akte_einrichten                     # fragt Benutzername und Passwort ab
    python manage.py akte_einrichten --benutzer anna     # Passwort wird verdeckt abgefragt
    python manage.py akte_einrichten --benutzer anna --token   # zusätzlich ein Token für Werkzeuge und MCP

Ohne Terminal (z. B. in Skripten) kommt das Passwort aus der Umgebungsvariable ``AKTE_PASSWORT``.
Das Token wird nur einmal angezeigt; ``manage.py akte_token <konto> --neu`` erzeugt ein neues.
"""

from __future__ import annotations

import getpass
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token

from akte.permissions import REDAKTION_GRUPPE


class Command(BaseCommand):
    help = "Redaktionsgruppe anlegen und ein Redaktionskonto einrichten (erster Start)."

    def add_arguments(self, parser):
        parser.add_argument("--benutzer", help="Benutzername des Redaktionskontos")
        parser.add_argument("--email", default="", help="E-Mail-Adresse (optional)")
        parser.add_argument("--token", action="store_true", help="Token für Werkzeuge und MCP ausgeben")

    def handle(self, *args, **opts):
        gruppe, _ = Group.objects.get_or_create(name=REDAKTION_GRUPPE)
        benutzer = opts["benutzer"] or input("Benutzername: ").strip()
        if not benutzer:
            raise CommandError("Ohne Benutzername geht es nicht.")

        User = get_user_model()
        konto = User.objects.filter(username=benutzer).first()
        if konto is None:
            passwort = os.environ.get("AKTE_PASSWORT") or self._passwort_abfragen()
            konto = User(username=benutzer, email=opts["email"])
            try:
                validate_password(passwort, konto)
            except ValidationError as fehler:
                raise CommandError(" ".join(fehler.messages)) from None
            konto.set_password(passwort)
            konto.is_staff = True
            konto.save()
            self.stdout.write(self.style.SUCCESS(f"Konto „{benutzer}“ angelegt."))
        else:
            self.stdout.write(f"Konto „{benutzer}“ gibt es schon.")
        konto.groups.add(gruppe)
        self.stdout.write(self.style.SUCCESS(f"„{benutzer}“ gehört zur Redaktion."))

        if opts["token"]:
            Token.objects.filter(user=konto).delete()
            token = Token.objects.create(user=konto)
            self.stdout.write("Token (nur jetzt sichtbar, nie ins Repo):")
            self.stdout.write(token.key)

    def _passwort_abfragen(self) -> str:
        erstes = getpass.getpass("Passwort (mind. 10 Zeichen): ")
        zweites = getpass.getpass("Passwort wiederholen: ")
        if erstes != zweites:
            raise CommandError("Die Passwörter stimmen nicht überein.")
        return erstes
