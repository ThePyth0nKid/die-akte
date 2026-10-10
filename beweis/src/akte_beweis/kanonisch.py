# SPDX-License-Identifier: MIT
"""Deterministische Kodierungen, byte-gleich mit dem Prüfer von Atlas (``atlas-trust-core``).

* **CBOR** nach RFC 8949 § 4.2.1 („Core Deterministic Encoding“): kürzeste Kodierung, Map-Schlüssel nach Länge
  des kodierten Schlüssels, dann bytewise. Gleitkommazahlen werden abgelehnt (sie sind über Bibliotheken hinweg nicht
  deterministisch); Beträge gehören als Zeichenkette oder ganze Zahl in die Nutzlast. Ganze Zahlen nur im Bereich
  von i64/u64, wie bei ``serde_json``.
* **Kanonisches JSON** für den Hash des Schlüsselbündels: Schlüssel sortiert, keine Leerzeichen, Escaping wie
  ``serde_json`` (nur ``"``, ``\\`` und Steuerzeichen).
"""

from __future__ import annotations

import json
import struct
from typing import Any

MAX_EINTRAEGE = 10_000
MAX_TIEFE = 100
I64_MIN, U64_MAX = -(2**63), 2**64 - 1


class KodierFehler(ValueError):
    """Wert lässt sich nicht deterministisch kodieren (z. B. Gleitkommazahl)."""


def _kopf(haupttyp: int, wert: int) -> bytes:
    basis = haupttyp << 5
    if wert < 24:
        return bytes([basis | wert])
    if wert < 0x100:
        return bytes([basis | 24, wert])
    if wert < 0x10000:
        return bytes([basis | 25]) + struct.pack(">H", wert)
    if wert < 0x100000000:
        return bytes([basis | 26]) + struct.pack(">I", wert)
    return bytes([basis | 27]) + struct.pack(">Q", wert)


def cbor(wert: Any, _tiefe: int = 0) -> bytes:
    """Kanonisches CBOR eines JSON-artigen Werts (None, bool, int, str, list, dict mit str-Schlüsseln)."""
    if _tiefe > MAX_TIEFE:
        raise KodierFehler("zu tief verschachtelt")
    if wert is None:
        return b"\xf6"
    if wert is True:
        return b"\xf5"
    if wert is False:
        return b"\xf4"
    if isinstance(wert, int):
        if not I64_MIN <= wert <= U64_MAX:
            raise KodierFehler(f"ganze Zahl außerhalb von i64/u64: {wert}")
        return _kopf(0, wert) if wert >= 0 else _kopf(1, -1 - wert)
    if isinstance(wert, float):
        raise KodierFehler(f"Gleitkommazahl abgelehnt (kanonisches CBOR): {wert!r}")
    if isinstance(wert, str):
        roh = wert.encode("utf-8")
        return _kopf(3, len(roh)) + roh
    if isinstance(wert, (list, tuple)):
        if len(wert) > MAX_EINTRAEGE:
            raise KodierFehler("zu viele Einträge in einer Liste")
        return _kopf(4, len(wert)) + b"".join(cbor(x, _tiefe + 1) for x in wert)
    if isinstance(wert, dict):
        if len(wert) > MAX_EINTRAEGE:
            raise KodierFehler("zu viele Einträge in einer Map")
        paare = []
        for schluessel, inhalt in wert.items():
            if not isinstance(schluessel, str):
                raise KodierFehler("Map-Schlüssel müssen Zeichenketten sein")
            paare.append((cbor(schluessel, _tiefe + 1), cbor(inhalt, _tiefe + 1)))
        paare.sort(key=lambda p: (len(p[0]), p[0]))
        return _kopf(5, len(paare)) + b"".join(k + v for k, v in paare)
    raise KodierFehler(f"Typ nicht kodierbar: {type(wert).__name__}")


def kanonisches_json(wert: Any) -> bytes:
    """Wie ``canonical_json_bytes`` in Atlas: Schlüssel sortiert (bytewise), ohne Leerzeichen, UTF-8 roh."""
    if isinstance(wert, float):
        raise KodierFehler("Gleitkommazahl abgelehnt")
    return json.dumps(wert, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
