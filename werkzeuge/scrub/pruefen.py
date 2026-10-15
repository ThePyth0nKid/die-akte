#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prüft Dateien, Commits und die ganze Git-Historie auf Dinge, die nicht in ein öffentliches Repo gehören.

Zwei Regelsätze:
  * öffentlich: ``regeln_oeffentlich.txt`` neben diesem Skript (Benutzerpfade, private IP-Bereiche, Schlüsselmuster …)
  * privat:     eine Sperrliste, die NIE im Repo liegt. Gesucht in dieser Reihenfolge:
                ``$OSS_SCRUB_SPERRLISTE`` (Pfad), ``$OSS_SCRUB_SPERRLISTE_INHALT`` (Inhalt, z. B. aus einem CI-Secret),
                ``~/.config/oss-scrub/sperrliste.txt``.

Format beider Listen: eine Regex je Zeile, ``#`` = Kommentar, Groß-/Kleinschreibung egal (auch bei Umlauten).
Präfix ``CS:`` = mit Groß-/Kleinschreibung. Präfix ``HART:`` = gilt auch in Zeilen mit ``scrub:erlaubt`` (für
Schlüsselmuster: ein echter Schlüssel lässt sich nicht wegmarkieren). Beide Präfixe lassen sich kombinieren.

Treffer privater Regeln werden nie im Wortlaut ausgegeben (sonst stünde die Sperrliste im CI-Log), auch nicht über den
Dateinamen: Trifft eine private Regel einen Pfad, erscheint der Pfad nur verdeckt. Ausnahme: ``--zeigen`` auf dem
eigenen Rechner.

Eine Zeile mit ``scrub:erlaubt`` ist von ÖFFENTLICHEN Regeln ausgenommen; private Regeln gelten immer.

Im Zweifel ein Fund: Was sich nicht lesen lässt oder zu groß ist, gilt als nicht geprüft und lässt die Prüfung
scheitern (Grenze ``--max-mb``), ebenso verlinkte Ordner bei ``--pfad``. UTF-16 (auch ohne BOM) und Windows-1252
werden umkodiert, Text zusätzlich in Unicode-NFC geprüft (ein „ü“ aus u + Trema trifft dieselbe Regel wie ein
fertiges „ü“). ZIP-Container (auch DOCX, XLSX, PPTX) werden Datei für Datei geprüft. ``--historie`` prüft auch Tags
und verweigert flache Klone, denn dort fehlt Historie.

Einzige Ausnahme in der Historie: ``historie_ausnahmen.txt`` neben diesem Skript nennt schon veröffentlichte Commits,
deren Autoren- oder Committer-Name nicht geprüft wird (GitHub schreibt beim Zusammenführen den Profilnamen hinein:
beim Merge-Commit als Autor, beim Rebase als Committer). Sie gilt
nur für Commits, die schon auf ``origin/main`` liegen; ein Pull Request kann so keinen eigenen Commit freigeben. Beide
Mail-Adressen, Nachricht und Inhalt dieser Commits prüft ``--historie`` weiter; jede Ausnahme steht im Log.

Bilder (PNG, GIF, WebP) werden nach ihrem Aufbau gelesen: geprüft werden Metadaten (Text, auch gepackter, EXIF, XMP,
ICC, Kommentare) und jeder unbekannte Teil, nicht aber die Pixeldaten. Darin träfe eine Regel nur zufällig etwas.
Das schützt vor Versehen (Werkzeuge schreiben Pfade und Namen in Metadaten), nicht vor absichtlich in Pixel- oder
Farbdaten verstecktem Text.
Wirkt der Aufbau unsauber (falsche Prüfsumme oder Länge, Bytes hinter dem Ende), wird die ganze Datei geprüft.
JPEG, MP4 und alles andere werden immer ganz geprüft.

Nicht geprüft werden komprimierte PDF-Inhalte, Base64, Git-LFS-Objekte (nur deren Zeiger) und das, was ein Bild
zeigt. Für solche Dateien gilt: vor dem Commit selbst ansehen.

