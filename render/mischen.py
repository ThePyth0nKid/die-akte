#!/usr/bin/env python3
"""Ton für ein gesichtsloses Akte-Video: Stimme, Musik mit Ducking, Klänge auf den Kamerabewegungen.

Jede Spur einzeln auf ihren Pegel, dann mischen: Stimme −16 LUFS, Musik −30 LUFS mit Sidechain unter der Stimme,
Klänge je Ereignis −27 LUFS; Summe −14 LUFS, True Peak −1,5 dB. Klänge nur mit geklärter Lizenz.

    python render/mischen.py <video.mp4> --stimme <ordner mit stimme.wav, zeiten.json>
        --video-yaml kapitel.yaml --auftrag auftrag_*.json --musik musik_1.mp3 --aus <ziel.mp4>
        [--klaenge <ordner mit _BANK.json>]

Ohne Klangbank (``--klaenge`` bzw. ``AKTE_KLANGBANK``) gibt es keine Effektklänge, Stimme und Musik bleiben.

Ausgabe: fertiges MP4 (Video kopiert, AAC 48 kHz), daneben Stems (stimme/musik/klaenge .wav) und die Klangliste.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

BANK = Path(os.environ["AKTE_KLANGBANK"]) if os.environ.get("AKTE_KLANGBANK") else None
ZIEL_STIMME, ZIEL_MUSIK, ZIEL_KLANG, ZIEL_SUMME = -16.0, -30.0, -27.0, -14.0

#: Einspieler nur aus diesen Ordnern — gleiche Liste wie EINSPIELER_WURZELN in render_fahrt.cjs.
EINSPIELER_WURZELN = [
    Path(w).resolve()
    for w in (os.environ.get("AKTE_EINSPIELER_WURZELN") or "").split(";") if w
]


def pruefe_einspieler(e: dict) -> tuple[Path, float, float]:
    """Pfad (echt, existiert, Video, in erlaubtem Ordner) und Grenzen prüfen, bevor ffmpeg ihn liest."""
    try:
        datei = Path(str(e["datei"])).resolve(strict=True)
        ab, bis = float(e.get("ab", 0)), float(e["bis"])
    except (KeyError, OSError, TypeError, ValueError):
        raise SystemExit(f"Einspieler ungültig: {e.get('datei')!r}") from None
    if datei.suffix.lower() not in {".mp4", ".mov", ".webm", ".mkv"}:
        raise SystemExit(f"Einspieler ist kein Video: {datei}")
    if not any(datei.is_relative_to(w) for w in EINSPIELER_WURZELN):
        raise SystemExit(f"Einspieler außerhalb der erlaubten Ordner: {datei}")
    if not 0 <= ab < bis <= ab + 30:
        raise SystemExit(f"Einspieler-Ausschnitt ungültig: {ab}–{bis}")
    return datei, ab, bis

#: Welcher Klang wofür (Kennungen aus _BANK.json; eine Bank kann das mit dem Eintrag "_zuordnung" ändern).
KLANG = {
    "auftakt": "vir_stich_cinematic_whoosh_deep",
    "flug_lang": "ueb_swoosh_lang",
    "flug_kurz": "ueb_swoosh_kurz",
    "beweis": "ueb_bass_stich",
    "zahl": "vir_bass_short_bass_hit",
    "riser": "ueb_riser",
    "pointe": "ueb_sub_drop",
    "einspieler": "ueb_glitch",
}


def lauf(befehl: list[str]) -> str:
    r = subprocess.run(befehl, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise SystemExit(f"{befehl[0]} scheiterte: {r.stderr[-800:]}")
    return r.stderr


def lautheit(datei: Path) -> float:
    """Integrierte Lautheit (LUFS) nach EBU R128."""
    aus = lauf(["ffmpeg", "-hide_banner", "-nostats", "-i", str(datei), "-af", "ebur128=framelog=quiet", "-f", "null", "-"])
    werte = re.findall(r"I:\s+(-?[\d.]+) LUFS", aus)  # scrub:erlaubt (ffmpeg-Ausgabe)
    return float(werte[-1]) if werte else -70.0


#: Mehr Verstärkung hebt nur Rauschen an: Eine so leise Spur ist kaputt oder falsch gewählt.
MAX_GEWINN_DB = 24.0
STUMM_LUFS = -60.0


def gewinn_fuer(ziel_lufs: float, gemessen: float, was: str) -> float:
    """Verstärkung auf die Ziel-Lautheit, gedeckelt. Eine stumme Spur bricht ab, statt Rauschen hochzuziehen."""
    if gemessen <= STUMM_LUFS:
        raise SystemExit(f"{was} ist praktisch stumm ({gemessen:.1f} LUFS). Datei prüfen.")
    gewinn = ziel_lufs - gemessen
    if gewinn > MAX_GEWINN_DB:
        print(f"Hinweis: {was} ist sehr leise ({gemessen:.1f} LUFS); Verstärkung auf +{MAX_GEWINN_DB:.0f} dB begrenzt.",
              file=sys.stderr)
        gewinn = MAX_GEWINN_DB
    return gewinn


def auf_pegel(quelle: Path, ziel: Path, lufs: float, extra: str = "") -> None:
    """Linear auf Ziel-Lautheit bringen (kein Kompressor, das Verhältnis der Spur bleibt)."""
    gewinn = gewinn_fuer(lufs, lautheit(quelle), quelle.name)
    filter_ = f"volume={gewinn:.2f}dB" + (f",{extra}" if extra else "")
    lauf(["ffmpeg", "-v", "error", "-y", "-i", str(quelle), "-af", filter_, "-ac", "2", "-ar", "48000", str(ziel)])


def _bank() -> dict:
    try:
        return json.loads((BANK / "_BANK.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Klang-Bank fehlt: {BANK}") from None


def klang_kennung(art: str, bank: dict | None = None) -> str:
    """Die Kennung, die wirklich erklingt: Zuordnung der Bank vor dem Standard."""
    bank = _bank() if bank is None else bank
    return (bank.get("_zuordnung") or {}).get(art) or KLANG[art]


def klang_datei(art: str) -> Path:
    bank = _bank()
    kennung = klang_kennung(art, bank)
    eintrag = bank.get(kennung)
    if not eintrag or not eintrag.get("da"):
        raise SystemExit(f"Klang {kennung} fehlt in der Bank")
    return BANK / eintrag["datei"]


def ereignisse(stationen_yaml: list[dict], plan: list[dict], ende_ms: int) -> list[tuple[str, int]]:
    """Wann welcher Klang: aus dem echten Zeitplan des Renderers (Flugbeginn, Ankunft)."""
    liste: list[tuple[str, int]] = [("auftakt", 0)]
    for i, (s, p) in enumerate(zip(stationen_yaml, plan, strict=True)):
        flug = p["ankunft"] - p["start"]
        if i > 0 and flug > 0:
            liste.append(("flug_lang" if flug >= 1100 else "flug_kurz", p["start"]))
        if s.get("beweis"):
            liste.append(("beweis", p["ankunft"] + 450))
        if s.get("einspieler") and p.get("einspieler"):
            liste.append(("einspieler", max(0, int(p["einspieler"]["t0"]) - 250)))
        einblendung = s.get("einblendung") or {}
        if einblendung.get("voll"):
            liste.append(("pointe", max(0, p["ankunft"] - 150)))
        elif einblendung.get("gross"):
            liste.append(("zahl", p["ankunft"] + 120))
    # Riser läuft auf die Pointe zu (die letzte Station).
    if plan:
        liste.append(("riser", max(0, plan[-1]["ankunft"] - 2400)))
    return sorted((e for e in liste if e[1] < ende_ms), key=lambda e: e[1])


def mischen(a: argparse.Namespace) -> None:
    video = Path(a.video)
    stimm_ordner = Path(a.stimme)
    aus = Path(a.aus)
    stems = aus.parent / f"{aus.stem}_stems"
    stems.mkdir(parents=True, exist_ok=True)
    stationen = yaml.safe_load(Path(a.video_yaml).read_text(encoding="utf-8"))["stationen"]
    auftrag = json.loads(Path(a.auftrag).read_text(encoding="utf-8"))
    # Der Plan des Formats, dessen Video gemischt wird (Schwenks können je Format anders sein).
    plan_format = (auftrag.get("plaene") or {}).get(a.format) or auftrag["plan"]
    plan = plan_format["stationen"]
    dauer_ms = int(plan_format["dauerMs"])
    if len(plan) != len(stationen):
        raise SystemExit(f"Plan hat {len(plan)} Stationen, die Video-Datei {len(stationen)}.")
    dauer = dauer_ms / 1000

    # 1. Stimme auf −16; O-Töne (Einspieler) ebenfalls auf −16 und an ihre Stelle, als eigene Spur.
    stimme = stems / "stimme.wav"
    auf_pegel(stimm_ordner / "stimme.wav", stimme, ZIEL_STIMME, f"apad=whole_dur={dauer}")
    o_toene = [(s["einspieler"], p["einspieler"]) for s, p in zip(stationen, plan, strict=True) if s.get("einspieler") and p.get("einspieler")]
    oton = stems / "o-ton.wav"
    if o_toene:
        teile_o, eingaben_o = [], []
        for n, (e, fenster) in enumerate(o_toene):
            roh = stems / f"_oton_{n}.wav"
            datei, ab, bis = pruefe_einspieler(e)
            # Nie länger als das Bild den Clip zeigt (Sicherung, falls der Plan kürzen musste).
            bis = min(bis, ab + (int(fenster["laufBis"]) - int(fenster["t0"])) / 1000)
            lauf(["ffmpeg", "-v", "error", "-y", "-ss", str(ab), "-to", str(bis), "-i", str(datei),
                  "-vn", "-ac", "2", "-ar", "48000", str(roh)])
            gepegelt = stems / f"_oton_{n}_pegel.wav"
            auf_pegel(roh, gepegelt, ZIEL_STIMME, "afade=t=in:d=0.04")
            roh.unlink()
            eingaben_o += ["-i", str(gepegelt)]
            t0 = int(fenster["t0"])
            teile_o.append(f"[{n}:a]adelay={t0}|{t0}[o{n}]")
        teile_o.append("".join(f"[o{n}]" for n in range(len(o_toene))) + f"amix=inputs={len(o_toene)}:normalize=0,apad=whole_dur={dauer},atrim=0:{dauer}[aus]")
        lauf(["ffmpeg", "-v", "error", "-y", *eingaben_o, "-filter_complex", ";".join(teile_o), "-map", "[aus]", "-ac", "2", "-ar", "48000", str(oton)])
        for n in range(len(o_toene)):
            (stems / f"_oton_{n}_pegel.wav").unlink()
    else:
        lauf(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{dauer}", str(oton)])

    # 2. Musik auf −30, auf Videolänge, weich rein und raus; vor der Pointe fast weg.
    zeiten = json.loads((stimm_ordner / "zeiten.json").read_text(encoding="utf-8"))
    pointe = zeiten["stationen"][-1] / 1000
    musik_roh = stems / "_musik_zugeschnitten.wav"
    lauf(["ffmpeg", "-v", "error", "-y", "-i", str(a.musik), "-t", f"{dauer}",
          "-af", f"afade=t=in:d=1.2,afade=t=out:st={dauer - 2.5}:d=2.5,"
                 f"volume='if(between(t,{pointe - 0.9},{pointe + 1.6}),0.25,1)':eval=frame",
          "-ac", "2", "-ar", "48000", str(musik_roh)])
    musik = stems / "musik.wav"
    auf_pegel(musik_roh, musik, ZIEL_MUSIK)
    musik_roh.unlink()

    # 3. Klänge: jedes Ereignis einzeln auf Pegel, dann an seine Stelle.
    liste = ereignisse(stationen, plan, dauer_ms) if BANK else []
    vorrat = stems / "_klaenge"
    vorrat.mkdir(exist_ok=True)
    eingaben, teile = [], []
    for n, (art, ms) in enumerate(liste):
        roh = vorrat / f"{art}.wav"
        if not roh.exists():
            auf_pegel(klang_datei(art), roh, ZIEL_KLANG + (3 if art == "pointe" else 0))
        eingaben += ["-i", str(roh)]
        teile.append(f"[{n}:a]adelay={ms}|{ms}[k{n}]")
    teile.append("".join(f"[k{n}]" for n in range(len(liste))) + f"amix=inputs={len(liste)}:normalize=0,apad=whole_dur={dauer},atrim=0:{dauer}[aus]")
    klaenge = stems / "klaenge.wav"
    if liste:
        lauf(["ffmpeg", "-v", "error", "-y", *eingaben, "-filter_complex", ";".join(teile), "-map", "[aus]", "-ac", "2", "-ar", "48000", str(klaenge)])
    else:
        lauf(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{dauer}", str(klaenge)])
    shutil.rmtree(vorrat)
    bank = _bank() if liste else {}
    (stems / "klangliste.json").write_text(json.dumps([{"klang": klang_kennung(k, bank), "art": k, "ms": ms}
                                                       for k, ms in liste], indent=1), encoding="utf-8")

    # 4. Summe: Musik duckt unter der Stimme (Sidechain), dann alles zusammen, auf −14 / TP −1,5.
    summe_roh = stems / "_summe.wav"
    lauf(["ffmpeg", "-v", "error", "-y", "-i", str(stimme), "-i", str(musik), "-i", str(klaenge), "-i", str(oton), "-filter_complex",
          # Steuerspur = Stimme + O-Ton: die Musik weicht beiden aus.
          "[0:a][3:a]amix=inputs=2:normalize=0,asplit=2[st][steuer];"
          "[1:a][steuer]sidechaincompress=threshold=0.03:ratio=5:attack=40:release=450:makeup=1[md];"
          "[st][md][2:a]amix=inputs=3:normalize=0[aus]",
          "-map", "[aus]", "-ac", "2", "-ar", "48000", "-t", f"{dauer}", str(summe_roh)])
    summe = stems / "summe.wav"
    gewinn = gewinn_fuer(ZIEL_SUMME, lautheit(summe_roh), "Die Summe")
    lauf(["ffmpeg", "-v", "error", "-y", "-i", str(summe_roh), "-af",
          # Limiter mit vierfacher Abtastung: sonst Überschwinger zwischen den Samples (True Peak 0 dB statt −1,5).
          f"volume={gewinn:.2f}dB,aresample=192000,alimiter=limit=0.8:level=false:attack=3:release=60,aresample=48000",
          "-ar", "48000", str(summe)])
    summe_roh.unlink()

    # 5. Ins Video (Bild wird kopiert, nicht neu kodiert).
    lauf(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(summe), "-map", "0:v", "-map", "1:a",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(aus)])
    print(f"✓ {aus}  (Summe {lautheit(summe):.1f} LUFS, {len(liste)} Klänge)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--stimme", required=True)
    ap.add_argument("--video-yaml", required=True)
    ap.add_argument("--auftrag", required=True)
    ap.add_argument("--musik", required=True)
    ap.add_argument("--aus", required=True)
    ap.add_argument("--format", default="16x9", choices=["16x9", "9x16", "1x1", "oben"])
    ap.add_argument("--klaenge", help="Ordner der Klangbank mit _BANK.json (Standard: AKTE_KLANGBANK)")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    a = ap.parse_args(argv)
    if a.klaenge:
        global BANK
        BANK = Path(a.klaenge)
    mischen(a)


if __name__ == "__main__":
    main()
