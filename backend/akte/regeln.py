"""Die Prüfregeln der Akte, einzeln einstellbar.

Jede Regel hat eine Stufe:

* ``aus``      – wird nicht geprüft,
* ``hinweis``  – erscheint als Befund, hält aber nichts auf,
* ``sperrt``   – hält einen Faden aus der öffentlichen Ansicht, bis ein Mensch ihn mit Begründung überstimmt.

Standard ist ``hinweis``: Die Prüfung berät, der Mensch entscheidet. Nur der Schutz von Privatpersonen sperrt von
Haus aus, weil er eine rechtliche Grenze ist; auch das ist umstellbar. Stufen kommen aus drei Ebenen, die spätere
gewinnt: Standard hier → ``settings.AKTE_REGELN`` (JSON) → ``Board.regeln``.

Die Zustandsregeln (Faden oder Karte noch nicht freigegeben, verändert seit der Freigabe) sind keine Belegregeln:
Sie sperren immer und lassen sich nicht überstimmen, denn sie beschreiben, ob ein Mensch unterschrieben hat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from django.conf import settings

AUS, HINWEIS, SPERRT = "aus", "hinweis", "sperrt"
STUFEN = (AUS, HINWEIS, SPERRT)

#: code → (Beschreibung, Standardstufe)
REGELN: dict[str, tuple[str, str]] = {
    "ohne_quelle": ("Faden ohne Beleg", HINWEIS),
    "quelle_ohne_adresse": ("Quelle ohne Link und ohne Datei", HINWEIS),
    "quelle_ohne_abruf": ("Quelle ohne Abrufdatum", HINWEIS),
    "quelle_ohne_archiv": ("Quelle ohne Archivkopie", HINWEIS),
    "verdacht_ohne_anhoerung": ("Verdacht gegen eine Person ohne Anhörung", HINWEIS),
    "verdacht_zu_duenn": ("Verdacht mit weniger als zwei unabhängigen Quellen", HINWEIS),
    "ohne_start": ("Faden ohne Startdatum", HINWEIS),
    "zeitraum_widerspruch": ("„Aktuell“ und Enddatum zugleich", HINWEIS),
    "zeitraum_offen": ("Weder „aktuell“ noch Enddatum", HINWEIS),
    "zeitraum_verkehrt": ("Ende vor dem Start", HINWEIS),
    "verdacht_privatperson": ("Verdacht gegen eine Privatperson", SPERRT),
    "familie_privatperson": ("Familienbande einer Privatperson", SPERRT),
}

#: Zustandsregeln: immer sperrend, nie überstimmbar.
ZUSTAND = {"faden_nicht_freigegeben", "karte_nicht_freigegeben", "veraendert_seit_freigabe"}


@dataclass(frozen=True)
class Einstellung:
    stufen: dict[str, str]

    def stufe(self, code: str) -> str:
        if code in ZUSTAND:
            return SPERRT
        return self.stufen.get(code, REGELN.get(code, ("", HINWEIS))[1])


def _gueltig(daten) -> dict[str, str]:
    if not isinstance(daten, dict):
        return {}
    return {k: v for k, v in daten.items() if k in REGELN and v in STUFEN}


def global_einstellung() -> dict[str, str]:
    roh = getattr(settings, "AKTE_REGELN", "") or ""
    if isinstance(roh, dict):
        return _gueltig(roh)
    try:
        return _gueltig(json.loads(roh)) if roh else {}
    except ValueError:
        return {}


def einstellung(board=None) -> Einstellung:
    stufen = {code: standard for code, (_, standard) in REGELN.items()}
    stufen.update(global_einstellung())
    if board is not None:
        stufen.update(_gueltig(getattr(board, "regeln", None)))
    return Einstellung(stufen)


def pruefe_board_regeln(daten) -> dict[str, str]:
    """Eingabe für ``Board.regeln`` prüfen; unbekannte Codes oder Stufen sind ein Fehler."""
    if not isinstance(daten, dict):
        raise ValueError("regeln ist ein Objekt {code: aus|hinweis|sperrt}.")
    falsch = [k for k, v in daten.items() if k not in REGELN or v not in STUFEN]
    if falsch:
        raise ValueError(f"Unbekannte Regel oder Stufe: {', '.join(sorted(falsch))}")
    return dict(daten)


def uebersicht(board=None) -> list[dict]:
    e = einstellung(board)
    return [{"code": code, "text": text, "stufe": e.stufe(code), "standard": standard}
            for code, (text, standard) in REGELN.items()]
