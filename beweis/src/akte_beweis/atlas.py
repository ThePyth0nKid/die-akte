# SPDX-License-Identifier: MIT
"""Ereignisse und Traces im Format ``atlas-trace-v1`` erzeugen und prüfen.

Das Format stammt aus Atlas (https://github.com/ThePyth0nKid/atlas, Prüfer unter Apache-2.0). Ein Trace, den diese
Bibliothek schreibt, prüft auch ``atlas-verify-cli`` und der WASM-Prüfer ``@atlas-trust/verify-wasm``.

* Signing-Input: kanonisches CBOR der Map {v, workspace, id, ts, kid, parents, payload[, author_did]}.
* ``event_hash`` = blake3(Signing-Input) als Hex in Kleinbuchstaben.
* Signatur: Ed25519 über die rohen Signing-Input-Bytes, base64url ohne Auffüllung.
* Schlüsselbündel: {schema, generated_at, keys: {kid: base64url(32 Byte)}}; Hash = blake3(kanonisches JSON).

Die Prüfung hier bildet die Prüfschritte von Atlas nach (Schema, Bündel-Hash, Event-Hashes, Signaturen,
Eltern, Spitzen, auf Wunsch strikte Kette). Verankerungen in Transparenz-Logs prüft sie nicht; dafür gibt es die
Prüfer von Atlas.
"""

from __future__ import annotations

import base64
import binascii
import hmac
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .kanonisch import KodierFehler, cbor, kanonisches_json

SCHEMA_TRACE = "atlas-trace-v1"
SCHEMA_BUENDEL = "atlas-pubkey-bundle-v1"
MAX_ELTERN = 10_000


# ─── Grundbausteine ──────────────────────────────────────────────────────────

def b64url(daten: bytes) -> str:
    return base64.urlsafe_b64encode(daten).rstrip(b"=").decode("ascii")


def b64url_lesen(text: str) -> bytes:
    """Streng: nur base64url ohne Auffüllung, und nur die kanonische Form (wie ``URL_SAFE_NO_PAD`` in Rust)."""
    if "=" in text or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in text):
        raise ValueError("kein base64url ohne Auffüllung")
    try:
        roh = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except binascii.Error as fehler:
        raise ValueError(f"base64url ungültig: {fehler}") from None
    if b64url(roh) != text:
        raise ValueError("base64url nicht kanonisch")
    return roh


def signing_input(workspace: str, event_id: str, ts: str, kid: str, eltern: list[str], payload: Any,
                  author_did: str | None = None) -> bytes:
    if len(eltern) > MAX_ELTERN:
        raise KodierFehler("zu viele Eltern-Hashes")
    huelle: dict[str, Any] = {"v": SCHEMA_TRACE, "workspace": workspace, "id": event_id, "ts": ts, "kid": kid,
                              "parents": list(eltern), "payload": payload}
    if author_did is not None:
        huelle["author_did"] = author_did
    return cbor(huelle)


def hash_hex(daten: bytes) -> str:
    return blake3.blake3(daten).hexdigest()


def oeffentlicher_schluessel(privat: Ed25519PrivateKey) -> bytes:
    return privat.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def signieren(privat: Ed25519PrivateKey, *, workspace: str, event_id: str, ts: str, kid: str, eltern: list[str],
              payload: Any) -> dict:
    """Ein fertiges, signiertes Ereignis (Form ``AtlasEvent``)."""
    eingabe = signing_input(workspace, event_id, ts, kid, eltern, payload)
    return ereignis_aus_signatur(eingabe, privat.sign(eingabe), event_id=event_id, ts=ts, kid=kid, eltern=eltern,
                                 payload=payload)


def ereignis_aus_signatur(eingabe: bytes, signatur: bytes, *, event_id: str, ts: str, kid: str, eltern: list[str],
                          payload: Any) -> dict:
    """Für Signaturen, die außerhalb entstehen (Browser, Hardware-Schlüssel): Ereignis aus Eingabe und Signatur."""
    return {"event_id": event_id, "event_hash": hash_hex(eingabe), "parent_hashes": list(eltern), "payload": payload,
            "signature": {"alg": "EdDSA", "kid": kid, "sig": b64url(signatur)}, "ts": ts}


def signatur_gueltig(pubkey: bytes, nachricht: bytes, signatur: bytes) -> bool:
    if len(pubkey) != 32 or len(signatur) != 64:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(pubkey).verify(signatur, nachricht)
        return True
    except InvalidSignature:
        return False


def buendel(schluessel: dict[str, bytes], generated_at: str) -> dict:
    return {"schema": SCHEMA_BUENDEL, "generated_at": generated_at,
            "keys": {kid: b64url(roh) for kid, roh in sorted(schluessel.items())}}


def buendel_hash(b: dict) -> str:
    return hash_hex(kanonisches_json({"schema": b["schema"], "generated_at": b["generated_at"], "keys": b["keys"]}))


def spitzen(ereignisse: list[dict]) -> list[str]:
    """Hashes, auf die kein anderes Ereignis verweist (sortiert)."""
    verwiesen = {p for e in ereignisse for p in e.get("parent_hashes", [])}
    return sorted(e["event_hash"] for e in ereignisse if e["event_hash"] not in verwiesen)


