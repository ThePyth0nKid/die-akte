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


SALZ_MIN_BYTES = 16


def zusage(inhalt: Any, salz: str) -> str:
    roh = b64url_lesen(salz)
    if len(roh) < SALZ_MIN_BYTES:
        raise ValueError(f"Salz zu kurz (mindestens {SALZ_MIN_BYTES} Byte)")
    return "sha256:" + hashlib.sha256(roh + kanonisches_json(inhalt)).hexdigest()


def zusage_stimmt(erwartet: str, inhalt: Any, salz: str) -> bool:
    if not isinstance(erwartet, str) or not isinstance(salz, str):
        return False
    try:
        return hmac.compare_digest(erwartet.encode("utf-8", "surrogatepass"), zusage(inhalt, salz).encode("ascii"))
    except (ValueError, TypeError):
        return False


def _widerrufene_vorfahren(ereignisse: list[dict]) -> dict[str, set[str]]:
    """Je Ereignis: welche Schlüssel in seinen Vorfahren (über ``parent_hashes``) widerrufen wurden.

    Maßgeblich ist die Kette, nicht die Position in der Liste: Ein Ereignis, das einen Widerruf als Vorfahr hat,
    darf nicht mehr mit dem widerrufenen Schlüssel signiert sein. Wer ein Ereignis in der Liste nach vorn schiebt,
    ändert daran nichts.
    """
    nach_hash = {e["event_hash"]: e for e in ereignisse if isinstance(e.get("event_hash"), str)}
    ergebnis: dict[str, set[str]] = {}

    def widerruft(e: dict) -> set[str]:
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        return {p["kid"]} if p.get("type") == "akte.widerruf" and isinstance(p.get("kid"), str) else set()

    for start in nach_hash:
        if start in ergebnis:
            continue
        stapel = [(start, False)]
        while stapel:
            h, fertig = stapel.pop()
            if h in ergebnis:
                continue
            eltern = [x for x in (nach_hash[h].get("parent_hashes") or []) if isinstance(x, str) and x in nach_hash]
            if not fertig:
                stapel.append((h, True))
                stapel.extend((x, False) for x in eltern if x not in ergebnis)
                continue
            menge: set[str] = set()
            for x in eltern:
                menge |= ergebnis.get(x, set()) | widerruft(nach_hash[x])
            ergebnis[h] = menge
    return ergebnis


def pruefen(trace: dict, offenlegung: dict | None = None) -> Ergebnis:
    """Rollen, Widerrufe, Reihenfolge und Offenlegungen prüfen.

    ``offenlegung``: {event_hash: {"salz": …, "inhalt": …}}. Fehlerhafte Eingaben ergeben ``gueltig=False``.
    """
    erg = Ergebnis()
    ereignisse = trace.get("events") if isinstance(trace, dict) else None
    if not isinstance(ereignisse, list) or not all(isinstance(e, dict) for e in ereignisse):
        erg.fehler.append("events muss eine Liste von Objekten sein.")
        erg.pruefung("format", False)
        return erg

    vorfahren = _widerrufene_vorfahren(ereignisse)
    rollen_ok, widerruf_ok, typ_ok = True, True, True
    anzahl_widerrufe = 0
    for e in ereignisse:
        sig = e.get("signature") if isinstance(e.get("signature"), dict) else {}
        kid = sig.get("kid") if isinstance(sig.get("kid"), str) else ""
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        typ = p.get("type", "")
        eid = str(e.get("event_id", "?"))[:80]
        if typ not in ERLAUBT:
            erg.fehler.append(f"Ereignis {eid}: unbekannter Typ {str(typ)[:40]!r}")
            typ_ok = False
            continue
        if kid in vorfahren.get(e.get("event_hash"), set()):
            erg.fehler.append(f"Ereignis {eid}: signiert mit einem Schlüssel, der in der Kette davor widerrufen wurde")
            widerruf_ok = False
        if not kid.startswith(ERLAUBT[typ]):
            erg.fehler.append(f"Ereignis {eid}: {typ} darf {rolle(kid)} nicht signieren")
            rollen_ok = False
        anzahl_widerrufe += typ == "akte.widerruf"
    erg.pruefung("akte-typen", typ_ok)
    erg.pruefung("akte-rollen", rollen_ok, "Freigaben und Widerrufe nur durch Menschen")
    erg.pruefung("akte-widerrufe", widerruf_ok, f"{anzahl_widerrufe} Widerrufe in der Kette")

    # Eine Akte exportiert ihre Kette in Kettenreihenfolge: jedes Ereignis setzt das vorige fort.
    reihenfolge_ok = all(
        (e.get("parent_hashes") or []) == ([ereignisse[i - 1].get("event_hash")] if i else [])
        for i, e in enumerate(ereignisse)
    )
    if not reihenfolge_ok:
        erg.fehler.append("Die Ereignisse stehen nicht in Kettenreihenfolge (jedes setzt das vorige fort).")
    erg.pruefung("akte-reihenfolge", reihenfolge_ok)

    if offenlegung is not None:
        if not isinstance(offenlegung, dict):
            erg.fehler.append("Offenlegung muss ein Objekt sein.")
            erg.pruefung("akte-offenlegung", False)
            return erg
        nach_hash = {e.get("event_hash"): e for e in ereignisse}
        offen_ok, gezaehlt = True, 0
        for event_hash, eintrag in offenlegung.items():
            e = nach_hash.get(event_hash)
            if not e or not isinstance(eintrag, dict):
                erg.fehler.append(f"Offenlegung für unbekanntes Ereignis {str(event_hash)[:12]}…")
                offen_ok = False
                continue
            p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            if not zusage_stimmt(p.get("inhalt_zusage"), eintrag.get("inhalt"), eintrag.get("salz")):
                erg.fehler.append(f"Ereignis {str(e.get('event_id'))[:80]}: offengelegter Inhalt passt nicht zur Zusage")
                offen_ok = False
            gezaehlt += 1
        erg.pruefung("akte-offenlegung", offen_ok, f"{gezaehlt} Inhalte offengelegt und geprüft")
    return erg
