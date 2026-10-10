#!/usr/bin/env python3
"""Stimme und Musik für ein gesichtsloses Akte-Video (ElevenLabs).

Je Station ein Sprechstück über ``text-to-speech/<stimme>/with-timestamps`` (mit ``previous_text`` und
``next_text``, damit die Sätze ineinander fließen). Die Zeichen-Zeiten ergeben die Satzanfänge; daraus
wird ``zeiten.json`` für den Renderer (die Kamera kommt beim ersten Wort an), ``woerter.json`` für die
Klänge und ``untertitel.srt`` für CapCut.

    python render/vertonen.py stimme video.yaml --stimme erzaehler --ziel <ordner> [--ton ton.yaml]
    python render/vertonen.py musik --laenge-ms 90000 --ziel <ordner> [--varianten 2]
    python render/vertonen.py gegenprobe <ordner>          (Whisper small, Zahlen und Namen prüfen)

Stimmen stehen in ``ton.yaml`` (Vorlage: ``ton.beispiel.yaml``): Name → ElevenLabs-Stimm-ID und Einstellungen.
Schlüssel: ``ELEVENLABS_API_KEY`` nur aus der Umgebung — wird nie ausgegeben.
Jede Antwort wird zwischengespeichert (``_cache/``): derselbe Text mit derselben Stimme kostet nur einmal.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib import error, request

import yaml

API = "https://api.elevenlabs.io/v1"
MODELL = "eleven_multilingual_v2"
TON_DATEI = Path(os.environ.get("AKTE_TON", "ton.yaml"))


#: Grenzen der Musik-Schnittstelle (10 s bis 5 min) und der Varianten je Lauf (jede kostet Guthaben).
MUSIK_MIN_MS, MUSIK_MAX_MS, MUSIK_MAX_VARIANTEN = 10_000, 300_000, 4


def stimmen(datei: Path | None = None) -> dict[str, tuple[str, dict]]:
    """Stimmen aus ton.yaml: {stimmen: {name: {voice_id: …, einstellungen: {stability: …, …}}}}."""
    datei = datei or TON_DATEI
    if not datei.exists():
        raise SystemExit(f"{datei} fehlt. Vorlage: render/ton.beispiel.yaml kopieren und Stimm-IDs eintragen.")
    daten = yaml.safe_load(datei.read_text(encoding="utf-8")) or {}
    return {name: (str(w["voice_id"]), dict(w.get("einstellungen") or {}))
            for name, w in (daten.get("stimmen") or {}).items()}
#: Die erste Station (meist die ganze Wand) steht kurz still, bevor die Stimme einsetzt.
VORLAUF_MS = 900
#: Atempause nach jeder Station, wenn die Station keine eigene ``pause_ms`` nennt.
PAUSE_MS = 420
#: Rahmen um einen Einspieler (wie ``einspielerStationMs`` in apps/web/src/lib/akte/aufnahme.ts):
#: 300 ms Vorlauf, Clip, Standbild, 350 ms Ausblenden, 150 ms Luft.
EINSPIELER_RAHMEN_MS = 300 + 350 + 150
#: Die Quelle eines O-Tons steht mindestens 5 s (``QUELLE_MIN_MS``); danach Platz für den Flug zur nächsten Station.
QUELLE_MIN_MS = 5000
FLUG_NACH_OTON_MS = 900


def einspieler_ms(station: dict, quelle_gezeigt: bool = False) -> int | None:
    """Länge einer Einspieler-Station in ms, oder None, wenn die Station spricht.

    Die Quelle steht beim ersten Auftritt eines Werks mindestens 5 s; läuft dasselbe Werk noch einmal
    (``quelle_gezeigt``), bleibt das Standbild so kurz wie angegeben (wie ``einspielerFreeze`` in aufnahme.ts).
    """
    e = station.get("einspieler") or {}
    if not e:
        return None
    dauer = round((float(e["bis"]) - float(e.get("ab", 0))) * 1000)
    freeze = int(e.get("freeze_ms", 700))
    if not quelle_gezeigt:
        freeze = max(freeze, QUELLE_MIN_MS - dauer)
    return dauer + freeze + EINSPIELER_RAHMEN_MS
def schluessel() -> str:
    wert = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not wert:
        raise SystemExit("ELEVENLABS_API_KEY fehlt (Umgebungsvariable). Ohne Stimme: Fahrt ohne Ton rendern.")
    return wert


def post(pfad: str, daten: dict, antwort_json: bool = True, zeit: int = 300):
    req = request.Request(
        f"{API}{pfad}", data=json.dumps(daten).encode(),
        headers={"xi-api-key": schluessel(), "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=zeit) as r:
            roh = r.read()
    except error.HTTPError as e:
        # Fehlertext der API zeigen (nie den Schlüssel).
        raise SystemExit(f"ElevenLabs {e.code} bei {pfad}: {e.read()[:400].decode(errors='replace')}") from None
    except (error.URLError, TimeoutError, OSError) as e:
        raise SystemExit(f"ElevenLabs nicht erreichbar bei {pfad}: {e}") from None
    return json.loads(roh) if antwort_json else roh


def ffprobe_dauer(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


# ─── Stimme ────────────────────────────────────────────────────────────────


def sprich(text: str, stimme: str, vorher: str, nachher: str, cache: Path) -> dict:
    """Ein Sprechstück samt Zeichen-Zeiten; aus dem Zwischenspeicher, wenn schon einmal bezahlt."""
    alle = stimmen()
    if stimme not in alle:
        raise SystemExit(f"Stimme {stimme!r} fehlt in {TON_DATEI} (vorhanden: {', '.join(sorted(alle)) or 'keine'}).")
    stimm_id, einstellung = alle[stimme]
    auftrag = {"text": text, "model_id": MODELL, "voice_settings": {**einstellung, "use_speaker_boost": True},
               "previous_text": vorher[-400:], "next_text": nachher[:400]}
    kennung = hashlib.sha256(json.dumps([stimm_id, auftrag], sort_keys=True).encode()).hexdigest()[:20]
    datei = cache / f"{stimme}_{kennung}.json"
    if datei.exists():
        return json.loads(datei.read_text(encoding="utf-8"))
    antwort = post(f"/text-to-speech/{stimm_id}/with-timestamps?output_format=mp3_44100_128", auftrag)
    cache.mkdir(parents=True, exist_ok=True)
    datei.write_text(json.dumps(antwort), encoding="utf-8")
    return antwort


def woerter_aus(ausrichtung: dict, versatz_ms: int, station: int) -> list[dict]:
    """Zeichen-Zeiten → Wörter mit Start und Ende (ms, auf der Gesamtzeitachse)."""
    zeichen = ausrichtung["characters"]
    starts = ausrichtung["character_start_times_seconds"]
    enden = ausrichtung["character_end_times_seconds"]
    woerter, aktuell, beginn, letzte_ende = [], "", None, 0
    for z, s, e in zip(zeichen, starts, enden, strict=True):
        if z.isspace():
            if aktuell:
                woerter.append({"wort": aktuell, "start_ms": beginn, "ende_ms": letzte_ende, "station": station})
            aktuell, beginn = "", None
            continue
        if beginn is None:
            beginn = versatz_ms + round(s * 1000)
        aktuell += z
        letzte_ende = versatz_ms + round(e * 1000)
    if aktuell:
        woerter.append({"wort": aktuell, "start_ms": beginn, "ende_ms": letzte_ende, "station": station})
    return woerter


def srt_zeit(ms: int) -> str:
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def untertitel(woerter: list[dict], max_zeichen: int = 42) -> str:
    """Zeilen an Satzzeichen und nach Länge umbrechen (SRT für den Schnitt)."""
    bloecke, aktuell = [], []
    for w in woerter:
        aktuell.append(w)
        text = " ".join(x["wort"] for x in aktuell)
        if re.search(r"[.!?:]$", w["wort"]) or len(text) >= max_zeichen or (w["wort"].endswith(",") and len(text) > 24):
            bloecke.append(aktuell)
            aktuell = []
    if aktuell:
        bloecke.append(aktuell)
    zeilen = []
    for i, b in enumerate(bloecke, 1):
        zeilen += [str(i), f"{srt_zeit(b[0]['start_ms'])} --> {srt_zeit(b[-1]['ende_ms'])}", " ".join(x["wort"] for x in b), ""]
    return "\n".join(zeilen)


def stimme(a: argparse.Namespace) -> None:
    video = yaml.safe_load(Path(a.video).read_text(encoding="utf-8"))
    stationen = video.get("stationen") or []
    if not stationen:
        raise SystemExit("Die Video-Datei hat keine Stationen.")
    texte = [str(s.get("text", "")).strip() for s in stationen]
    beides = [i + 1 for i, (s, t) in enumerate(zip(stationen, texte, strict=True)) if t and einspieler_ms(s)]
    if beides:
        raise SystemExit(f"Station(en) mit Einspieler UND text: {beides} — während des O-Tons schweigt die Stimme.")
    leer = [i + 1 for i, (s, t) in enumerate(zip(stationen, texte, strict=True)) if not t and not einspieler_ms(s)]
    if leer:
        raise SystemExit(f"Station(en) ohne text und ohne Einspieler: {leer}")
    # Fluss für die Stimme: nur die gesprochenen Texte zählen als Nachbarn.
    gesprochen = [t for t in texte if t]
    ziel = Path(a.ziel) / a.stimme
    ziel.mkdir(parents=True, exist_ok=True)
    cache = Path(a.ziel) / "_cache"
    t = VORLAUF_MS
    ankunft, alle_woerter, stuecke = [], [], []
    letzter_oton = 0
    gezeigt: set[str] = set()
    for i, text in enumerate(texte):
        quelle = str((stationen[i].get("einspieler") or {}).get("quelle", ""))
        o_ton = einspieler_ms(stationen[i], quelle in gezeigt)
        if o_ton:
            gezeigt.add(quelle)
        if o_ton:
            # O-Ton-Station: die Kamera steht, der Clip läuft, die Stimme schweigt.
            ankunft.append(t)
            letzter_oton = t + o_ton
            t += o_ton + max(int(stationen[i].get("pause_ms", 0)), FLUG_NACH_OTON_MS)
            print(f"  {i + 1:>2}. {o_ton / 1000:5.2f} s  [O-Ton] {stationen[i]['einspieler'].get('quelle', '')[:60]}", flush=True)
            continue
        k = gesprochen.index(text)
        antwort = sprich(text, a.stimme, " ".join(gesprochen[:k]), " ".join(gesprochen[k + 1:]), cache)
        mp3 = ziel / f"station_{i + 1:02}.mp3"
        mp3.write_bytes(base64.b64decode(antwort["audio_base64"]))
        ausrichtung = antwort.get("alignment") or antwort["normalized_alignment"]
        erster = next((s for z, s in zip(ausrichtung["characters"], ausrichtung["character_start_times_seconds"], strict=True) if not z.isspace()), 0)
        ankunft.append(t + round(erster * 1000))
        alle_woerter += woerter_aus(ausrichtung, t, i)
        stuecke.append((mp3, t))
        dauer = round(ffprobe_dauer(mp3) * 1000)
        t += dauer + int(stationen[i].get("pause_ms", PAUSE_MS))
        print(f"  {i + 1:>2}. {dauer / 1000:5.2f} s  {text[:70]}", flush=True)
    # Endet die Folge mit einem O-Ton, zählt dessen Ende; sonst das letzte Wort.
    ende = max(alle_woerter[-1]["ende_ms"] if alle_woerter else 0, letzter_oton)
    # Alle Stücke auf ihre Stelle legen; Länge = letztes Wort + 1,5 s Ausklang.
    if not stuecke:
        # Folge nur aus O-Tönen: Stimme ist Stille in voller Länge.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                        "-t", f"{(ende + 1500) / 1000}", str(ziel / "stimme.wav")], check=True)
    eingaben, filter_teile = [], []
    for n, (mp3, start) in enumerate(stuecke):
        eingaben += ["-i", str(mp3)]
        filter_teile.append(f"[{n}:a]aresample=48000,adelay={start}|{start}[s{n}]")
    filter_teile.append("".join(f"[s{n}]" for n in range(len(stuecke))) + f"amix=inputs={len(stuecke)}:normalize=0,apad=whole_dur={(ende + 1500) / 1000}[aus]")
    if stuecke:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *eingaben, "-filter_complex", ";".join(filter_teile), "-map", "[aus]",
                        "-ac", "2", "-ar", "48000", str(ziel / "stimme.wav")], check=True)
    # Die Kamera hält bis 0,9 s nach dem letzten Wort; mit dem Ausklang des Plans (0,6 s) sind Bild und Ton gleich lang.
    # Satzanfänge reisen mit: der Renderer prüft damit, dass die Fahrt noch zu dieser Stimme passt.
    zeiten = {"stationen": ankunft, "ende_ms": ende + 900, "letztes_wort_ms": ende, "anfaenge": [x[:40] for x in texte]}
    (ziel / "zeiten.json").write_text(json.dumps(zeiten, indent=1), encoding="utf-8")
    (ziel / "woerter.json").write_text(json.dumps(alle_woerter, ensure_ascii=False, indent=1), encoding="utf-8")
    (ziel / "untertitel.srt").write_text(untertitel(alle_woerter), encoding="utf-8")
    print(f"✓ {a.stimme}: {len(texte)} Stationen, Stimme endet bei {ende / 1000:.1f} s → {ziel}")


# ─── Musik ─────────────────────────────────────────────────────────────────

MUSIK_PROMPT = (
    "Dark investigative documentary score, instrumental only, no vocals. Slow pulsing analog synth bass around "
    "80 BPM, ticking hi-hat like a clock, cold digital textures, sparse low piano notes, a sense of being watched. "
    "Tension builds gradually and steadily; subtle lift two thirds in; stays understated and never loud, "
    "leaves the midrange free for a narrator. Ends on a held dark chord."
)


def musik(a: argparse.Namespace) -> None:
    if not MUSIK_MIN_MS <= a.laenge_ms <= MUSIK_MAX_MS:
        raise SystemExit(f"--laenge-ms zwischen {MUSIK_MIN_MS} und {MUSIK_MAX_MS} (die Schnittstelle kann nicht mehr).")
    if not 1 <= a.varianten <= MUSIK_MAX_VARIANTEN:
        raise SystemExit(f"--varianten zwischen 1 und {MUSIK_MAX_VARIANTEN} (jede Variante kostet Guthaben).")
    ziel = Path(a.ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    for v in range(1, a.varianten + 1):
        datei = ziel / f"musik_{v}.mp3"
        if datei.exists():
            print(f"  vorhanden: {datei.name}")
            continue
        audio = post("/music?output_format=mp3_44100_128",
                     {"prompt": a.prompt or MUSIK_PROMPT, "music_length_ms": a.laenge_ms, "model_id": "music_v1"},
                     antwort_json=False, zeit=600)
        datei.write_bytes(audio)
        print(f"✓ {datei.name}: {ffprobe_dauer(datei):.1f} s", flush=True)


# ─── Gegenprobe ────────────────────────────────────────────────────────────


def gegenprobe(a: argparse.Namespace) -> None:
    """Whisper hört die Stimme ab; Zahlen und Namen stehen daneben zum Vergleich."""
    ordner = Path(a.ordner)
    soll = " ".join(w["wort"] for w in json.loads((ordner / "woerter.json").read_text(encoding="utf-8")))
    aus = ordner / "_gegenprobe"
    r = subprocess.run([sys.executable, "-m", "whisper", str(ordner / "stimme.wav"), "--model", "small", "--language", "de",
                        "--output_format", "txt", "--output_dir", str(aus)], capture_output=True, text=True, errors="replace")
    if r.returncode:
        raise SystemExit(f"Whisper scheiterte: {r.stderr[-800:]}")
    ist = (aus / "stimme.txt").read_text(encoding="utf-8")
    print("SOLL:", soll, "\n\nIST: ", " ".join(ist.split()))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="befehl", required=True)
    p = sub.add_parser("stimme")
    p.add_argument("video")
    p.add_argument("--stimme", required=True, help="Name der Stimme aus ton.yaml")
    p.add_argument("--ziel", required=True)
    p.add_argument("--ton", help="Pfad zur ton.yaml (Standard: AKTE_TON, sonst ./ton.yaml)")
    p = sub.add_parser("musik")
    p.add_argument("--laenge-ms", type=int, required=True)
    p.add_argument("--ziel", required=True)
    p.add_argument("--varianten", type=int, default=2)
    p.add_argument("--prompt", default="")
    p = sub.add_parser("gegenprobe")
    p.add_argument("ordner")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    a = ap.parse_args(argv)
    if getattr(a, "ton", None):
        global TON_DATEI
        TON_DATEI = Path(a.ton)
    {"stimme": stimme, "musik": musik, "gegenprobe": gegenprobe}[a.befehl](a)


if __name__ == "__main__":
    main()
