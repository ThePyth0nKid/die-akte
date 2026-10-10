"""Unabhängige Gegenprobe: Traces aus dieser Python-Bibliothek prüft der WASM-Prüfer von Atlas (Rust).

Braucht Node und ``npm ci`` in ``beweis/kreuzpruefung``; sonst wird übersprungen (in der CI läuft es immer).
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from akte_beweis import b64url, buendel, neues_salz, oeffentlicher_schluessel, signieren, trace, zusage

ORDNER = Path(__file__).resolve().parents[1] / "kreuzpruefung"
BEREIT = shutil.which("node") and (ORDNER / "node_modules" / "@atlas-trust" / "verify-wasm").is_dir()
pytestmark = pytest.mark.skipif(not BEREIT, reason="Node oder npm ci in beweis/kreuzpruefung fehlt")


def _akte_trace() -> tuple[dict, dict]:
    mensch, geraet = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    kid_m, kid_g = "akte-mensch:redaktion#3f9a1c2b4d5e6f70", "akte-geraet:musterhafen"
    ws = "akte:9b2e4f10-0000-4000-8000-000000000001"
    ereignisse, eltern = [], []
    plan = [
        (geraet, kid_g, {"type": "akte.sicherung", "art": "original", "sha256": "ab" * 32, "bytes": 182311,
                         "gesichert_am": "2026-10-10T12:00:00Z", "inhalt_zusage": zusage({"url": "https://x.test/a"},
                                                                                          neues_salz())}),
        (mensch, kid_m, {"type": "akte.ueberstimmung", "befund": "quelle_ohne_archiv",
                         "begruendung_zusage": zusage("Archiv drosselt, Original mit Prüfsumme liegt vor",
                                                      neues_salz())}),
        (mensch, kid_m, {"type": "akte.freigabe", "objekt": "faden", "objekt_id": 17,
                         "inhalt_zusage": zusage({"von": "Senat", "nach": "Nordlicht", "betrag": "1250000.00"},
                                                 neues_salz()), "belege": 1}),
    ]
    for i, (privat, kid, payload) in enumerate(plan):
        e = signieren(privat, workspace=ws, event_id=f"01JAKTE{i:019d}", ts=f"2026-10-10T12:00:0{i}Z", kid=kid,
                      eltern=eltern, payload=payload)
        ereignisse.append(e)
        eltern = [e["event_hash"]]
    b = buendel({kid_m: oeffentlicher_schluessel(mensch), kid_g: oeffentlicher_schluessel(geraet)},
                "2026-10-10T11:59:00Z")
    return trace(ws, ereignisse, b, "2026-10-10T12:05:00Z"), b


def _atlas_prueft(t: dict, b: dict, tmp_path: Path) -> dict:
    (tmp_path / "trace.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "buendel.json").write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    lauf = subprocess.run(["node", str(ORDNER / "pruefen.mjs"), str(tmp_path / "trace.json"), str(tmp_path / "buendel.json")],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    return json.loads(lauf.stdout)


def test_atlas_wasm_prueft_akte_trace_gueltig(tmp_path):
    t, b = _akte_trace()
    ergebnis = _atlas_prueft(t, b, tmp_path)
    assert ergebnis["valid"], ergebnis.get("errors")
    checks = {e["check"]: e["ok"] for e in ergebnis["evidence"]}
    assert checks["event-signatures"] and checks["event-hashes"] and checks["pubkey-bundle-hash"]


@pytest.mark.parametrize("eingriff", ["payload", "signatur", "schluessel"])
def test_atlas_wasm_erkennt_manipulation(tmp_path, eingriff):
    t, b = _akte_trace()
    t, b = copy.deepcopy(t), copy.deepcopy(b)
    if eingriff == "payload":
        t["events"][2]["payload"]["objekt_id"] = 18
    elif eingriff == "signatur":
        t["events"][2]["signature"]["sig"] = b64url(bytes(64))
    else:
        b["keys"]["akte-mensch:redaktion#3f9a1c2b4d5e6f70"] = b64url(
            oeffentlicher_schluessel(Ed25519PrivateKey.generate()))
    assert not _atlas_prueft(t, b, tmp_path)["valid"]
