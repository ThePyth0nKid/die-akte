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
import json
import logging
import time

from django.core.cache import cache
from django.db import transaction

SEKUNDEN = 300
VERSION = "akte:oeffentlich:version"
#: Stand der Werkstatt (Live-Aktualisierung der Wand): ändert sich bei jeder Änderung, auch bei Dingen, die Leser
#: nicht sehen (Fahrten, Beweisstücke). ``veraltet`` setzt beide Versionen, ``werkstatt_veraltet`` nur diese.
WERKSTATT = "akte:werkstatt:version"
log = logging.getLogger(__name__)


def _lesen(schluessel: str) -> int:
    try:
        return int(cache.get(schluessel) or 0)
    except Exception:  # noqa: BLE001 — ohne Cache gibt es keine Version, nur frisch gerechnete Antworten
        return -1


def version() -> int:
    return _lesen(VERSION)


def werkstatt_version() -> int:
    return _lesen(WERKSTATT)


def _setzen(*schluessel: str) -> None:
    jetzt = time.time_ns()
    try:
        cache.set_many({s: jetzt for s in schluessel}, None)
    except Exception:  # noqa: BLE001
        log.warning("Akte: Cache-Version nicht gesetzt", exc_info=True)


def _neue_version() -> None:
    _setzen(VERSION, WERKSTATT)


def _neue_werkstatt_version() -> None:
    _setzen(WERKSTATT)


def veraltet(**_) -> None:
    """Signal-Empfänger: neue Version. Eine Uhrzeit statt eines Zählers, damit sich eine Version nie wiederholt,
    auch wenn Redis den Schlüssel verdrängt.

    Zweimal: sofort und noch einmal nach dem Commit. Sonst könnte eine Anfrage zwischen Änderung und Commit den
    alten Stand lesen und unter der neuen Version fünf Minuten lang in den Cache legen. Wer mit ``.update()``
    speichert (kein Signal), ruft diese Funktion selbst auf.
    """
    _neue_version()
    transaction.on_commit(_neue_version)


def werkstatt_veraltet(**_) -> None:
    """Wie ``veraltet``, aber nur für die Werkstatt (Fahrten, Stationen, Beweisstücke: Leser sehen sie nicht)."""
    _neue_werkstatt_version()
    transaction.on_commit(_neue_werkstatt_version)


def _hash(daten) -> str:
    roh = json.dumps(daten, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:32]


def fingerabdruck(slug: str, lesbar: set[str], rechnen) -> str:
    """Fingerabdruck der Lese-Ansicht für die Live-Aktualisierung: einmal je Cache-Version gerechnet und gemerkt
    (Mitglieder und Besucher fragen alle paar Sekunden; JSON und Hash der ganzen Wand kosten sonst jedes Mal)."""
    v = version()
    if v < 0:
        return _hash(rechnen())
    schluessel = "akte:stand:" + hashlib.sha256(f"{v}|{slug}|{','.join(sorted(lesbar))}".encode()).hexdigest()[:32]
    try:
        wert = cache.get(schluessel)
    except Exception:  # noqa: BLE001
        log.warning("Akte: Cache nicht lesbar, rechne ohne", exc_info=True)
        return _hash(rechnen())
    if wert is None:
        wert = _hash(holen(slug, lesbar, rechnen))
        try:
            cache.set(schluessel, wert, SEKUNDEN)
        except Exception:  # noqa: BLE001
            log.warning("Akte: Cache nicht schreibbar", exc_info=True)
    return wert


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
