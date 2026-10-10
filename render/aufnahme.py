#!/usr/bin/env python3
"""Fahrten der Akte als Video: nur Bild (``rendern``) oder die ganze Kette mit Stimme und Musik (``video``).

    AKTE_BASIS=http://127.0.0.1:8080  AKTE_TOKEN=…            (Werkzeug-Token, nie ins Repo)
    AKTE_WEB_LOGIN=…  AKTE_WEB_PASSWORT=…                     (Konto, mit dem der Browser die Wand öffnet)

    python render/aufnahme.py rendern <board> "<Fahrt-Titel oder ID>" --format 16x9,9x16 [--4k] [--unschaerfe]
    python render/aufnahme.py video <board> kapitel.yaml --stimme erzaehler --ziel ausgabe/kapitel-1 [--musik m.mp3]

``video``: Fahrt aus der YAML anlegen (Stationen mit ``fokus`` und ``text``) → Stimme (render/vertonen.py) →
Musik (falls keine angegeben) → Bild im Takt der Stimme (render_fahrt.cjs) → Mischung (render/mischen.py).
Jeder Schritt ist wiederholbar; Stimme und Musik kommen beim zweiten Mal aus dem Zwischenspeicher.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
try:
    from akte_client import Akte, AkteFehler
except ImportError:  # ohne installiertes Paket: direkt aus dem Repo
    sys.path.insert(0, str(HIER.parent / "mcp" / "src"))
    from akte_client import Akte, AkteFehler

FORMATE = ("16x9", "9x16", "1x1", "oben")


def slug_datei(text: str) -> str:
    """Wie slug() in render_fahrt.cjs: klein, Umlaute ausgeschrieben, nur a–z, 0–9, Bindestrich."""
    t = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60]
    return t or "fahrt"


def formate_lesen(text: str) -> list[str]:
    formate = [f.strip() for f in text.split(",") if f.strip()]
    falsch = [f for f in formate if f not in FORMATE]
    if not formate or falsch:
        raise SystemExit(f"Unbekanntes Format {', '.join(falsch) or '(leer)'}; erlaubt: {', '.join(FORMATE)}")
    return formate


def lade_yaml(pfad: str) -> dict:
    import yaml

    return yaml.safe_load(Path(pfad).read_text(encoding="utf-8"))


def rendern(akte: Akte, a: argparse.Namespace) -> None:
    """Sucht die Fahrt und startet den Renderer; Fortschritt kommt als JSON-Zeilen zurück."""
    formate = formate_lesen(a.format)
    fahrten = akte.wand(a.board)["fahrten"]
    wahl = [f for f in fahrten if str(f["id"]) == a.fahrt or f["titel"].lower() == a.fahrt.lower()]
    if len(wahl) != 1:
        namen = ", ".join(f"„{f['titel']}“ ({f['id']})" for f in fahrten) or "keine"
        raise SystemExit(f"Fahrt „{a.fahrt}“ nicht eindeutig. Auf {a.board}: {namen}")
    f = wahl[0]
    befehl = ["node", str(HIER / "render_fahrt.cjs"), "--board", a.board, "--fahrt", str(f["id"]), "--titel", f["titel"],
              "--formate", ",".join(formate), "--halte", str(a.halte), "--basis", a.web.rstrip("/")]
    if a.look:
        befehl += ["--look", a.look]
    if a.ziel:
        befehl += ["--ziel", a.ziel]
    for schalter, an in (("--stichworte", a.stichworte), ("--legende", a.legende), ("--4k", a.vierk),
                         ("--unschaerfe", a.unschaerfe)):
        if an:
            befehl.append(schalter)
    prozess = subprocess.Popen(befehl, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        for zeile in prozess.stdout:
            try:
                m = json.loads(zeile)
            except ValueError:
                print(zeile, end="")
                continue
            if m["art"] == "bild" and (m["bild"] - 1) % 250 and m["bild"] != m["von"]:
                continue
            if m["art"] == "format":
                print(f"{m['format']}: {m['bilder']} Bilder, {m['dauerMs'] / 1000:.1f} s, {m['stationen']} Stationen", flush=True)
            elif m["art"] == "bild":
                print(f"  {m['format']}: Bild {m['bild']}/{m['von']} ({m['sekunden']} s)", flush=True)
            elif m["art"] == "fertig":
                print(f"✓ {m['datei']}", flush=True)
            elif m["art"] == "ende":
                print(f"→ Ordner: {m['ziel']}", flush=True)
            elif m["art"] in ("fehler", "warnung"):
                print(f"{'✗' if m['art'] == 'fehler' else '!'} {m.get('format', '')} {m['text']}", file=sys.stderr)
            else:
                print(zeile, end="")
        prozess.wait()
    finally:
        # Abbruch (Strg+C) nimmt den Renderer samt Browser mit, statt ihn verwaist laufen zu lassen.
        if prozess.poll() is None:
            prozess.terminate()
            try:
                prozess.wait(timeout=10)
            except subprocess.TimeoutExpired:
                prozess.kill()
    if prozess.returncode:
        raise SystemExit(prozess.returncode)


def video(akte: Akte, a: argparse.Namespace) -> None:
    """Die ganze Kette für eine Folge."""
    formate = formate_lesen(a.format)
    ziel = Path(a.ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    beschreibung = lade_yaml(a.datei)
    name = slug_datei(beschreibung["titel"])

    def schritt(titel: str, befehl: list[str]) -> None:
        print(f"── {titel}", flush=True)
        if subprocess.run(befehl).returncode:
            raise SystemExit(f"Abbruch bei: {titel}")

    fahrt = akte.post(f"/boards/{a.board}/fahrten/aus-beschreibung/", beschreibung)
    print(f"── Fahrt „{fahrt['titel']}“: {len(fahrt['stationen'])} Stationen (ID {fahrt['id']})", flush=True)
    py = sys.executable
    schritt("Stimme", [py, str(HIER / "vertonen.py"), "stimme", a.datei, "--stimme", a.stimme, "--ziel", str(ziel)])
    stimm_ordner = ziel / a.stimme
    zeiten = json.loads((stimm_ordner / "zeiten.json").read_text(encoding="utf-8"))
    musik = Path(a.musik) if a.musik else ziel / "musik" / "musik_1.mp3"
    if not a.musik:
        schritt("Musik", [py, str(HIER / "vertonen.py"), "musik", "--laenge-ms", str(zeiten["ende_ms"] + 3500),
                          "--ziel", str(ziel / "musik"), "--varianten", "1"])
    schritt("Bild", ["node", str(HIER / "render_fahrt.cjs"), "--board", a.board, "--fahrt", str(fahrt["id"]),
                     "--name", name, "--formate", ",".join(formate), "--basis", a.web.rstrip("/"),
                     "--zeiten", str(stimm_ordner / "zeiten.json"), "--ziel", str(ziel)])
    auftrag = ziel / f"auftrag_{name}.json"
    for f in formate:
        befehl = [py, str(HIER / "mischen.py"), str(ziel / f"{a.board}_{name}_{f}.mp4"), "--stimme", str(stimm_ordner),
                  "--video-yaml", a.datei, "--auftrag", str(auftrag), "--musik", str(musik),
                  "--format", f, "--aus", str(ziel / f"{name}_{f}.mp4")]
        if a.klaenge:
            befehl += ["--klaenge", a.klaenge]
        schritt(f"Ton {f}", befehl)
    print(f"✓ fertig: {ziel}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--basis", default=os.environ.get("AKTE_BASIS", "http://127.0.0.1:8080"))
    ap.add_argument("--web", default=os.environ.get("AKTE_WEB", "http://127.0.0.1:8080"),
                    help="Adresse der laufenden Oberfläche (nur lokal)")
    sub = ap.add_subparsers(dest="befehl", required=True)
    p = sub.add_parser("rendern", help="Fahrt als Video rendern (16x9, 9x16, 1x1, oben)")
    p.add_argument("board"); p.add_argument("fahrt", help="Titel oder ID der Fahrt")
    p.add_argument("--format", default="16x9"); p.add_argument("--halte", type=int, default=3000)
    p.add_argument("--look", choices=["dunkel", "papier"]); p.add_argument("--stichworte", action="store_true")
    p.add_argument("--legende", action="store_true"); p.add_argument("--4k", dest="vierk", action="store_true")
    p.add_argument("--unschaerfe", action="store_true", help="Bewegungsunschärfe (4 Unterbilder, ~4x Zeit)")
    p.add_argument("--ziel")
    p = sub.add_parser("video", help="Gesichtsloses Video: Fahrt, Stimme, Musik, Bild, Mischung")
    p.add_argument("board"); p.add_argument("datei", help="YAML mit titel und stationen (fokus, text, …)")
    p.add_argument("--stimme", required=True, help="Name aus ton.yaml")
    p.add_argument("--format", default="9x16,16x9"); p.add_argument("--musik")
    p.add_argument("--klaenge", help="Ordner der Klangbank (optional)")
    p.add_argument("--ziel", required=True)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    akte = Akte(a.basis, os.environ.get("AKTE_TOKEN"))
    try:
        (rendern if a.befehl == "rendern" else video)(akte, a)
    except AkteFehler as fehler:
        print(fehler, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
