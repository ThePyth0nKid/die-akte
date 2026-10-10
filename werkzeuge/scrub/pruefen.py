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

Treffer privater Regeln werden nie im Wortlaut ausgegeben (sonst stünde die Sperrliste im CI-Log), auch nicht über den
Dateinamen: Trifft eine private Regel einen Pfad, erscheint der Pfad nur verdeckt. Ausnahme: ``--zeigen`` auf dem
eigenen Rechner.

Eine Zeile mit ``scrub:erlaubt`` ist von ÖFFENTLICHEN Regeln ausgenommen; private Regeln gelten immer.

Im Zweifel ein Fund: Was sich nicht lesen lässt oder zu groß ist, gilt als nicht geprüft und lässt die Prüfung
scheitern (Grenze ``--max-mb``). UTF-16-Dateien werden umkodiert, Text zusätzlich in Unicode-NFC geprüft (ein „ü“
aus u + Trema trifft dieselbe Regel wie ein fertiges „ü“). ``--historie`` verweigert flache Klone, denn dort fehlt
Historie.

Aufrufe:
  pruefen.py --staged                 # vor dem Commit (Git-Hook)
  pruefen.py --alle                   # alle Dateien im Arbeitsbaum, die Git nicht ignoriert
  pruefen.py --historie               # jeder Commit: Inhalt, Dateinamen, Autor, Nachricht
  pruefen.py --pfad ORDNER            # beliebiger Ordner (alles außer .git; weitere mit --ohne NAME)
  pruefen.py --nachricht DATEI        # Commit-Nachricht (commit-msg-Hook)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

HIER = Path(__file__).resolve().parent
OEFFENTLICH = HIER / "regeln_oeffentlich.txt"
ERLAUBT_MARKE = "scrub:erlaubt"
MAX_MB = 50


@dataclass(frozen=True)
class Regel:
    nummer: int
    muster: re.Pattern[bytes]
    privat: bool
    quelle: str


#: Pseudo-Regel für alles, was nicht geprüft werden konnte (zu groß, unlesbar).
UNGEPRUEFT = Regel(0, re.compile(b"(?!)"), False, "nicht geprüft")


@dataclass(frozen=True)
class Fund:
    ort: str
    zeile: int
    regel: Regel
    treffer: str


def _regeln_lesen(text: str, privat: bool, quelle: str) -> list[Regel]:
    regeln: list[Regel] = []
    for nr, roh in enumerate(text.splitlines(), start=1):
        zeile = roh.strip().lstrip("﻿")
        if not zeile or zeile.startswith("#"):
            continue
        flags = re.IGNORECASE
        if zeile.startswith("CS:"):
            zeile = zeile[3:]
            flags = 0
        try:
            muster = re.compile(unicodedata.normalize("NFC", zeile).encode("utf-8"), flags)
        except re.error as fehler:
            # Bei der privaten Liste keine Musterteile ausgeben (die Meldung landet sonst im CI-Log).
            grund = "" if privat else f": {fehler}"
            raise SystemExit(f"Regel {quelle}:{nr} ist keine gültige Regex{grund}") from None
        regeln.append(Regel(nr, muster, privat, quelle))
    return regeln


