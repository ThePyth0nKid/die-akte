"""Byte-Gleichheit mit Atlas (festgenagelte Vektoren aus atlas-trust-core), Rundlauf und Manipulation."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from akte_beweis import (
    KodierFehler,
    b64url,
    b64url_lesen,
    buendel,
    buendel_hash,
    cbor,
    oeffentlicher_schluessel,
    pruefen,
    signieren,
    signing_input,
    trace,
    trace_pruefen,
    zusage,
)

# ─── Festgenagelte Vektoren aus Atlas (crates/atlas-trust-core/src/cose.rs, pubkey_bundle.rs) ──────────────────

PIN_V1 = ("a761766e61746c61732d74726163652d76316269646630314830303162747374323032362d30342d3237"
          "5431303a30303a30305a636b6964737370696666653a2f2f61746c61732f7465737467706172656e7473"
          "80677061796c6f6164a164747970656b6e6f64652e63726561746569776f726b73706163656777732d74"
          "657374")
PIN_DID = ("a861766e61746c61732d74726163652d76316269646630314830303162747374323032362d30342d3237"
           "5431303a30303a30305a636b6964737370696666653a2f2f61746c61732f7465737467706172656e7473"
           "80677061796c6f6164a164747970656b6e6f64652e63726561746569776f726b73706163656777732d74"
           "6573746a617574686f725f646964784a6469643a61746c61733a61343466343462336436633964346532"
           "633834623664343066366530653065386438653366326331613066396538643763366235613439333832"
           "373136303566")
PIN_BUENDEL = "f87e9a30a06963f8c13b30bcf1085f1d65afa149b8f5015f7af5c79107d3fe0c"


def test_signing_input_v1_byte_gleich_mit_atlas():
    roh = signing_input("ws-test", "01H001", "2026-04-27T10:00:00Z", "spiffe://atlas/test", [],
                        {"type": "node.create"})
    assert roh.hex() == PIN_V1


def test_signing_input_mit_author_did_byte_gleich_mit_atlas():
    did = "did:atlas:a44f44b3d6c9d4e2c84b6d40f6e0e0e8d8e3f2c1a0f9e8d7c6b5a4938271605f"
    roh = signing_input("ws-test", "01H001", "2026-04-27T10:00:00Z", "spiffe://atlas/test", [],
                        {"type": "node.create"}, did)
    assert roh.hex() == PIN_DID


def test_buendel_hash_byte_gleich_mit_atlas():
    b = {"schema": "atlas-pubkey-bundle-v1", "generated_at": "2026-01-01T00:00:00Z",
         "keys": {"spiffe://atlas/agent/cursor-001": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
                  "spiffe://atlas/human/sebastian.meinhardt@bankhaus-hagedorn.de":  # scrub:erlaubt (Atlas-Testvektor)
                  "QkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQg"}}
    assert buendel_hash(b) == PIN_BUENDEL


# ─── Kanonisches CBOR ─────────────────────────────────────────────────────────

def test_cbor_lehnt_gleitkomma_ab():
    with pytest.raises(KodierFehler):
        cbor({"betrag": 1.5})
    with pytest.raises(KodierFehler):
        cbor({"betrag": 1.0})


def test_cbor_grenzen_und_reihenfolge():
    assert cbor(2**64 - 1).hex() == "1bffffffffffffffff"
    assert cbor(-(2**63)).hex() == "3b7fffffffffffffff"
    with pytest.raises(KodierFehler):
        cbor(2**64)
    # Schlüssel nach Länge, dann bytewise: "b" vor "aa"; Einfügereihenfolge spielt keine Rolle.
    assert cbor({"aa": 1, "b": 2}) == cbor({"b": 2, "aa": 1})
    assert cbor({"aa": 1, "b": 2}).hex() == "a2616202626161" + "01"
    assert cbor(True) == b"\xf5" and cbor(None) == b"\xf6"


def test_b64url_streng():
    assert b64url_lesen(b64url(b"\x00\x01\x02")) == b"\x00\x01\x02"
    for falsch in ("AAE=", "AA+B", "AA/B"):
        with pytest.raises(ValueError):
            b64url_lesen(falsch)


# ─── Rundlauf und Manipulation ────────────────────────────────────────────────

def _kette(anzahl: int = 3):
    mensch, geraet = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    kid_m, kid_g = "akte-mensch:redaktion#abcd", "akte-geraet:probe"
    ws = "akte:test"
    ereignisse, eltern = [], []
    for i in range(anzahl):
        privat, kid = (geraet, kid_g) if i % 2 == 0 else (mensch, kid_m)
        typ = "akte.sicherung" if i % 2 == 0 else "akte.freigabe"
        e = signieren(privat, workspace=ws, event_id=f"01JA{i:022d}", ts=f"2026-10-10T12:00:0{i}Z", kid=kid,
                      eltern=eltern, payload={"type": typ, "inhalt_zusage": zusage({"nr": i}, "AAAAAAAAAAAAAAAAAAAAAA")})
        ereignisse.append(e)
        eltern = [e["event_hash"]]
    b = buendel({kid_m: oeffentlicher_schluessel(mensch), kid_g: oeffentlicher_schluessel(geraet)},
                "2026-10-10T12:00:00Z")
    return trace(ws, ereignisse, b, "2026-10-10T12:10:00Z"), b


def test_rundlauf_gueltig_und_strikte_kette():
    t, b = _kette()
    erg = trace_pruefen(t, b, strikte_kette=True)
    assert erg.gueltig, erg.fehler
    assert pruefen(t).gueltig


@pytest.mark.parametrize("eingriff", ["payload", "ts", "sig", "kid", "bundle", "eltern"])
def test_manipulation_wird_erkannt(eingriff):
    t, b = _kette()
    t, b = copy.deepcopy(t), copy.deepcopy(b)
    e = t["events"][1]
    if eingriff == "payload":
        e["payload"]["inhalt_zusage"] = "sha256:" + "0" * 64
    elif eingriff == "ts":
        e["ts"] = "2027-01-01T00:00:00Z"
    elif eingriff == "sig":
        e["signature"]["sig"] = b64url(bytes(64))
    elif eingriff == "kid":
        e["signature"]["kid"] = "akte-geraet:probe"
    elif eingriff == "bundle":
        b["keys"]["akte-geraet:probe"] = b64url(oeffentlicher_schluessel(Ed25519PrivateKey.generate()))
    elif eingriff == "eltern":
        e["parent_hashes"] = []
    assert not trace_pruefen(t, b, strikte_kette=True).gueltig


def test_richtlinie_freigabe_nur_durch_menschen():
    t, b = _kette()
    agent = Ed25519PrivateKey.generate()
    letzte = t["events"][-1]["event_hash"]
    falsch = signieren(agent, workspace=t["workspace_id"], event_id="01JZ", ts="2026-10-10T12:01:00Z",
                       kid="akte-agent:mcp", eltern=[letzte], payload={"type": "akte.freigabe", "inhalt_zusage": ""})
    t["events"].append(falsch)
    erg = pruefen(t)
    assert not erg.gueltig
    assert any("darf agent nicht" in f for f in erg.fehler)


def test_richtlinie_widerruf():
    mensch = Ed25519PrivateKey.generate()
    kid = "akte-mensch:redaktion#abcd"
    ws = "akte:test"
    w = signieren(mensch, workspace=ws, event_id="01", ts="2026-10-10T12:00:00Z", kid=kid, eltern=[],
                  payload={"type": "akte.widerruf", "kid": kid})
    danach = signieren(mensch, workspace=ws, event_id="02", ts="2026-10-10T12:00:01Z", kid=kid,
                       eltern=[w["event_hash"]], payload={"type": "akte.freigabe", "inhalt_zusage": ""})
    t = {"events": [w, danach]}
    erg = pruefen(t)
    assert not erg.gueltig and any("widerrufen" in f for f in erg.fehler)


def test_offenlegung_gegen_zusage():
    t, _ = _kette(1)
    e = t["events"][0]
    gut = {e["event_hash"]: {"salz": "AAAAAAAAAAAAAAAAAAAAAA", "inhalt": {"nr": 0}}}
    assert pruefen(t, gut).gueltig
    falsch = {e["event_hash"]: {"salz": "AAAAAAAAAAAAAAAAAAAAAA", "inhalt": {"nr": 1}}}
    assert not pruefen(t, falsch).gueltig


# ─── Golden-Trace von Atlas (wenn ein Atlas-Checkout da ist) ──────────────────

def _atlas_ordner() -> Path | None:
    for kandidat in (os.environ.get("ATLAS_REPO", ""), str(Path(__file__).resolve().parents[3] / "atlas")):
        if kandidat and (Path(kandidat) / "examples" / "golden-traces").is_dir():
            return Path(kandidat) / "examples" / "golden-traces"
    return None


@pytest.mark.skipif(_atlas_ordner() is None, reason="kein Atlas-Checkout (ATLAS_REPO setzen)")
def test_atlas_golden_trace_prueft_gueltig():
    ordner = _atlas_ordner()
    t = json.loads((ordner / "bank-q1-2026.trace.json").read_text(encoding="utf-8"))
    b = json.loads((ordner / "bank-q1-2026.pubkey-bundle.json").read_text(encoding="utf-8"))
    erg = trace_pruefen(t, b)
    assert erg.gueltig, erg.fehler