Aufrufe:
  pruefen.py --staged                 # vor dem Commit (Git-Hook)
  pruefen.py --alle                   # alle Dateien im Arbeitsbaum, die Git nicht ignoriert
  pruefen.py --historie               # jeder Commit: Inhalt, Dateinamen, Autor, Nachricht
  pruefen.py --pfad ORDNER            # beliebiger Ordner (alles außer .git; weitere mit --ohne NAME)
  pruefen.py --nachricht DATEI        # Commit-Nachricht (commit-msg-Hook)
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

HIER = Path(__file__).resolve().parent
OEFFENTLICH = HIER / "regeln_oeffentlich.txt"
AUSNAHMEN = HIER / "historie_ausnahmen.txt"
#: Was eine Ausnahme abdecken darf, mit der Zeile im Commit-Kopf (%an, %ae, %cn, %ce, %B): nur Namen, nie Mail
#: oder Nachricht.
AUSNAHME_FELDER = {"autor-name": 0, "committer-name": 2}
#: Eine Ausnahme gilt nur für Commits, die hier schon enthalten sind (fehlt der Verweis: keine Ausnahme).
AUSNAHME_BASIS = "refs/remotes/origin/main"
ERLAUBT_MARKE = "scrub:erlaubt"
MAX_MB = 50


@dataclass(frozen=True)
class Regel:
    nummer: int
    muster: re.Pattern[str]
    privat: bool
    quelle: str
    #: Gilt auch in Zeilen mit ``scrub:erlaubt``.
    hart: bool = False


#: Pseudo-Regel für alles, was nicht geprüft werden konnte (zu groß, unlesbar).
UNGEPRUEFT = Regel(0, re.compile("(?!)"), False, "nicht geprüft")
ZIP_MAX_DATEIEN = 2000


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
        flags, hart = re.IGNORECASE, False
        while zeile.startswith(("CS:", "HART:")):
            if zeile.startswith("CS:"):
                zeile, flags = zeile[3:], 0
            else:
                zeile, hart = zeile[5:], True
        try:
            muster = re.compile(unicodedata.normalize("NFC", zeile), flags)
        except re.error as fehler:
            # Bei der privaten Liste keine Musterteile ausgeben (die Meldung landet sonst im CI-Log).
            grund = "" if privat else f": {fehler}"
            raise SystemExit(f"Regel {quelle}:{nr} ist keine gültige Regex{grund}") from None
        regeln.append(Regel(nr, muster, privat, quelle, hart))
    return regeln


