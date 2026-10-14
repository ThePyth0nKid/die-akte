"""Persönlicher Token für Werkzeuge an der Akte (CLI ``akte``, MCP-Server ``akte-mcp``).

    python manage.py akte_token redaktion
    python manage.py akte_token              # ohne Namen: das einzige Konto der Redaktion (sonst Fehler mit Liste)

Gibt den Token einmal aus. Er gehört in die Umgebungsvariable ``AKTE_TOKEN`` auf dem
eigenen Rechner, nie ins Repo. ``--neu`` verwirft den alten Token.

Ohne Namen wählt der Befehl dasselbe Konto, das auch die Einrichtung als „Redaktion“ zählt
(``permissions.redaktionskonten``: aktive Redaktionsgruppe oder Superuser) – aber nur, wenn es genau eines gibt.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token

from akte.permissions import ist_redaktion, redaktionskonten


class Command(BaseCommand):
    help = "Legt den Werkzeug-Token für ein Redaktionskonto an und gibt ihn aus."

    def add_arguments(self, parser):
        parser.add_argument("benutzer", nargs="?", help="Konto; ohne Angabe das einzige Redaktionskonto")
        parser.add_argument("--neu", action="store_true", help="Alten Token verwerfen.")

    def handle(self, benutzer=None, neu=False, **_):
        if not benutzer:
            namen = list(redaktionskonten().values_list("username", flat=True))
            if not namen:
                raise CommandError("Es gibt noch kein Konto für die Redaktion. Zuerst im Browser anlegen.")
            if len(namen) > 1:
                raise CommandError("Es gibt mehrere Konten: " + ", ".join(namen) + ". Bitte eines nennen.")
            benutzer = namen[0]
        User = get_user_model()
        try:
            user = User.objects.get(username=benutzer)
        except User.DoesNotExist:
            raise CommandError(f"Kein Konto {benutzer!r}.") from None
        if not user.is_active:
            raise CommandError("Das Konto ist deaktiviert.")
        if not ist_redaktion(user):
            raise CommandError("Das Konto gehört nicht zur Redaktion der Akte.")
        if neu:
            Token.objects.filter(user=user).delete()
        token, _ = Token.objects.get_or_create(user=user)
        self.stdout.write(token.key)
