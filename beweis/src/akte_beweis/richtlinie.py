# SPDX-License-Identifier: MIT
"""Regeln der Akte über dem Atlas-Format: Wer darf was signieren, was gilt nach einem Widerruf, stimmen die
offengelegten Inhalte mit den Zusagen in der Kette?

Atlas prüft Unverändertheit, Signaturen und Reihenfolge. Es kennt keine Rollen und keinen Widerruf. Diese Schicht
ergänzt das, ohne das Format zu ändern: Die Rolle steckt in der Schlüssel-ID (``kid``), die über den Bündel-Hash
an jede Signatur gebunden ist.

Schlüssel-IDs:
    akte-mensch:<name>#<fingerabdruck>   ein Mensch (Freigaben, Überstimmungen, Widerrufe)
    akte-geraet:<instanz>                die eigene Installation (Beweissicherungen)
    akte-agent:<name>                    ein Werkzeug oder Agent (nie Freigaben)

Ereignisse (``payload.type``):
    akte.sicherung      Beweisstück gesichert (Prüfsumme des Originals, Zeitpunkt)   Gerät oder Mensch
    akte.freigabe       ein Mensch gibt eine Karte oder einen Faden frei              nur Mensch
    akte.ueberstimmung  ein Mensch überstimmt einen Befund, mit Begründung            nur Mensch
    akte.widerruf       ein Schlüssel gilt ab hier nicht mehr                         nur Mensch

Inhalte stehen nicht im Klartext in der Kette, sondern als Zusage ``inhalt_zusage = sha256(salz ‖ kanonisches JSON)``.
Veröffentlicht wird der Inhalt samt Salz in einer Offenlegung; so bleiben Entwürfe privat und die Kette trotzdem
vollständig prüfbar.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from .atlas import Ergebnis, b64url, b64url_lesen
from .kanonisch import kanonisches_json

MENSCH, GERAET, AGENT = "akte-mensch:", "akte-geraet:", "akte-agent:"
ERLAUBT = {
    "akte.sicherung": (MENSCH, GERAET),
    "akte.freigabe": (MENSCH,),
    "akte.ueberstimmung": (MENSCH,),
    "akte.widerruf": (MENSCH,),
}


def rolle(kid: str) -> str:
    for praefix, name in ((MENSCH, "mensch"), (GERAET, "geraet"), (AGENT, "agent")):
        if kid.startswith(praefix):
            return name
    return "unbekannt"


def fingerabdruck(pubkey: bytes) -> str:
    """Kurzer, gut vorlesbarer Fingerabdruck eines öffentlichen Schlüssels (SHA-256, 16 Hex-Zeichen)."""
    return hashlib.sha256(pubkey).hexdigest()[:16]


def neues_salz() -> str:
    return b64url(secrets.token_bytes(16))


def zusage(inhalt: Any, salz: str) -> str:
    return "sha256:" + hashlib.sha256(b64url_lesen(salz) + kanonisches_json(inhalt)).hexdigest()


def zusage_stimmt(erwartet: str, inhalt: Any, salz: str) -> bool:
    try:
        return hmac.compare_digest(erwartet, zusage(inhalt, salz))
    except (ValueError, TypeError):
        return False


def pruefen(trace: dict, offenlegung: dict | None = None) -> Ergebnis:
    """Rollen, Widerrufe und Offenlegungen prüfen. ``offenlegung``: {event_hash: {"salz": …, "inhalt": …}}."""
    erg = Ergebnis()
    widerrufen: set[str] = set()
    rollen_ok, widerruf_ok, typ_ok = True, True, True
    for e in trace.get("events", []):
        kid = e.get("signature", {}).get("kid", "")
        p = e.get("payload") or {}
        typ = p.get("type", "")
        eid = e.get("event_id", "?")
        if typ not in ERLAUBT:
            erg.fehler.append(f"Ereignis {eid}: unbekannter Typ {typ!r}")
            typ_ok = False
            continue
        if kid in widerrufen:
            erg.fehler.append(f"Ereignis {eid}: signiert mit widerrufenem Schlüssel {kid}")
            widerruf_ok = False
        if not kid.startswith(ERLAUBT[typ]):
            erg.fehler.append(f"Ereignis {eid}: {typ} darf {rolle(kid)} nicht signieren ({kid})")
            rollen_ok = False
        if typ == "akte.widerruf" and isinstance(p.get("kid"), str):
            widerrufen.add(p["kid"])
    erg.pruefung("akte-typen", typ_ok)
    erg.pruefung("akte-rollen", rollen_ok, "Freigaben und Überstimmungen nur durch Menschen")
    erg.pruefung("akte-widerrufe", widerruf_ok, f"{len(widerrufen)} widerrufene Schlüssel")

    if offenlegung is not None:
        nach_hash = {e["event_hash"]: e for e in trace.get("events", [])}
        offen_ok, gezaehlt = True, 0
        for event_hash, eintrag in offenlegung.items():
            e = nach_hash.get(event_hash)
            if not e:
                erg.fehler.append(f"Offenlegung für unbekanntes Ereignis {event_hash[:12]}…")
                offen_ok = False
                continue
            erwartet = (e.get("payload") or {}).get("inhalt_zusage", "")
            if not zusage_stimmt(erwartet, eintrag.get("inhalt"), eintrag.get("salz", "")):
                erg.fehler.append(f"Ereignis {e.get('event_id')}: offengelegter Inhalt passt nicht zur Zusage")
                offen_ok = False
            gezaehlt += 1
        erg.pruefung("akte-offenlegung", offen_ok, f"{gezaehlt} Inhalte offengelegt und geprüft")
    return erg