def _text_lesen(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8-sig")


def regeln_laden(nur_oeffentlich: bool = False) -> tuple[list[Regel], bool]:
    regeln = _regeln_lesen(_text_lesen(OEFFENTLICH), False, "öffentlich")
    if nur_oeffentlich:
        return regeln, False
    inhalt = None
    pfad = os.environ.get("OSS_SCRUB_SPERRLISTE")
    if pfad:
        if not Path(pfad).is_file():
            raise SystemExit("OSS_SCRUB_SPERRLISTE zeigt auf keine Datei. Pfad prüfen oder Variable entfernen.")
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


def _utf16_ohne_bom(daten: bytes) -> str | None:
    """UTF-16 ohne BOM erkennen: in Text aus lateinischen Zeichen ist jedes zweite Byte eine Null."""
    probe = daten[:4096]
    if len(probe) < 8 or probe.count(0) < len(probe) // 4:
        return None
    gerade, ungerade = probe[0::2].count(0), probe[1::2].count(0)
    if ungerade > len(probe) // 4 and gerade < ungerade // 8:
        return daten.decode("utf-16-le", "replace")
    if gerade > len(probe) // 4 and ungerade < gerade // 8:
        return daten.decode("utf-16-be", "replace")
    return None


def _fassungen(daten: bytes) -> list[str]:
    """Die Bytes Zeichen für Zeichen (Latin-1, damit Schlüsselmuster auch in Binärdateien treffen) und derselbe Inhalt
    als Text in Unicode-NFC (aus UTF-8, UTF-16 oder Windows-1252)."""
    roh = daten.decode("latin-1")
    text = None
    if daten[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = daten.decode("utf-16", "replace")
    elif (utf16 := _utf16_ohne_bom(daten)) is not None:
        text = utf16
    elif daten[:3] == b"\xef\xbb\xbf" or not daten.isascii():
        try:
            text = daten.decode("utf-8-sig")
        except UnicodeDecodeError:
            # Kein UTF-8: als Windows-1252 lesen, damit Regeln mit Umlauten auch alte Dateien treffen.
            text = daten.decode("cp1252", "replace")
    if text is None:
        return [roh]
    normal = unicodedata.normalize("NFC", text)
    return [roh] if normal == roh else [roh, normal]


# ─── Bilder: nur Metadaten und Unbekanntes, keine Pixeldaten ─────────────────────────────────────────────────

class _Unpruefbar(Exception):
    """Ein Teil des Bildes ließ sich nicht lesen (z. B. gepackter Text zu groß oder kaputt)."""


#: Reine Bild- und Farbdaten. Alles andere (auch jeder unbekannte Teil) wird geprüft.
_PNG_BILDDATEN = {b"IDAT", b"fdAT", b"PLTE", b"tRNS"}
_PNG_GEPACKT = {b"zTXt", b"iCCP"}  # Schlüsselwort \0 Verfahren Daten; iTXt hat ein eigenes Format
_WEBP_BILDDATEN = {b"VP8 ", b"VP8L", b"ALPH"}
MAX_BILD_TEILE = 10_000  # mehr Teile: ganze Datei prüfen


def _entpacken(gepackt: bytes, max_bytes: int) -> bytes:
    if max_bytes <= 0:  # 0 hieße für zlib: unbegrenzt
        raise _Unpruefbar("gepackter Bildtext zu groß")
    zerleger = zlib.decompressobj()
    try:
        inhalt = zerleger.decompress(gepackt, max_bytes)
    except zlib.error as fehler:
        raise _Unpruefbar(f"gepackter Bildtext unlesbar ({fehler})") from None
    if zerleger.unconsumed_tail:
        raise _Unpruefbar("gepackter Bildtext zu groß")
    if zerleger.unused_data:  # ein zweiter Strom dahinter bliebe sonst ungelesen
        raise _Unpruefbar("gepackter Bildtext mit Resten")
    return inhalt


def _hinter_nullen(inhalt: bytes, n: int) -> bytes:
    """Was nach dem n-ten Nullbyte steht (Schlüsselwort \\0 …)."""
    stuecke = inhalt.split(b"\0", n)
    if len(stuecke) <= n:
        raise _Unpruefbar("Bildtext unvollständig")
    return stuecke[n]


def _png_teile(daten: bytes, max_bytes: int) -> list[bytes] | None:
    pos, teile, rest = 8, [], max_bytes  # rest: was alle gepackten Texte zusammen entpackt groß sein dürfen
    while pos + 12 <= len(daten):
        laenge = int.from_bytes(daten[pos:pos + 4], "big")
        art = daten[pos + 4:pos + 8]
        ende = pos + 12 + laenge
        if not art.isalpha() or ende > len(daten):
            return None
        inhalt = daten[pos + 8:ende - 4]
        if zlib.crc32(art + inhalt) != int.from_bytes(daten[ende - 4:ende], "big"):
            return None
        pos = ende
        if art == b"IEND":
            return teile if pos == len(daten) else None  # Bytes hinter dem Ende: ganz prüfen
        if art in _PNG_BILDDATEN:
            continue
        teile.append(inhalt)
        gepackt = None
        if art in _PNG_GEPACKT:  # Schlüsselwort \0 Verfahren Daten
            gepackt = _hinter_nullen(inhalt, 1)[1:]
        elif art == b"iTXt":  # Schlüsselwort \0 Flag Verfahren Sprache \0 Übersetzung \0 Text
            hinten = _hinter_nullen(inhalt, 1)
            if hinten[:1] == b"\x01":
                gepackt = _hinter_nullen(hinten[2:], 2)
        if gepackt is not None:
            teile.append(_entpacken(gepackt, rest))
            rest -= len(teile[-1])
    return None  # kein IEND


def _gif_bloecke(daten: bytes, pos: int) -> tuple[bytes, int] | None:
    """Unterblöcke ab ``pos`` bis zum leeren Block: (Inhalt ohne Längenbytes, Position danach)."""
    inhalt = bytearray()
    while pos < len(daten):
        n = daten[pos]
        if n == 0:
            return bytes(inhalt), pos + 1
        if pos + 1 + n > len(daten):
            return None
        inhalt += daten[pos + 1:pos + 1 + n]
        pos += 1 + n
    return None


def _gif_teile(daten: bytes) -> list[bytes] | None:
    if len(daten) < 13:
        return None
    pos, teile = 13, []
    if daten[10] & 0x80:  # globale Farbtabelle
        pos += 3 * 2 ** ((daten[10] & 7) + 1)
    while pos < len(daten):
        marke = daten[pos]
        if marke == 0x3B:  # Ende
            return teile if pos + 1 == len(daten) else None
        if marke == 0x21 and pos + 2 <= len(daten):  # Erweiterung: Kommentar, Anwendung (XMP), Text …
            bloecke = _gif_bloecke(daten, pos + 2)
            if bloecke is None:
                return None
            inhalt, weiter = bloecke
            # Beides: XMP steht roh in den Blöcken (die Längenbytes sind Teil des Textes), Kommentare zerteilt.
            teile += [daten[pos:weiter], inhalt]
            pos = weiter
        elif marke == 0x2C and pos + 10 <= len(daten):  # Einzelbild: Farbtabelle und Pixel überspringen
            gepackt = daten[pos + 9]
            pos += 10 + (3 * 2 ** ((gepackt & 7) + 1) if gepackt & 0x80 else 0) + 1
            bloecke = _gif_bloecke(daten, pos)
            if bloecke is None:
                return None
            pos = bloecke[1]
        else:
            return None
    return None  # kein Ende


def _riff_teile(daten: bytes, pos: int, ende: int, tiefe: int) -> list[bytes] | None:
    teile: list[bytes] = []
    while pos < ende:
        if pos + 8 > ende:
            return None
        art, laenge = daten[pos:pos + 4], int.from_bytes(daten[pos + 4:pos + 8], "little")
        weiter = pos + 8 + laenge + (laenge & 1)
        if weiter > ende or (laenge & 1 and daten[weiter - 1] != 0):
            return None
        inhalt = daten[pos + 8:pos + 8 + laenge]
        if art == b"ANMF" and tiefe == 0:  # Animationsbild: 16 Bytes Lage und Dauer, dann eigene Teile
            innen = _riff_teile(daten, pos + 24, pos + 8 + laenge, 1) if laenge >= 16 else None
            if innen is None:
                return None
            teile += innen
        elif art not in _WEBP_BILDDATEN:
            teile.append(art + inhalt)
        pos = weiter
    return teile


def _bild_teile(daten: bytes, max_bytes: int) -> list[bytes] | None:
    """Die Teile eines PNG, GIF oder WebP, die geprüft werden; None heißt: kein solches Bild oder unsauber, also
    die ganze Datei prüfen."""
    teile = None
    if daten.startswith(b"\x89PNG\r\n\x1a\n"):
        teile = _png_teile(daten, max_bytes)
    elif daten[:6] in (b"GIF87a", b"GIF89a"):
        teile = _gif_teile(daten)
    elif daten[:4] == b"RIFF" and daten[8:12] == b"WEBP":
        if int.from_bytes(daten[4:8], "little") + 8 == len(daten):
            teile = _riff_teile(daten, 12, len(daten), 0)
    # Kein echtes Bild hat so viele Metadaten-Teile; jeder einzeln durch alle Regeln wäre nur langsam.
    return None if teile is None or len(teile) > MAX_BILD_TEILE else teile


def _pruefe_zip(ort: str, daten: bytes, regeln: list[Regel], max_bytes: int) -> list[Fund] | None:
    """ZIP-Container (auch DOCX, XLSX, PPTX) Datei für Datei; None, wenn es kein lesbares ZIP ist."""
    try:
        archiv = zipfile.ZipFile(io.BytesIO(daten))
        eintraege = [e for e in archiv.infolist() if not e.is_dir()]
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    if len(eintraege) > ZIP_MAX_DATEIEN or sum(e.file_size for e in eintraege) > max_bytes:
        return [_ungeprueft(ort, "ZIP-Inhalt zu groß")]
    funde: list[Fund] = []
    for e in eintraege:
        innen = f"{ort}!{e.filename}"
        funde += _pruefe_name(innen, regeln)
        try:
            funde += _pruefe_bytes(innen, archiv.read(e), regeln, max_bytes, tiefe=1)
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as fehler:
            funde.append(_ungeprueft(innen, f"unlesbar ({type(fehler).__name__})"))
    return funde


def _pruefe_bytes(ort: str, daten: bytes, regeln: list[Regel], max_bytes: int = MAX_MB * 1024 * 1024,
                  tiefe: int = 0) -> list[Fund]:
    funde: list[Fund] = []
    if tiefe == 0 and daten[:4] == b"PK\x03\x04":
        innen = _pruefe_zip(ort, daten, regeln, max_bytes)
        if innen is not None:
            funde += innen
    try:
        teile = _bild_teile(daten, max_bytes)
    except _Unpruefbar as grund:
        funde.append(_ungeprueft(ort, str(grund)))
        teile = None
    # Bei Bildern zählen die Zeilen durch alle geprüften Teile, nicht durch die Datei.
    gesehen: set[tuple[int, str, int]] = set()
    versatz = 0
    for teil in [daten] if teile is None else teile:
        laengste = 0
        for fassung in _fassungen(teil):
            zeilen = fassung.splitlines()
            laengste = max(laengste, len(zeilen))
            for zeilen_nr, zeile in enumerate(zeilen, start=versatz + 1):
                erlaubt = ERLAUBT_MARKE in zeile
                for regel in regeln:
                    if erlaubt and not regel.privat and not regel.hart:
                        continue
                    m = regel.muster.search(zeile)
                    if m and (zeilen_nr, regel.quelle, regel.nummer) not in gesehen:
                        gesehen.add((zeilen_nr, regel.quelle, regel.nummer))
                        funde.append(Fund(ort, zeilen_nr, regel, m.group(0)))
        versatz += laengste
    return funde


def _pruefe_name(name: str, regeln: list[Regel]) -> list[Fund]:
    funde, gesehen = [], set()
    for fassung in {name, unicodedata.normalize("NFC", name)}:
        for r in regeln:
            m = r.muster.search(fassung)
            if m and (r.quelle, r.nummer) not in gesehen:
                gesehen.add((r.quelle, r.nummer))
                funde.append(Fund(name, 0, r, m.group(0)))
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
            funde += _pruefe_bytes(name, pfad.read_bytes(), regeln, max_mb * 1024 * 1024)
        except OSError as fehler:
            funde.append(_ungeprueft(name, f"unlesbar ({type(fehler).__name__})"))
    return funde


def ordner_dateien(ordner: Path, ohne: set[str] | None = None) -> list[Path]:
    """Alle Dateien unter ``ordner`` außer ``.git`` und ausdrücklich genannten Ordnernamen. Verlinkte Ordner kommen
    als Eintrag mit; lesen lassen sie sich nicht, also werden sie zum Fund „nicht geprüft“."""
    weg = {".git"} | set(ohne or ())
    ergebnis = []
    for wurzel, verzeichnisse, dateien in os.walk(ordner):
        verzeichnisse[:] = [v for v in verzeichnisse if v not in weg]
        ergebnis += [Path(wurzel) / v for v in verzeichnisse if (Path(wurzel) / v).is_symlink()]
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
        funde += _pruefe_bytes(name, daten, regeln, max_mb * 1024 * 1024)
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


def _ausnahmen_lesen(pfad: Path) -> dict[str, set[str]]:
    """``<voller Commit-Hash> <Feld>`` je Zeile (Feld aus ``AUSNAHME_FELDER``), ``#`` = Kommentar.

    Jede andere Zeile bricht ab (im Zweifel prüfen).
    """
    if not pfad.exists():
        return {}
    ausnahmen: dict[str, set[str]] = {}
    for nr, roh in enumerate(pfad.read_text(encoding="utf-8").splitlines(), start=1):
        teile = roh.split("#", 1)[0].split()
        if not teile:
            continue
        if len(teile) != 2 or not re.fullmatch(r"[0-9a-f]{40}", teile[0]) or teile[1] not in AUSNAHME_FELDER:
            raise SystemExit(f"{pfad.name}:{nr}: erwartet „<voller Commit-Hash> autor-name|committer-name“.")
        ausnahmen.setdefault(teile[0], set()).add(teile[1])
    return ausnahmen


def _liegt_auf_basis(commit: str, wurzel: Path) -> bool:
    """Ist ``commit`` schon in ``AUSNAHME_BASIS`` enthalten? Fehlt der Verweis, nein (dann gilt keine Ausnahme)."""
    ergebnis = subprocess.run(["git", "merge-base", "--is-ancestor", commit, AUSNAHME_BASIS], cwd=wurzel,
                              capture_output=True)
    return ergebnis.returncode == 0


def historie_pruefen(regeln: list[Regel], max_mb: int = MAX_MB) -> list[Fund]:
    wurzel = repo_wurzel()
    if _git("rev-parse", "--is-shallow-repository", cwd=wurzel).strip() == b"true":
        raise SystemExit("Flacher Klon: Die Historie ist unvollständig. Erst `git fetch --unshallow` "
                         "(in GitHub Actions: fetch-depth: 0).")
    ausnahmen = _ausnahmen_lesen(AUSNAHMEN)
    genutzt: set[str] = set()
    funde: list[Fund] = []
    # Tags: Name, Verfasser und Nachricht annotierter Tags
    tags = _git("for-each-ref", "--format=%(refname)%0a%(taggername) %(taggeremail)%0a%(contents)", "refs/tags",
                cwd=wurzel)
    if tags.strip():
        funde += _pruefe_bytes("tags", tags, regeln)
    erster_ort: dict[str, str] = {}  # Blob → erster Ort (commit:name), damit jeder Blob nur einmal gelesen wird
    namen_gesehen: set[str] = set()
    for commit in _git("rev-list", "--all", cwd=wurzel).decode().split():
        kopf = _git("show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%B", commit, cwd=wurzel)
        felder = ausnahmen.get(commit)
        if felder:
            genutzt.add(commit)
            zeilen = kopf.split(b"\n")
            if len(zeilen) < 5:
                raise SystemExit(f"Unerwartetes Kopfformat in {commit[:12]}.")
            if _liegt_auf_basis(commit, wurzel):
                # Nur die Zeile des Felds ersetzen; die Zeilennummern der übrigen bleiben gleich.
                for feld in felder:
                    zeilen[AUSNAHME_FELDER[feld]] = b"(ausgenommen)"
                kopf = b"\n".join(zeilen)
                print(f"Ausnahme: {', '.join(sorted(felder))} von {commit[:12]} nicht geprüft ({AUSNAHMEN.name}).",
                      file=sys.stderr)
            else:
                print(f"Ausnahme für {commit[:12]} gilt nicht: nicht in {AUSNAHME_BASIS}.", file=sys.stderr)
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
    for commit in sorted(set(ausnahmen) - genutzt):
        print(f"Hinweis: Ausnahme für {commit[:12]} trifft keinen Commit ({AUSNAHMEN.name}).", file=sys.stderr)
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
