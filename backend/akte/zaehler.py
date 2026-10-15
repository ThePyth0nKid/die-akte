"""Zähler mit festem Zeitfenster in der Datenbank (Fehlversuche bei Anmeldung und Einrichtung).

* Das Fenster beginnt mit dem ersten Zählen und endet nach ``dauer`` Sekunden; weiteres Zählen verlängert es nicht.
* Hochzählen ist atomar (``UPDATE … SET anzahl = anzahl + 1``), auch bei gleichzeitigen Anfragen.
* Abgelaufene Zeilen räumt jedes Zählen mit auf.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import Zaehler

#: Abgelaufene Zeilen bleiben noch so lange stehen (billiger Löschlauf, kein Löschen bei jedem Zählen).
AUFRAEUMEN_NACH = timedelta(hours=1)


@dataclass(frozen=True)
class Stand:
    anzahl: int
    ablauf: datetime | None

    def rest_sekunden(self) -> int:
        if self.ablauf is None:
            return 0
        return max(1, int((self.ablauf - timezone.now()).total_seconds() + 0.999))


def stand(name: str) -> Stand:
    zeile = Zaehler.objects.filter(schluessel=name, ablauf__gt=timezone.now()).values_list("anzahl", "ablauf").first()
    return Stand(*zeile) if zeile else Stand(0, None)


def erhoehen(name: str, dauer: int) -> Stand:
    """Um eins erhöhen; ist das Fenster abgelaufen oder neu, beginnt ein neues mit 1."""
    jetzt = timezone.now()
    with transaction.atomic():
        if not Zaehler.objects.filter(schluessel=name, ablauf__gt=jetzt).update(anzahl=F("anzahl") + 1):
            ablauf = jetzt + timedelta(seconds=dauer)
            if not Zaehler.objects.filter(schluessel=name).update(anzahl=1, ablauf=ablauf):
                try:
                    with transaction.atomic():
                        Zaehler.objects.create(schluessel=name, anzahl=1, ablauf=ablauf)
                except IntegrityError:  # gleichzeitig angelegt: dann zählt dieser Versuch dazu
                    Zaehler.objects.filter(schluessel=name).update(anzahl=F("anzahl") + 1)
        Zaehler.objects.filter(ablauf__lt=jetzt - AUFRAEUMEN_NACH).delete()
    return stand(name)


def wartezeit(sekunden: int) -> str:
    """„in 42 Sekunden“, „in einer Minute“, „in 37 Minuten“ – die echte Restzeit, gerundet nach oben."""
    if sekunden <= 1:
        return "gleich"
    if sekunden < 60:
        return f"in {sekunden} Sekunden"
    minuten = (sekunden + 59) // 60
    return "in einer Minute" if minuten == 1 else f"in {minuten} Minuten"
