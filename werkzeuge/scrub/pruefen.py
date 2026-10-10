#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prüft Dateien, Commits und die ganze Git-Historie auf Dinge, die nicht in ein öffentliches Repo gehören.

Zwei Regelsätze:
  * öffentlich: ``regeln_oeffentlich.txt`` neben diesem Skript (Benutzerpfade, private IP-Bereiche, Schlüsselmuster …)
  * privat:     eine Sperrliste, die NIE im Repo liegt. Gesucht in dieser Reihenfolge:
                ``$OSS_SCRUB_SPERRLISTE`` (Pfad), ``$OSS_SCRUB_SPERRLISTE_INHALT`` (Inhalt, z. B. aus einem CI-Secret),
                ``~/.config/oss-scrub/sperrliste.txt``.

Format beider Listen: eine Regex je Zeile, ``#`` = Kommentar, Groß-/Kleinschreibung egal.
Präfix ``CS:`` = mit Groß-/Kleinschreibung.

Treffer privater Regeln werden nie im Wortlaut ausgegeben (sonst stünde die Sperrliste im CI-Log),
außer mit ``--zeigen`` auf dem eigenen Rechner.

Eine Zeile mit ``scrub:erlaubt`` ist von ÖFFENTLICHEN Regeln ausgenommen; private Regeln gelten immer.

Aufrufe:
  pruefen.py --staged                 # vor dem Commit (Git-Hook)
  pruefen.py --alle                   # alle Dateien im Arbeitsbaum, die Git nicht ignoriert
  pruefen.py --historie               # jeder Commit: Inhalt, Dateinamen, Autor, Nachricht
  pruefen.py --pfad ORDNER            # beliebiger Ordner (z. B. Staging vor dem Kopieren)
  pruefen.py --nachricht DATEI        # Commit-Nachricht (commit-msg-Hook)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HIER = Path(__file__).resolve().parent
OEFFENTLICH = HIER / "regeln_oeffentlich.txt"
ERLAUBT_MARKE = "scrub:erlaubt"
MAX_BYTES = 50 * 1024 * 1024
UEBERSPRINGEN = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", ".mypy_cache",
                 ".pytest_cache", ".ruff_cache"}


@dataclass(frozen=True)
class Regel:
    nummer: int
    muster: re.Pattern[bytes]
    privat: bool
    quelle: str


@dataclass(frozen=True)
class Fund:
    ort: str
    zeile: int
    regel: Regel
    treffer: str


def _regeln_lesen(text: str, privat: bool, quelle: str) -> list[Regel]:
    regeln: list[Regel] = []
    for nr, roh in enumerate(text.splitlines(), start=1):
        zeile = roh.strip()
        if not zeile or zeile.startswith("#"):
            continue
        flags = re.IGNORECASE
        if zeile.startswith("CS:"):
            zeile = zeile[3:]
            flags = 0
        try:
            muster = re.compile(zeile.encode("utf-8"), flags)
        except re.error as fehler:
            # Bei der privaten Liste keine Musterteile ausgeben (die Meldung landet sonst im CI-Log).
            grund = "" if privat else f": {fehler}"
            raise SystemExit(f"Regel {quelle}:{nr} ist keine gültige Regex{grund}") from None
        regeln.append(Regel(nr, muster, privat, quelle))
    return regeln


def regeln_laden(nur_oeffentlich: bool = False) -> tuple[list[Regel], bool]:
    regeln = _regeln_lesen(OEFFENTLICH.read_text(encoding="utf-8"), False, "öffentlich")
    if nur_oeffentlich:
        return regeln, False
    inhalt = None
    pfad = os.environ.get("OSS_SCRUB_SPERRLISTE")
    if pfad and Path(pfad).is_file():
        inhalt = Path(pfad).read_text(encoding="utf-8")
    elif os.environ.get("OSS_SCRUB_SPERRLISTE_INHALT"):
        inhalt = os.environ["OSS_SCRUB_SPERRLISTE_INHALT"]
    else:
        standard = Path.home() / ".config" / "oss-scrub" / "sperrliste.txt"
        if standard.is_file():
            inhalt = standard.read_text(encoding="utf-8")
    if inhalt is None:
        return regeln, False
    return regeln + _regeln_lesen(inhalt, True, "privat"), True


def _pruefe_bytes(ort: str, daten: bytes, regeln: list[Regel]) -> list[Fund]:
    funde: list[Fund] = []
    for zeilen_nr, zeile in enumerate(daten.splitlines(), start=1):
        erlaubt = ERLAUBT_MARKE.encode() in zeile
        for regel in regeln:
            if erlaubt and not regel.privat:
                continue
            m = regel.muster.search(zeile)
            if m:
                funde.append(Fund(ort, zeilen_nr, regel, m.group(0).decode("utf-8", "replace")))
    return funde


def _pruefe_name(name: str, regeln: list[Regel]) -> list[Fund]:
    return [Fund(name, 0, r, m.group(0).decode("utf-8", "replace"))
            for r in regeln if (m := r.muster.search(name.encode("utf-8")))]


def _git(*args: str, cwd: Path) -> bytes:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True).stdout


def dateien_pruefen(pfade: list[Path], basis: Path, regeln: list[Regel]) -> list[Fund]:
    funde: list[Fund] = []
    for pfad in pfade:
        name = pfad.relative_to(basis).as_posix() if pfad.is_absolute() else pfad.as_posix()
        funde += _pruefe_name(name, regeln)
        try:
            if pfad.stat().st_size > MAX_BYTES:
                print(f"WARNUNG: {name} ist größer als {MAX_BYTES // 1024 // 1024} MB und wurde nicht gelesen.",
                      file=sys.stderr)
                continue
            funde += _pruefe_bytes(name, pfad.read_bytes(), regeln)
        except OSError as fehler:
            print(f"WARNUNG: {name}: {fehler}", file=sys.stderr)
    return funde


