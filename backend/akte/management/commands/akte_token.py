"""Persönlicher Token für Werkzeuge an der Akte (``scripts/akte/akte.py``).

    python manage.py akte_token redaktion

Gibt den Token einmal aus. Er gehört in die Umgebungsvariable ``AKTE_TOKEN`` auf dem
eigenen Rechner, nie ins Repo. ``--neu`` verwirft den alten Token.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token

from akte.permissions import ist_redaktion


class Command(BaseCommand):
    help = "Legt den Werkzeug-Token für ein Redaktionskonto an und gibt ihn aus."

    def add_arguments(self, parser):
        parser.add_argument("benutzer")
        parser.add_argument("--neu", action="store_true", help="Alten Token verwerfen.")

    def handle(self, benutzer, neu, **_):
        User = get_user_model()
        try:
            user = User.objects.get(username=benutzer)
        except User.DoesNotExist:
            raise CommandError(f"Kein Konto {benutzer!r}.") from None
        if not ist_redaktion(user):
            raise CommandError("Das Konto gehört nicht zur Redaktion der Akte.")
        if neu:
            Token.objects.filter(user=user).delete()
        token, _ = Token.objects.get_or_create(user=user)
        self.stdout.write(token.key)
