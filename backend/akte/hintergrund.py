"""Hintergrund-Arbeit der Akte: Beweissicherung und Fundstellen, ohne dass eine Anfrage darauf wartet.

Drei Betriebsarten (``settings.AKTE_HINTERGRUND``):

* ``thread`` (Standard ohne Redis): Arbeiter-Threads im API-Prozess, kein zweiter Prozess (SQLite verträgt nur
  einen Schreiber gut). Gunicorn läuft dann mit genau einem Worker (``start.sh``), damit es genau eine
  Warteschlange gibt. Drei Arbeiter:

  - **kurz**: Fundstellen aus PDFs (Sekunden),
  - **lang**: Abruf des Originals, Browser (bis zu zwei Minuten),
  - **archiv**: archive.org (oft gedrosselt, Minuten) – niedrigste Priorität, er hält nie die anderen auf.

  Ein hängender Auftrag hält so die anderen Arbeiter nicht auf. Jeder Auftrag hat eine Frist (``time_limit`` der
  Aufgabe); läuft er länger, meldet der Wächter das im Log (beenden lässt sich ein Thread in Python nicht; Abruf
  und Browser haben eigene Zeitgrenzen). Gleiche wartende Aufträge werden nicht doppelt eingereiht. Endet der
  Prozess, sind wartende Aufträge weg; beim nächsten Start holt ``sicherung.nachholen_beim_start`` sie nach.
* ``celery`` (mit ``REDIS_URL``): an den Celery-Worker.
* ``sofort``: gleich in der Anfrage (Tests, Demo-Befehl).

Ausnahmen einer Aufgabe hält ``tasks.py`` als Sicherung mit Status „Fehler“ fest; der Arbeiter loggt sie zusätzlich
und läuft weiter. Vor und nach jeder Aufgabe räumt er die Datenbankverbindung auf (``close_old_connections``).
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field

from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)

#: Mehr wartende Aufträge je Arbeiter nimmt der Thread nicht an; darüber hinaus wird geloggt und verworfen.
MAX_WARTEND = 1000
KURZ, LANG, ARCHIV = "kurz", "lang", "archiv"
#: Aufgaben für den kurzen Arbeiter und für den archive.org-Arbeiter; alle anderen laufen im langen.
KURZE_AUFGABEN = frozenset({"akte.tasks.fundstelle_sichern"})
ARCHIV_AUFGABEN = frozenset({"akte.tasks.archiv_nachholen"})
#: Die Nachhol-Charge läuft im Arbeiter ihrer Aufträge (hinter ihnen): ``nachholen_charge("archive_org", …)`` im
#: archive.org-Arbeiter, sonst im langen.
CHARGE_AUFGABE = "akte.tasks.nachholen_charge"
#: Aufgaben, die Chromium brauchen: nur mit ``AKTE_BROWSER_AKTIV``.
BROWSER_AUFGABEN = frozenset({"akte.tasks.seite_rendern_task", "akte.tasks.fundstelle_browser"})
#: Frist, wenn eine Aufgabe keine eigene (``time_limit``) mitbringt.
FRIST_STANDARD = 300
#: Wie oft der Wächter nachsieht (Sekunden).
WAECHTER_TAKT = 15.0


@dataclass
class _Lauf:
    schluessel: tuple
    anfang: float
    frist: float
    gemeldet: bool = False


@dataclass
class _Arbeiter:
    name: str
    schlange: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=MAX_WARTEND))
    thread: threading.Thread | None = None
    lauf: _Lauf | None = None


def _neue_arbeiter() -> dict[str, _Arbeiter]:
    return {name: _Arbeiter(name) for name in (KURZ, LANG, ARCHIV)}


_sperre = threading.Lock()
_wartend: set[tuple] = set()
_arbeiter: dict[str, _Arbeiter] = _neue_arbeiter()
_waechter: threading.Thread | None = None


def _nach_fork() -> None:
    """Im Kindprozess eines fork (Gunicorn mit --preload) gehören Threads und Sperre dem Elternprozess."""
    global _sperre, _wartend, _arbeiter, _waechter
    _sperre = threading.Lock()
    _wartend = set()
    _arbeiter = _neue_arbeiter()
    _waechter = None


if hasattr(os, "register_at_fork"):  # nicht unter Windows (dort gibt es kein fork)
    os.register_at_fork(after_in_child=_nach_fork)


def modus() -> str:
    wert = str(getattr(settings, "AKTE_HINTERGRUND", "thread") or "thread").lower()
    return wert if wert in ("thread", "celery", "sofort") else "thread"


def _name(aufgabe) -> str:
    return str(getattr(aufgabe, "name", None) or repr(aufgabe))


def arbeiter_fuer(aufgabe, args: tuple = ()) -> str:
    name = _name(aufgabe)
    if name in KURZE_AUFGABEN:
        return KURZ
    if name in ARCHIV_AUFGABEN or (name == CHARGE_AUFGABE and args[:1] == ("archive_org",)):
        return ARCHIV
    return LANG


def frist_fuer(aufgabe) -> float:
    try:
        return float(getattr(aufgabe, "time_limit", None) or FRIST_STANDARD)
    except (TypeError, ValueError):
        return float(FRIST_STANDARD)


def starten(aufgabe, *args) -> None:
    """Aufgabe (eine Celery-Aufgabe aus ``tasks.py``) im Hintergrund ausführen lassen. Kehrt sofort zurück.

    Aufrufer im Request benutzen ``transaction.on_commit(lambda: starten(...))``, damit der Arbeiter die eben
    gespeicherten Zeilen schon sieht.
    """
    if _name(aufgabe) in BROWSER_AUFGABEN and not getattr(settings, "AKTE_BROWSER_AKTIV", False):
        logger.debug("Akte: %s ohne Browser übersprungen", _name(aufgabe))
        return
    art = modus()
    if art == "celery":
        aufgabe.delay(*args)
    elif art == "sofort":
        # Eager-Celery (Tests, Demo) führt .delay() gleich aus; ohne Eager direkt aufrufen statt an einen Broker.
        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            aufgabe.delay(*args)
        else:
            aufgabe(*args)
    else:
        _einreihen(aufgabe, args)


def _einreihen(aufgabe, args: tuple) -> None:
    global _waechter
    schluessel = (_name(aufgabe), tuple(args))
    arbeiter = _arbeiter[arbeiter_fuer(aufgabe, tuple(args))]
    with _sperre:
        if schluessel in _wartend:
            return
        try:
            arbeiter.schlange.put_nowait((schluessel, aufgabe, tuple(args)))
        except queue.Full:
            logger.warning("Akte: Hintergrund-Warteschlange %s voll, %s verworfen", arbeiter.name, schluessel[0])
            return
        _wartend.add(schluessel)
        if arbeiter.thread is None or not arbeiter.thread.is_alive():
            arbeiter.thread = threading.Thread(target=_schleife, args=(arbeiter,), name=f"akte-{arbeiter.name}",
                                               daemon=True)
            arbeiter.thread.start()
        if _waechter is None or not _waechter.is_alive():
            _waechter = threading.Thread(target=_wache, name="akte-waechter", daemon=True)
            _waechter.start()


def _schleife(arbeiter: _Arbeiter) -> None:
    while True:
        schluessel, aufgabe, args = arbeiter.schlange.get()
        with _sperre:
            # Schon vor dem Lauf austragen: Ein neuer Auftrag während des Laufs (z. B. neue Daten) wird neu eingereiht.
            _wartend.discard(schluessel)
        arbeiter.lauf = _Lauf(schluessel, time.monotonic(), frist_fuer(aufgabe))
        try:
            close_old_connections()
            aufgabe(*args)
        except Exception:  # noqa: BLE001 — ein Fehler darf den Arbeiter nie beenden
            logger.exception("Akte: Hintergrund-Aufgabe %s gescheitert", schluessel[0])
        finally:
            arbeiter.lauf = None
            try:
                close_old_connections()
            except Exception:  # noqa: BLE001
                logger.warning("Akte: Datenbankverbindung im Hintergrund nicht aufgeräumt", exc_info=True)
            arbeiter.schlange.task_done()


def waechter_pruefen(jetzt: float | None = None) -> list[str]:
    """Aufträge über ihrer Frist melden (einmal je Auftrag). Gibt die gemeldeten Namen zurück."""
    jetzt = time.monotonic() if jetzt is None else jetzt
    gemeldet = []
    for arbeiter in list(_arbeiter.values()):
        lauf = arbeiter.lauf
        if lauf is not None and not lauf.gemeldet and jetzt - lauf.anfang > lauf.frist:
            lauf.gemeldet = True
            gemeldet.append(lauf.schluessel[0])
            logger.error("Akte: Hintergrund-Aufgabe %s (%s) läuft seit %d s, Frist %d s. Der Arbeiter %s wartet darauf; "
                         "die übrigen Aufträge dieses Arbeiters stehen solange.", lauf.schluessel[0], lauf.schluessel[1],
                         jetzt - lauf.anfang, lauf.frist, arbeiter.name)
    return gemeldet


def _wache() -> None:
    while True:
        time.sleep(WAECHTER_TAKT)
        try:
            waechter_pruefen()
        except Exception:  # noqa: BLE001
            logger.warning("Akte: Wächter der Hintergrund-Arbeit gestolpert", exc_info=True)


def _offen() -> int:
    return sum(a.schlange.unfinished_tasks for a in _arbeiter.values())


def warten(sekunden: float = 30.0) -> bool:
    """Bis alle Warteschlangen leer und abgearbeitet sind (für Tests). ``True`` = fertig."""
    fertig = threading.Event()

    def pruefen():
        for arbeiter in list(_arbeiter.values()):
            arbeiter.schlange.join()
        fertig.set()

    threading.Thread(target=pruefen, daemon=True).start()
    return fertig.wait(sekunden)


def wartend() -> int:
    """Zahl der Aufträge, die noch warten oder gerade laufen."""
    return _offen()


def zuruecksetzen(sekunden: float = 30.0) -> None:
    """Für Tests: warten, bis alles abgearbeitet ist, dann die Merkliste leeren."""
    warten(sekunden)
    with _sperre:
        _wartend.clear()