def _text_lesen(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8-sig")


def regeln_laden(nur_oeffentlich: bool = False) -> tuple[list[Regel], bool]:
    regeln = _regeln_lesen(_text_lesen(OEFFENTLICH), False, "öffentlich")
    if nur_oeffentlich:
        return regeln, False
    inhalt = None
    pfad = os.environ.get("OSS_SCRUB_SPERRLISTE")
    if pfad and Path(pfad).is_file():
        inhalt = _text_lesen(Path(pfad))
    elif os.environ.get("OSS_SCRUB_SPERRLISTE_INHALT"):
        inhalt = os.environ["OSS_SCRUB_SPERRLISTE_INHALT"]
    else:
        standard = Path.home() / ".config" / "oss-scrub" / "sperrliste.txt"
        if standard.is_file():
            inhalt = _text_lesen(standard)
    if inhalt is None:
        return regeln, False
    return regeln + _regeln_lesen(inhalt, True, "privat"), True


def _fassungen(daten: bytes) -> list[bytes]:
    """Die Bytes, so wie sie sind, und dieselben Zeichen in UTF-8-NFC (aus UTF-16 umkodiert bzw. normalisiert)."""
    text = None
    if daten[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = daten.decode("utf-16", "replace")
    elif daten[:3] == b"\xef\xbb\xbf" or not daten.isascii():
        try:
            text = daten.decode("utf-8-sig")
        except UnicodeDecodeError:
            # Kein UTF-8: als Windows-1252 lesen, damit Regeln mit Umlauten auch alte Dateien treffen.
            text = daten.decode("cp1252", "replace")
    if text is None:
        return [daten]
    normal = unicodedata.normalize("NFC", text).encode("utf-8")
    return [daten] if normal == daten else [daten, normal]


def _pruefe_bytes(ort: str, daten: bytes, regeln: list[Regel]) -> list[Fund]:
    funde: list[Fund] = []
    gesehen: set[tuple[int, str, int]] = set()
    for fassung in _fassungen(daten):
        for zeilen_nr, zeile in enumerate(fassung.splitlines(), start=1):
            erlaubt = ERLAUBT_MARKE.encode() in zeile
            for regel in regeln:
                if erlaubt and not regel.privat:
                    continue
                m = regel.muster.search(zeile)
                if m and (zeilen_nr, regel.quelle, regel.nummer) not in gesehen:
                    gesehen.add((zeilen_nr, regel.quelle, regel.nummer))
                    funde.append(Fund(ort, zeilen_nr, regel, m.group(0).decode("utf-8", "replace")))
    return funde


def _pruefe_name(name: str, regeln: list[Regel]) -> list[Fund]:
    funde, gesehen = [], set()
    for fassung in {name, unicodedata.normalize("NFC", name)}:
        for r in regeln:
            m = r.muster.search(fassung.encode("utf-8"))
            if m and (r.quelle, r.nummer) not in gesehen:
                gesehen.add((r.quelle, r.nummer))
                funde.append(Fund(name, 0, r, m.group(0).decode("utf-8", "replace")))
    return funde


def _ungeprueft(ort: str, grund: str) -> Fund:
    return Fund(ort, 0, UNGEPRUEFT, grund)


def _git(*args: str, cwd: Path) -> bytes:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True).stdout


def dateien_pruefen(pfade: list[Path], basis: Path, regeln: list[Regel], max_mb: int = MAX_MB) -> list[Fund]:
    funde: list[Fund] = []
    for pfad in pfade:
        name = pfad.relative_to(basis).as_posix() if pfad.is_absolute() else pfad.as_posix()
        funde += _pruefe_name(name, regeln)
        try:
            if pfad.stat().st_size > max_mb * 1024 * 1024:
                funde.append(_ungeprueft(name, f"größer als {max_mb} MB"))
                continue
            funde += _pruefe_bytes(name, pfad.read_bytes(), regeln)
        except OSError as fehler:
            funde.append(_ungeprueft(name, f"unlesbar ({type(fehler).__name__})"))
    return funde


def ordner_dateien(ordner: Path, ohne: set[str] | None = None) -> list[Path]:
    """Alle Dateien unter ``ordner`` außer ``.git`` und ausdrücklich genannten Ordnernamen."""
    weg = {".git"} | set(ohne or ())
    ergebnis = []
    for wurzel, verzeichnisse, dateien in os.walk(ordner):
        verzeichnisse[:] = [v for v in verzeichnisse if v not in weg]
        ergebnis += [Path(wurzel) / d for d in dateien]
    return sorted(ergebnis)


def repo_wurzel() -> Path:
    return Path(_git("rev-parse", "--show-toplevel", cwd=Path.cwd()).decode().strip())


def staged_pruefen(regeln: list[Regel], max_mb: int = MAX_MB) -> list[Fund]:
    wurzel = repo_wurzel()
    namen = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", cwd=wurzel).split(b"\0")
    funde: list[Fund] = []
    for roh in filter(None, namen):
        name = roh.decode("utf-8", "surrogateescape")
        funde += _pruefe_name(name, regeln)
        if _git("ls-files", "-s", "--", name, cwd=wurzel).startswith(b"160000"):
            continue  # Submodul (Gitlink): kein Inhalt in diesem Repo
        daten = _git("show", f":{name}", cwd=wurzel)
        if len(daten) > max_mb * 1024 * 1024:
            funde.append(_ungeprueft(name, f"größer als {max_mb} MB"))
            continue
        funde += _pruefe_bytes(name, daten, regeln)
    return funde


def alle_pruefen(regeln: list[Regel], max_mb: int = MAX_MB) -> list[Fund]:
    wurzel = repo_wurzel()
    namen = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard", cwd=wurzel).split(b"\0")
    pfade = [wurzel / n.decode("utf-8") for n in namen if n and (wurzel / n.decode("utf-8")).is_file()]
    return dateien_pruefen(pfade, wurzel, regeln, max_mb)


def _blobs_lesen(objekte: list[str], wurzel: Path, max_mb: int):
    """Alle Blobs in einem einzigen ``git cat-file --batch``; zu große werden nicht geladen (None)."""
    if not objekte:
        return
    prozess = subprocess.Popen(["git", "cat-file", "--batch"], cwd=wurzel, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE)
    try:
        for objekt in objekte:
            prozess.stdin.write(objekt.encode() + b"\n")
            prozess.stdin.flush()
            kopf = prozess.stdout.readline().split()
            if len(kopf) < 3:
                yield objekt, None
                continue
            groesse = int(kopf[2])
            daten = prozess.stdout.read(groesse)
            prozess.stdout.read(1)  # abschließender Zeilenumbruch
            yield objekt, (None if groesse > max_mb * 1024 * 1024 else daten)
    finally:
        prozess.stdin.close()
        prozess.wait()


def historie_pruefen(regeln: list[Regel], max_mb: int = MAX_MB) -> list[Fund]:
    wurzel = repo_wurzel()
    if _git("rev-parse", "--is-shallow-repository", cwd=wurzel).strip() == b"true":
        raise SystemExit("Flacher Klon: Die Historie ist unvollständig. Erst `git fetch --unshallow` "
                         "(in GitHub Actions: fetch-depth: 0).")
    funde: list[Fund] = []
    erster_ort: dict[str, str] = {}  # Blob → erster Ort (commit:name), damit jeder Blob nur einmal gelesen wird
    namen_gesehen: set[str] = set()
    for commit in _git("rev-list", "--all", cwd=wurzel).decode().split():
        kopf = _git("show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%B", commit, cwd=wurzel)
        funde += _pruefe_bytes(f"{commit[:12]}:kopf", kopf, regeln)
        for eintrag in filter(None, _git("ls-tree", "-r", "-z", commit, cwd=wurzel).split(b"\0")):
            meta, _, name_b = eintrag.partition(b"\t")
            art, objekt = meta.split(b" ")[1:3]
            if art != b"blob":
                continue
            name = name_b.decode("utf-8", "surrogateescape")
            if name not in namen_gesehen:
                namen_gesehen.add(name)
                funde += _pruefe_name(f"{commit[:12]}:{name}", regeln)
            erster_ort.setdefault(objekt.decode(), f"{commit[:12]}:{name}")
    for objekt, daten in _blobs_lesen(sorted(erster_ort), wurzel, max_mb):
        ort = erster_ort[objekt]
        if daten is None:
            funde.append(_ungeprueft(ort, f"größer als {max_mb} MB oder unlesbar"))
        else:
            funde += _pruefe_bytes(ort, daten, regeln)
    return funde


def _maskiert(treffer: str) -> str:
    """Kurzform eines Treffers für Logs: echte Schlüssel sollen nie vollständig im (CI-)Log stehen."""
    return f"{treffer[:4]!r}… ({len(treffer)} Zeichen)" if len(treffer) > 6 else "(kurz)"


_COMMIT = re.compile(r"^[0-9a-f]{12}:")


def _pfad(ort: str) -> str:
    """Der Pfad ohne vorangestellten Commit (``abc123def456:docs/x.md`` → ``docs/x.md``)."""
    return _COMMIT.sub("", ort, count=1)


def ausgeben(funde: list[Fund], zeigen: bool) -> None:
    # Pfade, die eine private Regel selbst trifft, erscheinen in keiner Zeile im Klartext, in keinem Commit.
    verdeckt = {_pfad(f.ort) for f in funde if f.regel.privat and f.zeile == 0}
    nummern = {pfad: i for i, pfad in enumerate(sorted(verdeckt), start=1)}
    for f in funde:
        if f.regel is UNGEPRUEFT:
            text = f"nicht geprüft: {f.treffer}"
        elif f.regel.privat and not zeigen:
            text = f"private Regel {f.regel.nummer}"
        elif zeigen:
            text = f"{f.regel.quelle} Regel {f.regel.nummer}: {f.treffer!r}"
        else:
            text = f"{f.regel.quelle} Regel {f.regel.nummer}: {_maskiert(f.treffer)} (Klartext mit --zeigen)"
        ort = f.ort if zeigen or _pfad(f.ort) not in verdeckt else f"(Pfad {nummern[_pfad(f.ort)]} verdeckt)"
        print(f"{ort}:{f.zeile}: {text}" if f.zeile else f"{ort} (Datei): {text}")


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
    p.add_argument("--max-mb", type=int, default=MAX_MB, help=f"größere Dateien gelten als Fund (Standard {MAX_MB})")
    p.add_argument("--ohne", action="append", default=[], metavar="NAME",
                   help="bei --pfad diesen Ordnernamen überspringen (mehrfach möglich)")
    a = p.parse_args(argv)
    for strom in (sys.stdout, sys.stderr):
        if hasattr(strom, "reconfigure"):
            strom.reconfigure(errors="replace")  # Dateinamen mit kaputter Kodierung brechen die Ausgabe nicht ab

    regeln, mit_privat = regeln_laden(a.nur_oeffentlich)
    if not mit_privat:
        hinweis = "Keine private Sperrliste gefunden; geprüft wird nur mit den öffentlichen Regeln."
        if a.privat_pflicht:
            print(f"FEHLER: {hinweis}", file=sys.stderr)
            return 2
        print(f"Hinweis: {hinweis}", file=sys.stderr)

    if a.staged:
        funde = staged_pruefen(regeln, a.max_mb)
    elif a.alle:
        funde = alle_pruefen(regeln, a.max_mb)
    elif a.historie:
        funde = historie_pruefen(regeln, a.max_mb)
    elif a.nachricht:
        funde = _pruefe_bytes("Commit-Nachricht", a.nachricht.read_bytes(), regeln)
    else:
        ordner = a.pfad.resolve()
        funde = dateien_pruefen(ordner_dateien(ordner, set(a.ohne)), ordner, regeln, a.max_mb)

    if funde:
        ausgeben(funde, a.zeigen)
        print(f"\n{len(funde)} Fund(e). Nichts davon darf öffentlich werden.", file=sys.stderr)
        return 1
    print("Sauber: keine Funde.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