def ordner_dateien(ordner: Path) -> list[Path]:
    ergebnis = []
    for wurzel, verzeichnisse, dateien in os.walk(ordner):
        verzeichnisse[:] = [v for v in verzeichnisse if v not in UEBERSPRINGEN]
        ergebnis += [Path(wurzel) / d for d in dateien]
    return sorted(ergebnis)


def repo_wurzel() -> Path:
    return Path(_git("rev-parse", "--show-toplevel", cwd=Path.cwd()).decode().strip())


def staged_pruefen(regeln: list[Regel]) -> list[Fund]:
    wurzel = repo_wurzel()
    namen = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", cwd=wurzel).split(b"\0")
    funde: list[Fund] = []
    for roh in filter(None, namen):
        name = roh.decode("utf-8")
        funde += _pruefe_name(name, regeln)
        daten = _git("show", f":{name}", cwd=wurzel)
        funde += _pruefe_bytes(name, daten, regeln)
    return funde


def alle_pruefen(regeln: list[Regel]) -> list[Fund]:
    wurzel = repo_wurzel()
    namen = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard", cwd=wurzel).split(b"\0")
    pfade = [wurzel / n.decode("utf-8") for n in namen if n and (wurzel / n.decode("utf-8")).is_file()]
    return dateien_pruefen(pfade, wurzel, regeln)


def historie_pruefen(regeln: list[Regel]) -> list[Fund]:
    wurzel = repo_wurzel()
    funde: list[Fund] = []
    commits = _git("rev-list", "--all", cwd=wurzel).decode().split()
    for commit in commits:
        kopf = _git("show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%B", commit, cwd=wurzel)
        funde += _pruefe_bytes(f"{commit[:12]}:kopf", kopf, regeln)
        baum = _git("ls-tree", "-r", "-z", commit, cwd=wurzel).split(b"\0")
        for eintrag in filter(None, baum):
            meta, _, name_b = eintrag.partition(b"\t")
            art, objekt = meta.split(b" ")[1:3]
            if art != b"blob":
                continue
            name = name_b.decode("utf-8")
            funde += _pruefe_name(f"{commit[:12]}:{name}", regeln)
            funde += _pruefe_bytes(f"{commit[:12]}:{name}", _git("cat-file", "blob", objekt.decode(), cwd=wurzel),
                                   regeln)
    # gleiche Blobs in mehreren Commits nur einmal melden
    gesehen, eindeutig = set(), []
    for f in funde:
        schluessel = (f.ort.split(":", 1)[-1], f.zeile, f.regel.quelle, f.regel.nummer)
        if schluessel not in gesehen:
            gesehen.add(schluessel)
            eindeutig.append(f)
    return eindeutig


def _maskiert(treffer: str) -> str:
    """Kurzform eines Treffers für Logs: echte Schlüssel sollen nie vollständig im (CI-)Log stehen."""
    return f"{treffer[:4]!r}… ({len(treffer)} Zeichen)" if len(treffer) > 6 else "(kurz)"


def ausgeben(funde: list[Fund], zeigen: bool) -> None:
    for f in funde:
        if f.regel.privat and not zeigen:
            text = f"private Regel {f.regel.nummer}"
        elif zeigen:
            text = f"{f.regel.quelle} Regel {f.regel.nummer}: {f.treffer!r}"
        else:
            text = f"{f.regel.quelle} Regel {f.regel.nummer}: {_maskiert(f.treffer)} (Klartext mit --zeigen)"
        ort = f"{f.ort}:{f.zeile}" if f.zeile else f"{f.ort} (Dateiname)"
        print(f"{ort}: {text}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modus = p.add_mutually_exclusive_group(required=True)
    modus.add_argument("--staged", action="store_true")
    modus.add_argument("--alle", action="store_true")
    modus.add_argument("--historie", action="store_true")
    modus.add_argument("--pfad", type=Path)
    modus.add_argument("--nachricht", type=Path)
    p.add_argument("--nur-oeffentlich", action="store_true", help="private Sperrliste nicht laden")
    p.add_argument("--zeigen", action="store_true", help="auch Treffer privater Regeln im Wortlaut zeigen")
    p.add_argument("--privat-pflicht", action="store_true", help="Fehler, wenn keine private Sperrliste gefunden wird")
    a = p.parse_args(argv)

    regeln, mit_privat = regeln_laden(a.nur_oeffentlich)
    if not mit_privat:
        hinweis = "Keine private Sperrliste gefunden; geprüft wird nur mit den öffentlichen Regeln."
        if a.privat_pflicht:
            print(f"FEHLER: {hinweis}", file=sys.stderr)
            return 2
        print(f"Hinweis: {hinweis}", file=sys.stderr)

    if a.staged:
        funde = staged_pruefen(regeln)
    elif a.alle:
        funde = alle_pruefen(regeln)
    elif a.historie:
        funde = historie_pruefen(regeln)
    elif a.nachricht:
        funde = _pruefe_bytes("Commit-Nachricht", a.nachricht.read_bytes(), regeln)
    else:
        ordner = a.pfad.resolve()
        funde = dateien_pruefen(ordner_dateien(ordner), ordner, regeln)

    if funde:
        ausgeben(funde, a.zeigen)
        print(f"\n{len(funde)} Fund(e). Nichts davon darf öffentlich werden.", file=sys.stderr)
        return 1
    print("Sauber: keine Funde.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