def trace(workspace: str, ereignisse: list[dict], b: dict, generated_at: str) -> dict:
    return {"schema_version": SCHEMA_TRACE, "generated_at": generated_at, "workspace_id": workspace,
            "pubkey_bundle_hash": buendel_hash(b), "events": ereignisse, "dag_tips": spitzen(ereignisse),
            "anchors": [], "policies": [], "filters": None}


# ─── Prüfen ──────────────────────────────────────────────────────────────────

@dataclass
class Ergebnis:
    gueltig: bool = True
    nachweise: list[dict] = field(default_factory=list)
    fehler: list[str] = field(default_factory=list)

    def pruefung(self, name: str, ok: bool, detail: str = "") -> None:
        self.nachweise.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            self.gueltig = False

    def als_dict(self) -> dict:
        return {"gueltig": self.gueltig, "nachweise": self.nachweise, "fehler": self.fehler}


def _rfc3339(ts: str) -> bool:
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return "T" in ts and (ts.endswith("Z") or "+" in ts[10:] or "-" in ts[10:])
    except ValueError:
        return False


def trace_pruefen(t: dict, b: dict, *, strikte_kette: bool = False) -> Ergebnis:
    """Prüft einen Trace gegen sein Schlüsselbündel (Schritte wie ``verify_trace_with`` in Atlas, ohne Anker)."""
    erg = Ergebnis()
    erg.pruefung("schema-version", t.get("schema_version") == SCHEMA_TRACE, str(t.get("schema_version")))
    try:
        ok = hmac.compare_digest(buendel_hash(b), str(t.get("pubkey_bundle_hash", "")))
    except (KeyError, KodierFehler) as fehler:
        ok = False
        erg.fehler.append(f"Bündel unlesbar: {fehler}")
    erg.pruefung("pubkey-bundle-hash", ok)

    ereignisse = t.get("events", [])
    workspace = t.get("workspace_id", "")
    gesehen: set[str] = set()
    hash_ok, sig_ok = True, True
    for e in ereignisse:
        eid = e.get("event_id", "?")
        if e["event_hash"] in gesehen:
            erg.fehler.append(f"Ereignis {eid}: doppelter event_hash")
            hash_ok = False
        gesehen.add(e["event_hash"])
        sig = e.get("signature", {})
        try:
            eingabe = signing_input(workspace, eid, e["ts"], sig["kid"], e.get("parent_hashes", []), e["payload"],
                                    e.get("author_did"))
        except (KeyError, KodierFehler) as fehler:
            erg.fehler.append(f"Ereignis {eid}: Signing-Input nicht baubar: {fehler}")
            hash_ok = sig_ok = False
            continue
        if not hmac.compare_digest(hash_hex(eingabe), e["event_hash"]):
            erg.fehler.append(f"Ereignis {eid}: event_hash passt nicht zum Inhalt")
            hash_ok = False
        if sig.get("alg") != "EdDSA" or not _rfc3339(e["ts"]):
            erg.fehler.append(f"Ereignis {eid}: alg oder ts ungültig")
            sig_ok = False
            continue
        try:
            pub = b64url_lesen(b["keys"][sig["kid"]])
            roh = b64url_lesen(sig["sig"])
        except KeyError:
            erg.fehler.append(f"Ereignis {eid}: Schlüssel {sig['kid']!r} nicht im Bündel")
            sig_ok = False
            continue
        except ValueError as fehler:
            erg.fehler.append(f"Ereignis {eid}: {fehler}")
            sig_ok = False
            continue
        if not signatur_gueltig(pub, eingabe, roh):
            erg.fehler.append(f"Ereignis {eid}: Signatur ungültig")
            sig_ok = False
    erg.pruefung("event-hashes", hash_ok, f"{len(ereignisse)} Ereignisse")
    erg.pruefung("event-signatures", sig_ok, f"{len(ereignisse)} Signaturen")

    eltern_ok = all(p in gesehen for e in ereignisse for p in e.get("parent_hashes", []))
    if not eltern_ok:
        erg.fehler.append("Ein Ereignis verweist auf ein Eltern-Ereignis, das im Trace fehlt.")
    erg.pruefung("parent-links", eltern_ok)

    if strikte_kette:
        erg.pruefung("strict-chain", _strikte_kette(ereignisse, erg))

    erg.pruefung("dag-tips", sorted(t.get("dag_tips", [])) == spitzen(ereignisse))
    return erg


def _strikte_kette(ereignisse: list[dict], erg: Ergebnis) -> bool:
    """Genau ein Anfang, jedes andere Ereignis hat genau einen Elternteil, keiner wird doppelt fortgesetzt."""
    if not ereignisse:
        erg.fehler.append("Strikte Kette: leer.")
        return False
    anfaenge = [e for e in ereignisse if not e.get("parent_hashes")]
    zaehler: dict[str, int] = {}
    for e in ereignisse:
        eltern = e.get("parent_hashes", [])
        if e["event_hash"] in eltern or (eltern and len(eltern) != 1):
            erg.fehler.append(f"Strikte Kette: Ereignis {e.get('event_id')} hat nicht genau einen Elternteil.")
            return False
        for p in eltern:
            zaehler[p] = zaehler.get(p, 0) + 1
    if len(anfaenge) != 1 or any(n > 1 for n in zaehler.values()):
        erg.fehler.append("Strikte Kette: Verzweigung oder mehrere Anfänge.")
        return False
    return True
