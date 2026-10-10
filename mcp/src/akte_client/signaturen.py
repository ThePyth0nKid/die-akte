# SPDX-License-Identifier: MIT
"""Die Beweiskette einer Akte prüfen – ohne dem Server zu vertrauen.

Geprüft wird mit ``akte_beweis`` (Kette, Signaturen, strikte Reihenfolge, Rollen, Widerrufe, Offenlegungen) und auf
Wunsch zusätzlich mit dem WASM-Prüfer von Atlas (unabhängige Umsetzung in Rust).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .client import Akte


def laden(*, basis: str = "", datei: str = "", token: str | None = None) -> dict:
    if datei:
        return json.loads(Path(datei).read_text(encoding="utf-8"))
    if not basis:
        raise ValueError("--basis oder --datei angeben.")
    return Akte(basis, token).get("/beweis/export/")


def speichern(export: dict, ordner: Path) -> list[Path]:
    """Für Dritte: trace.json, buendel.json, offenlegung.json (der Atlas-Prüfer liest die ersten beiden)."""
    ordner.mkdir(parents=True, exist_ok=True)
    dateien = []
    for name in ("trace", "buendel", "offenlegung"):
        pfad = ordner / f"{name}.json"
        pfad.write_text(json.dumps(export.get(name, {}), ensure_ascii=False, indent=1), encoding="utf-8")
        dateien.append(pfad)
    return dateien


def _atlas_skript() -> Path | None:
    kandidat = Path(__file__).resolve().parents[3] / "beweis" / "kreuzpruefung" / "pruefen.mjs"
    if kandidat.exists() and (kandidat.parent / "node_modules" / "@atlas-trust").is_dir():
        return kandidat
    return None


def atlas_pruefen(export: dict) -> dict | None:
    """Mit dem WASM-Prüfer von Atlas prüfen, wenn Node und ``npm ci`` in beweis/kreuzpruefung vorhanden sind."""
    skript = _atlas_skript()
    if not skript or not shutil.which("node"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        t, b, _ = speichern(export, Path(tmp))
        lauf = subprocess.run(["node", str(skript), str(t), str(b)], capture_output=True, text=True, encoding="utf-8",
                              timeout=120)
    try:
        return json.loads(lauf.stdout)
    except ValueError:
        return {"valid": False, "errors": [lauf.stderr[-500:]]}


def pruefen(export: dict, *, mit_atlas: bool = False) -> dict:
    from akte_beweis import pruefen as richtlinie_pruefen
    from akte_beweis import trace_pruefen

    kette = trace_pruefen(export["trace"], export["buendel"], strikte_kette=bool(export["trace"].get("events")))
    regeln = richtlinie_pruefen(export["trace"], export.get("offenlegung") or {})
    ergebnis = {
        "gueltig": kette.gueltig and regeln.gueltig,
        "ereignisse": len(export["trace"].get("events", [])),
        "offengelegt": len(export.get("offenlegung") or {}),
        "kette": kette.als_dict(),
        "regeln": regeln.als_dict(),
    }
    if mit_atlas:
        atlas = atlas_pruefen(export)
        ergebnis["atlas"] = atlas if atlas is not None else {"hinweis": "Atlas-Prüfer nicht verfügbar (Node + npm ci)."}
        if atlas is not None:
            ergebnis["gueltig"] = ergebnis["gueltig"] and bool(atlas.get("valid"))
    return ergebnis
