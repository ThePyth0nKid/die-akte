"""akte pruefe-signaturen: gültige Kette → 0, manipulierte → 1 (ohne Pipe, echter Rückgabewert)."""

from __future__ import annotations

import json

import pytest

akte_beweis = pytest.importorskip("akte_beweis")
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from akte_client.cli import main  # noqa: E402


def _export() -> dict:
    privat = Ed25519PrivateKey.generate()
    kid = "akte-mensch:redaktion#0123456789abcdef"
    inhalt, salz = {"name": "Nordlicht Analytik GmbH"}, akte_beweis.neues_salz()
    e = akte_beweis.signieren(privat, workspace="akte:test", event_id="01X", ts="2026-10-10T12:00:00Z", kid=kid,
                              eltern=[], payload={"type": "akte.freigabe", "objekt": "karte", "objekt_id": 1,
                                                  "inhalt_zusage": akte_beweis.zusage(inhalt, salz)})
    b = akte_beweis.buendel({kid: akte_beweis.oeffentlicher_schluessel(privat)}, "2026-10-10T11:00:00Z")
    return {"trace": akte_beweis.trace("akte:test", [e], b, "2026-10-10T12:01:00Z"), "buendel": b,
            "offenlegung": {e["event_hash"]: {"salz": salz, "inhalt": inhalt}}}


def test_gueltige_kette(tmp_path, capsys):
    datei = tmp_path / "export.json"
    datei.write_text(json.dumps(_export()), encoding="utf-8")
    assert main(["pruefe-signaturen", "--datei", str(datei)]) == 0
    assert "GÜLTIG" in capsys.readouterr().out


@pytest.mark.parametrize("eingriff", ["payload", "offenlegung"])
def test_manipulation_gibt_1(tmp_path, eingriff):
    export = _export()
    if eingriff == "payload":
        export["trace"]["events"][0]["payload"]["objekt_id"] = 2
    else:
        eintrag = next(iter(export["offenlegung"].values()))
        eintrag["inhalt"] = {"name": "Kranich Holding AG"}
    datei = tmp_path / "export.json"
    datei.write_text(json.dumps(export), encoding="utf-8")
    assert main(["pruefe-signaturen", "--datei", str(datei)]) == 1


def test_speichern_fuer_dritte(tmp_path):
    datei = tmp_path / "export.json"
    datei.write_text(json.dumps(_export()), encoding="utf-8")
    assert main(["pruefe-signaturen", "--datei", str(datei), "--speichern", str(tmp_path / "fuer-dritte")]) == 0
    assert sorted(p.name for p in (tmp_path / "fuer-dritte").iterdir()) == ["buendel.json", "offenlegung.json",
                                                                             "trace.json"]
