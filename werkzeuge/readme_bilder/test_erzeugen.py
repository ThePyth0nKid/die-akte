# SPDX-License-Identifier: MIT
"""Tests für das README-Werkzeug: Anker wie GitHub, die README-Prüfung und eine stimmige Szenenliste.

Browser und laufende Akte braucht hier nichts; das Erzeugen selbst prüft man mit dem Kontaktbogen (Tor 4).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
_spec = importlib.util.spec_from_file_location("readme_erzeugen", HIER / "erzeugen.py")
erzeugen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(erzeugen)
import szenen  # noqa: E402


def test_anker_wie_github():
    assert erzeugen._slug("Für KI-Agenten: so richtest du die Akte für deinen Menschen ein") == \
        "für-ki-agenten-so-richtest-du-die-akte-für-deinen-menschen-ein"
    assert erzeugen._slug("Schnellstart in drei Schritten (Windows)") == "schnellstart-in-drei-schritten-windows"
    assert erzeugen._slug("Beweiskette prüfen – ohne dem Server zu vertrauen") == \
        "beweiskette-prüfen--ohne-dem-server-zu-vertrauen"
    assert erzeugen._slug("Was deinen Rechner verlässt") == "was-deinen-rechner-verlässt"


def _readme(tmp_path: Path, text: str) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "da.md").write_text("x", encoding="utf-8")
    datei = tmp_path / "README.md"
    datei.write_text(text, encoding="utf-8")
    return datei


def test_readme_pruefung_findet_fehler(tmp_path):
    medien = tmp_path / "medien"
    medien.mkdir()
    (medien / "kopf.webp").write_bytes(b"x")
    text = """# Titel
## Was die Akte kann
[gut](#was-die-akte-kann) [schlecht](#gibt-es-nicht) [da](docs/da.md) [weg](docs/weg.md)
![Kopfbild der Wand (erfundene Demo-Daten)](docs/bilder/readme/kopf.webp)
![kurz](docs/bilder/readme/kopf.webp)
<img src="docs/bilder/readme/fehlt.webp" alt="Ein Bild, das fehlt (erfundene Demo-Daten)">
<img src="docs/bilder/readme/kopf.webp">
[Version](docs/bilder/readme/v0.2.0/x.webp)
```
[im Code](#zaehlt-nicht)
```
"""
    befunde = erzeugen.readme_pruefen(_readme(tmp_path, text), medien)
    assert "Anker fehlt: #gibt-es-nicht" in befunde
    assert "Ziel fehlt: docs/weg.md" in befunde
    assert "Ziel fehlt: docs/bilder/readme/fehlt.webp" in befunde
    assert any(b.startswith("Alt-Text zu kurz") for b in befunde)
    assert any(b.startswith("Bild ohne Alt-Text") for b in befunde)
    assert any(b.startswith("Versionsnummer im Pfad") for b in befunde)
    assert not any("zaehlt-nicht" in b or "was-die-akte-kann" in b or "docs/da.md" in b for b in befunde)


def test_doppelte_ueberschriften_bekommen_nummern(tmp_path):
    text = "# A\n## Mehr\n## Mehr\n[eins](#mehr) [zwei](#mehr-1) [drei](#mehr-2) [null](#mehr-0)\n"
    befunde = erzeugen.readme_pruefen(_readme(tmp_path, text), tmp_path)
    assert befunde == ["Anker fehlt: #mehr-2", "Anker fehlt: #mehr-0"]


def test_code_badges_und_srcset(tmp_path):
    text = """# A
~~~
[im Zaun](#nicht-pruefen)
~~~
Text mit `[inline](#auch-nicht)` und [![Abzeichen der Version](docs/da.md)](docs/fehlt.md)
<img src='docs/da.md' alt="Ein ausreichend langer Text" srcset="docs/da.md 1x, docs/weg.md 2x">
"""
    befunde = erzeugen.readme_pruefen(_readme(tmp_path, text), tmp_path)
    assert sorted(befunde) == ["Ziel fehlt: docs/fehlt.md", "Ziel fehlt: docs/weg.md"]


def test_anker_aus_ueberschrift_mit_link_und_schluss_raute():
    assert erzeugen._slug("[Erste Schritte](docs/x.md) mit Bildern ##") == "erste-schritte-mit-bildern"


def test_terminal_farben():
    assert 'class="gut"' in erzeugen._farbig('  "ergebnis": "gefunden",')
    assert 'class="nein"' in erzeugen._farbig('  "ergebnis": "nicht_gefunden",')
    assert 'class="ok"' in erzeugen._farbig("  ✓ strict-chain")
    grund = erzeugen._farbig('  "grund": "Das Zitat steht <so> da",')
    assert "<span" not in grund and "&lt;so&gt;" in grund


def test_zu_grosse_readme(tmp_path):
    befunde = erzeugen.readme_pruefen(_readme(tmp_path, "# A\n" + "x" * (501 * 1024)), tmp_path)
    assert any("500 KiB" in b for b in befunde)


def test_szenen_passen_zusammen():
    alle_karten = {name for b in szenen.BUEHNEN.values() for name in b["karten"]}
    assert {name for name, _, _ in szenen.GALERIE} <= alle_karten
    assert set(szenen.KOPF) == set(szenen.BUEHNEN["readme-kopf"]["karten"])
    for sz in szenen.STANDBILDER:
        assert sz["format"] in erzeugen.FORMATE
    assert all(name.endswith(".webp") for name in szenen.MEDIEN)
    assert all((HIER / "marken" / name).exists() for name in szenen.MARKEN)
    assert sum(kb for _, kb in szenen.MEDIEN.values()) <= szenen.GESAMT_KB
    assert {f["board"] for f in szenen.FAHRTEN} <= set(szenen.BUEHNEN) | {szenen.DEMO}
    karten = next(f for f in szenen.FAHRTEN if f["board"] == "readme-karten")
    assert len(karten["stationen"]) == len(szenen.GALERIE)
