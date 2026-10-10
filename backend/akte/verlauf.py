"""Änderungsverlauf — jede Änderung an Karten, Quellen und Fäden mit dem Stand danach."""

import json

from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict

from .models import Verbindung, Verlauf


def _stand(obj) -> dict:
    stand = model_to_dict(obj, exclude=["quellen", "ausgeblendete_verbindungen"])
    if isinstance(obj, Verbindung):
        stand["belege"] = list(
            obj.belege.values("quelle_id", "zitat_woertlich", "fundstelle")
        )
    # Durch den Encoder, damit Datum und Dezimalzahl als JSON landen.
    return json.loads(json.dumps(stand, cls=DjangoJSONEncoder))


def protokolliere(obj, aktion: str, nutzer) -> None:
    Verlauf.objects.create(
        objekt_art=obj._meta.model_name,
        objekt_id=obj.pk,
        aktion=aktion,
        nutzer=nutzer if nutzer and nutzer.is_authenticated else None,
        stand=_stand(obj),
    )
