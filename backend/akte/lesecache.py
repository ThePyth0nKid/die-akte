"""Zwischenspeicher der Lese-Ansicht ohne Konto.

Ohne Konto sieht jeder dieselbe Wand. Nach einem Video sollen nicht tausend Besucher dieselbe Wand je neu rechnen,
deshalb liegt die Antwort fünf Minuten im Cache. Zwei Regeln aus dem Review:
- Jede Änderung an der Akte setzt eine neue Version (Signale in ``apps.py``), der Schlüssel trägt sie. Eine
  Korrektur, etwa eine Person, die doch nur mit Initialen erscheinen soll, gilt damit sofort und nicht erst nach
  fünf Minuten.
- Fällt der Cache aus (Redis weg), wird die Wand ohne ihn gerechnet. Ein Ausfall darf die öffentliche Akte nicht mit
  500 abschalten.
"""

import hashlib
import logging
import time

from django.core.cache import cache
from django.db import transaction

SEKUNDEN = 300
VERSION = "akte:oeffentlich:version"
log = logging.getLogger(__name__)


def version() -> int:
    try:
        return int(cache.get(VERSION) or 0)
    except Exception:  # noqa: BLE001 — ohne Cache gibt es keine Version, nur frisch gerechnete Antworten
        return -1


def _neue_version() -> None:
    try:
        cache.set(VERSION, time.time_ns(), None)
    except Exception:  # noqa: BLE001
        log.warning("Akte: Cache-Version nicht gesetzt", exc_info=True)


def veraltet(**_) -> None:
    """Signal-Empfänger: neue Version. Eine Uhrzeit statt eines Zählers, damit sich eine Version nie wiederholt,
    auch wenn Redis den Schlüssel verdrängt.

    Zweimal: sofort und noch einmal nach dem Commit. Sonst könnte eine Anfrage zwischen Änderung und Commit den
    alten Stand lesen und unter der neuen Version fünf Minuten lang in den Cache legen. Wer mit ``.update()``
    speichert (kein Signal), ruft diese Funktion selbst auf.
    """
    _neue_version()
    transaction.on_commit(_neue_version)


def holen(slug: str, lesbar: set[str], rechnen):
    v = version()
    if v < 0:
        return rechnen()
    schluessel = "akte:oeffentlich:" + hashlib.sha256(
        f"{v}|{slug}|{','.join(sorted(lesbar))}".encode()).hexdigest()[:32]
    try:
        daten = cache.get(schluessel)
    except Exception:  # noqa: BLE001
        log.warning("Akte: Cache nicht lesbar, rechne ohne", exc_info=True)
        return rechnen()
    if daten is None:
        daten = rechnen()
        try:
            cache.set(schluessel, daten, SEKUNDEN)
        except Exception:  # noqa: BLE001
            log.warning("Akte: Cache nicht schreibbar", exc_info=True)
    return daten
