"""Review-Funde: Widerruf nach Abstammung, Reihenfolge, bösartige Eingaben ohne Absturz, strenges Zeitformat."""

from __future__ import annotations

import copy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from akte_beweis import (
    KodierFehler,
    buendel,
    kanonisches_json,
    neues_salz,
    oeffentlicher_schluessel,
    pruefen,
    signieren,
    trace,
    trace_pruefen,
    zusage,
)
from akte_beweis.atlas import _rfc3339

KID = "akte-mensch:0123456789abcdef"


def _kette_mit_widerruf():
    privat = Ed25519PrivateKey.generate()
    ws, ereignisse, eltern = "akte:test", [], []
    plan = [{"type": "akte.freigabe", "inhalt_zusage": zusage({"n": 1}, neues_salz())},
            {"type": "akte.widerruf", "kid": KID},
            {"type": "akte.freigabe", "inhalt_zusage": zusage({"n": 2}, neues_salz())}]
    for i, payload in enumerate(plan):
        e = signieren(privat, workspace=ws, event_id=f"0{i}", ts=f"2026-10-10T12:00:0{i}Z", kid=KID, eltern=eltern,
                      payload=payload)
        ereignisse.append(e)
        eltern = [e["event_hash"]]
    b = buendel({KID: oeffentlicher_schluessel(privat)}, "2026-10-10T11:00:00Z")
    return trace(ws, ereignisse, b, "2026-10-10T12:01:00Z"), b


def test_ereignis_nach_widerruf_ist_ungueltig():
    t, _ = _kette_mit_widerruf()
    erg = pruefen(t)
    assert not erg.gueltig
    assert any("widerrufen" in f for f in erg.fehler)


def test_umsortieren_hilft_nicht():
    """Das Ereignis nach dem Widerruf in der Liste vor ihn schieben: die Abstammung verrät es trotzdem."""
    t, b = _kette_mit_widerruf()
    t2 = copy.deepcopy(t)
    t2["events"] = [t2["events"][0], t2["events"][2], t2["events"][1]]
    erg = pruefen(t2)
    assert not erg.gueltig
    assert any("widerrufen" in f for f in erg.fehler)
    assert any("Kettenreihenfolge" in f for f in erg.fehler)
    # Für Atlas bleibt der Trace formal gültig (Reihenfolge der Liste ist dort egal) – die Akte-Richtlinie nicht.
    assert trace_pruefen(t2, b, strikte_kette=True).gueltig


@pytest.mark.parametrize("eingriff", [
    "hash_umlaut", "bundle_hash_umlaut", "surrogat_payload", "surrogat_kid", "ohne_event_hash", "ohne_ts",
    "payload_liste", "signatur_kein_objekt", "events_kein_array", "eltern_kein_array", "tips_unsinn",
])
def test_boesartige_eingaben_stuerzen_nicht_ab(eingriff):
    t, b = _kette_mit_widerruf()
    t, b = copy.deepcopy(t), copy.deepcopy(b)
    e = t["events"][0]
    if eingriff == "hash_umlaut":
        e["event_hash"] = "é" * 64
    elif eingriff == "bundle_hash_umlaut":
        t["pubkey_bundle_hash"] = "ü"
    elif eingriff == "surrogat_payload":
        e["payload"]["x"] = "\ud800"
    elif eingriff == "surrogat_kid":
        e["signature"]["kid"] = "\ud800"
    elif eingriff == "ohne_event_hash":
        del e["event_hash"]
    elif eingriff == "ohne_ts":
        del e["ts"]
    elif eingriff == "payload_liste":
        e["payload"] = ["kein", "objekt"]
    elif eingriff == "signatur_kein_objekt":
        e["signature"] = "x"
    elif eingriff == "events_kein_array":
        t["events"] = {"a": 1}
    elif eingriff == "eltern_kein_array":
        t["events"][1]["parent_hashes"] = "x"
    elif eingriff == "tips_unsinn":
        t["dag_tips"] = [1, None]
    assert not trace_pruefen(t, b, strikte_kette=True).gueltig
    pruefen(t, {"x": "kein objekt"})  # darf nicht werfen


@pytest.mark.parametrize("ts,gueltig", [
    ("2026-10-10T12:00:00Z", True), ("2026-10-10T12:00:00.123Z", True), ("2026-10-10T12:00:00+02:00", True),
    ("2025-01-01T00:00Z", False), ("2025-01-01T00:00:00+0100", False), ("2025-W01-1T00:00:00Z", False),
    ("20250101T000000Z", False), ("2025-13-01T00:00:00Z", False), (None, False),
])
def test_rfc3339_streng(ts, gueltig):
    assert _rfc3339(ts) is gueltig


def test_kanonisches_json_lehnt_verschachtelte_gleitkommazahl_ab():
    with pytest.raises(KodierFehler):
        kanonisches_json({"a": [1, {"b": 0.5}]})


def test_zu_kurzes_salz_wird_abgelehnt():
    with pytest.raises(ValueError):
        zusage({"a": 1}, "")
    with pytest.raises(ValueError):
        zusage({"a": 1}, "AAAA")
