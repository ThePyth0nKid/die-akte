"""Django-Systemprüfungen der Akte (laufen bei ``migrate`` beim Start des Containers und bei ``manage.py check``)."""

from __future__ import annotations

from django.core.checks import Tags, Warning, register
from django.db import DatabaseError
from django.db.models import Q

UMBENENNEN = ("docker compose exec api python manage.py shell -c \"from akte.models import Board; "
              "Board.objects.filter(slug__iexact='{slug}').update(slug='{slug}-alt')\"")


@register(Tags.database)
def board_kennung_reserviert(app_configs=None, databases=None, **kwargs):
    """Ein Board aus der Zeit vor 0.2 mit der Kennung „einrichten“ ist unter /akte/einrichten nicht mehr erreichbar
    (dort liegt jetzt die Einrichtung des ersten Kontos). Warnen und den Weg nennen."""
    if not databases:
        return []
    from .models import BOARD_SLUGS_RESERVIERT, Board

    bedingung = Q()
    for slug in BOARD_SLUGS_RESERVIERT:
        bedingung |= Q(slug__iexact=slug)
    try:
        belegt = list(Board.objects.filter(bedingung).values_list("slug", flat=True))
    except DatabaseError:  # Tabelle noch nicht da (erste Migration): nichts zu prüfen
        return []
    return [
        Warning(f"Das Board mit der Kennung „{slug}“ ist unter /akte/{slug} nicht erreichbar: Diese Adresse braucht "
                "die Oberfläche seit Version 0.2 selbst.",
                hint="Kennung ändern: " + UMBENENNEN.format(slug=slug.lower()), id="akte.W001")
        for slug in belegt
    ]
