# SPDX-License-Identifier: MIT
"""akte — an der Ermittler-Wand arbeiten, ohne zu klicken.

Zugang (nie ins Repo):

    AKTE_BASIS=http://localhost:8080        Adresse deiner Akte
    AKTE_TOKEN=…                            python manage.py akte_token <konto>  (ohne Token: nur lesen)

Beispiele:

    akte boards
    akte suche Mustermann
    akte karte "Erika Mustermann" --typ person --kurz "Senatorin" --board musterhafen --oeffentlich
    akte quelle --titel "Drucksache 9/1234" --url https://… --herausgeber Bürgerschaft --guete primaer --abgerufen 2026-10-01
    akte faden "Senat Musterhafen" "Nordlicht Analytik GmbH" --typ auftrag --text "beauftragt" \\
        --start 2024-01-01 --aktuell --quelle 12 --zitat "Der Senat beauftragt …" --fundstelle "S. 3"
    akte gruppen musterhafen gruppen.yaml           ({Titel: [Namen]} oder {Titel: {farbe: "#C8102E", karten: […]}})
    akte fahrt musterhafen fahrt.yaml
    akte pruefung musterhafen
    akte import paket.json                           (Probelauf; mit --echt wird geschrieben)
    akte export-oeffentlich ./datensatz              (nur, was Besucher ohne Konto sehen)

Freigeben kann die CLI nicht: Das tut ein Mensch in der Oberfläche.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import aktionen
from .client import Akte, AkteFehler


def lade_datei(pfad: str):
    text = Path(pfad).read_text(encoding="utf-8")
    if pfad.endswith((".yaml", ".yml")):
        import yaml

        return yaml.safe_load(text)
    return json.loads(text)


def zeige(daten) -> None:
    print(json.dumps(daten, ensure_ascii=False, indent=2))


def boards_baum(boards: list) -> list[str]:
    """Boards als Baum: Wurzeln zuerst, Mappen eingerückt darunter."""
    je_slug = {b["slug"]: b for b in boards}
    kinder: dict[str, list[str]] = {}
    for b in boards:
        for e in b.get("eltern", []):
            kinder.setdefault(e, []).append(b["slug"])
    zeilen: list[str] = []
    gedruckt: set[str] = set()

    def zeile(slug, tiefe, weg):
        gedruckt.add(slug)
        zeilen.append(f"{'  ' * tiefe}{'└ ' if tiefe else ''}{slug:{max(30 - 2 * tiefe, 10)}} {je_slug[slug]['titel']}")
        for k in sorted(kinder.get(slug, [])):
            if k not in weg:
                zeile(k, tiefe + 1, weg | {k})

    for slug in sorted(b["slug"] for b in boards if not (set(b.get("eltern", [])) & set(je_slug))):
        zeile(slug, 0, {slug})
    rest = sorted(set(je_slug) - gedruckt)
    if rest:
        zeilen.append("ohne Wurzel (Kreis oder Eltern nicht sichtbar): " + ", ".join(rest))
    return zeilen


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="akte", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--basis", default=os.environ.get("AKTE_BASIS", ""), help="Adresse der Akte (AKTE_BASIS)")
    sub = ap.add_subparsers(dest="befehl", required=True)

    sub.add_parser("boards")
    p = sub.add_parser("board-neu"); p.add_argument("titel"); p.add_argument("--beschreibung", default="")
    p.add_argument("--slug", default=""); p.add_argument("--in", dest="eltern", help="gleich als Mappe auf dieses Board")
    p = sub.add_parser("mappe", help="Ein Board als Aktenmappe auf ein anderes legen")
    p.add_argument("eltern"); p.add_argument("ziel"); p.add_argument("--x", type=float); p.add_argument("--y", type=float)
    p.add_argument("--farbe", default="")
    p = sub.add_parser("mappe-weg", help="Mappe von einer Wand nehmen (das Board selbst bleibt)")
    p.add_argument("eltern"); p.add_argument("ziel")
    p = sub.add_parser("gelenke", help="Karten, die in mehreren Mappen dieser Wand stecken")
    p.add_argument("board"); p.add_argument("--legen", action="store_true")
    p = sub.add_parser("zettel", help="Zettel aus einer Liste [{board, art, text}] anlegen")
    p.add_argument("datei"); p.add_argument("--board")
    p = sub.add_parser("wand"); p.add_argument("board")
    p = sub.add_parser("suche"); p.add_argument("q")
    p = sub.add_parser("karte")
    p.add_argument("name"); p.add_argument("--typ"); p.add_argument("--kurz", default="")
    p.add_argument("--notiz", default=""); p.add_argument("--oeffentlich", action="store_true")
    p.add_argument("--board"); p.add_argument("--x", type=float); p.add_argument("--y", type=float)
    p = sub.add_parser("quelle")
    p.add_argument("--titel", required=True); p.add_argument("--url", default="")
    p.add_argument("--herausgeber", default=""); p.add_argument("--guete", choices=["primaer", "sekundaer"], default="sekundaer")
    p.add_argument("--abgerufen"); p.add_argument("--veroeffentlicht")
    p = sub.add_parser("faden")
    p.add_argument("von"); p.add_argument("nach"); p.add_argument("--typ", default="sonstiges")
    p.add_argument("--text", default=""); p.add_argument("--start"); p.add_argument("--ende")
    p.add_argument("--aktuell", action="store_true")
    p.add_argument("--art", choices=["belegt", "verdacht", "meinung"], default="belegt")
    p.add_argument("--quelle", type=int, action="append", default=[])
    p.add_argument("--zitat", action="append", default=[]); p.add_argument("--fundstelle", action="append", default=[])
    p = sub.add_parser("beleg", help="Weiteren Beleg an einen Faden hängen")
    p.add_argument("faden", type=int); p.add_argument("--quelle", type=int, required=True)
    p.add_argument("--zitat", default=""); p.add_argument("--fundstelle", default="")
    p = sub.add_parser("gruppen", help="Karten in Themen-Rahmen sortieren und aufräumen")
    p.add_argument("board"); p.add_argument("datei")
    p = sub.add_parser("aufraeumen"); p.add_argument("board")
    p = sub.add_parser("pruefung"); p.add_argument("board")
    p = sub.add_parser("fahrt"); p.add_argument("board"); p.add_argument("datei")
    p = sub.add_parser("weg"); p.add_argument("von"); p.add_argument("nach"); p.add_argument("--nur-belegt", action="store_true")
    p = sub.add_parser("sichern", help="Quelle(n) sichern: Original, Archivkopie, Fundstellen")
    p.add_argument("quelle", nargs="?", type=int); p.add_argument("--alle", action="store_true")
    p = sub.add_parser("zitat-pruefen", help="Steht das Zitat eines Belegs wörtlich an der Quelle?")
    p.add_argument("beleg", type=int); p.add_argument("--quelle", type=int, required=True)
    p.add_argument("--warten", type=int, default=60)
    p = sub.add_parser("anhang", help="Datei an eine Quelle hängen oder als neue Quelle anlegen")
    p.add_argument("datei"); p.add_argument("--quelle", type=int); p.add_argument("--titel", default="")
    p.add_argument("--board"); p.add_argument("--herausgeber", default="")
    p = sub.add_parser("beweis", help="Quelle als Beweisstück-Karte auf ein Board legen")
    p.add_argument("board"); p.add_argument("quelle", type=int)
    p = sub.add_parser("import", help="Paket importieren (Standard: Probelauf)")
    p.add_argument("datei"); p.add_argument("--echt", action="store_true", help="wirklich schreiben")
    p = sub.add_parser("fotos", help="Fotoliste auf Karten ohne Foto legen"); p.add_argument("datei")
    p = sub.add_parser("export", help="Obsidian-Vault als ZIP"); p.add_argument("ziel")
    p = sub.add_parser("export-oeffentlich", help="Öffentliche Boards als Datensatz (JSON, CSV, Prüfsummen)")
    p.add_argument("ziel"); p.add_argument("--boards", help="nur diese Slugs, kommagetrennt")
    p.add_argument("--stand", default=""); p.add_argument("--lizenz", default="CC-BY-SA-4.0")
    p.add_argument("--herausgeber", default="")
    p.add_argument("--privatnamen", help="Datei mit vollen Namen von Privatpersonen, eine je Zeile (wird nur gelesen)")
    return ap


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not a.basis:
        print("AKTE_BASIS fehlt (z. B. http://localhost:8080).", file=sys.stderr)
        return 2
    try:
        return _ausfuehren(a)
    except (AkteFehler, ValueError) as fehler:
        print(fehler, file=sys.stderr)
        return 1


def _ausfuehren(a: argparse.Namespace) -> int:
    if a.befehl == "export-oeffentlich":
        namen = Path(a.privatnamen).read_text(encoding="utf-8").splitlines() if a.privatnamen else []
        boards = [s.strip() for s in a.boards.split(",")] if a.boards else None
        zeige(aktionen.export_oeffentlich(a.basis, Path(a.ziel), boards=boards, stand=a.stand, lizenz=a.lizenz,
                                          herausgeber=a.herausgeber, privatnamen=namen))
        return 0

    akte = Akte(a.basis, os.environ.get("AKTE_TOKEN"))
    if a.befehl == "boards":
        print("\n".join(boards_baum(akte.boards())))
    elif a.befehl == "board-neu":
        b = akte.post("/boards/", {"titel": a.titel, "beschreibung": a.beschreibung, "slug": a.slug})
        zeige(b)
        if a.eltern:
            akte.mappe_legen(a.eltern, b["slug"])
            print(f"Liegt als Mappe auf {a.eltern}.")
    elif a.befehl == "mappe":
        m, neu = akte.mappe_legen(a.eltern, a.ziel, a.x, a.y, a.farbe)
        print(("Neu: " if neu else "Liegt schon: ") + f"Mappe {m['ziel']} auf {a.eltern}.")
    elif a.befehl == "mappe-weg":
        m = next((m for m in akte.wand(a.eltern).get("mappen", []) if m["ziel"] == a.ziel), None)
        if not m:
            raise ValueError(f"Keine Mappe {a.ziel} auf {a.eltern}.")
        akte.delete(f"/boards/{a.eltern}/mappen/{m['id']}/")
        print(f"Mappe {a.ziel} von {a.eltern} genommen.")
    elif a.befehl == "gelenke":
        zeige(aktionen.gelenke(akte, a.board, a.legen))
    elif a.befehl == "zettel":
        zeige(aktionen.zettel_anlegen(akte, lade_datei(a.datei), a.board))
    elif a.befehl == "wand":
        w = akte.wand(a.board)
        print(f"{w['board']['titel']}: {len(w['karten'])} Karten, {len(w['faeden'])} Fäden, "
              f"{len(w.get('fahrten', []))} Fahrten, {sum(1 for f in w['faeden'] if f.get('befunde'))} Fäden mit Befunden")
        for k in sorted(w["karten"], key=lambda k: (k["y"], k["x"])):
            e = k["entitaet_detail"]
            print(f"  [{e['id']:>4}] {e['name']:40} {e['typ']:12} ({k['x']:.0f}, {k['y']:.0f})")
    elif a.befehl == "suche":
        for e in akte.entitaeten(q=a.q):
            print(f"[{e['id']:>4}] {e['name']:40} {e['typ']:12} {e['status']}")
    elif a.befehl == "karte":
        e, neu = akte.entitaet(a.name, a.typ, a.kurz, a.oeffentlich, a.notiz)
        print(("Neu (Entwurf): " if neu else "Vorhanden: ") + f"[{e['id']}] {e['name']}")
        if a.board:
            akte.auf_board(a.board, e["id"], a.x, a.y)
            print(f"Liegt auf {a.board}.")
    elif a.befehl == "quelle":
        q, neu = akte.quelle(a.titel, a.url, a.herausgeber, a.guete, a.abgerufen, a.veroeffentlicht)
        print(("Neu: " if neu else "Vorhanden: ") + f"[{q['id']}] {q['titel']}")
    elif a.befehl == "faden":
        belege = [{"quelle": q, "zitat_woertlich": (a.zitat[i] if i < len(a.zitat) else ""),
                   "fundstelle": (a.fundstelle[i] if i < len(a.fundstelle) else "")} for i, q in enumerate(a.quelle)]
        v = aktionen.faden_ziehen(akte, a.von, a.nach, typ=a.typ, beschreibung=a.text, aussageart=a.art,
                                  start=a.start, ende=a.ende, aktuell=a.aktuell, belege=belege)
        print(f"Faden [{v['id']}] als Entwurf angelegt.")
        for b in v.get("befunde", []):
            print(f"  offen: {b['text']}")
    elif a.befehl == "beleg":
        v = aktionen.beleg_hinzufuegen(akte, a.faden, a.quelle, a.zitat, a.fundstelle)
        print(f"Faden [{v['id']}] hat jetzt {len(v.get('belege', []))} Beleg(e).")
    elif a.befehl == "gruppen":
        zeige(aktionen.gruppen_setzen(akte, a.board, lade_datei(a.datei)))
    elif a.befehl == "aufraeumen":
        w = akte.post(f"/boards/{a.board}/aufraeumen/")
        print(f"Aufgeräumt: {len(w['karten'])} Karten, {len(w['zettel'])} Zettel, {len(w['rahmen'])} Rahmen.")
    elif a.befehl == "pruefung":
        p = akte.pruefung(a.board)
        ok = sum(1 for f in p["faeden"] if f["ok"])
        print(f"{ok}/{len(p['faeden'])} Fäden ohne offenen Befund.")
        for f in p["faeden"]:
            if not f["ok"]:
                print(f"  ✗ {f['titel']}: " + "; ".join(b["text"] for b in f["befunde"]))
    elif a.befehl == "fahrt":
        f = akte.post(f"/boards/{a.board}/fahrten/aus-beschreibung/", lade_datei(a.datei))
        print(f"Fahrt „{f['titel']}“ mit {len(f['stationen'])} Stationen gespeichert.")
    elif a.befehl == "weg":
        von, nach = akte.entitaet_finden(a.von), akte.entitaet_finden(a.nach)
        if not von or not nach:
            raise ValueError(f"Unbekannt: {a.von if not von else a.nach}")
        zeige(akte.weg(von["id"], nach["id"], a.nur_belegt))
    elif a.befehl == "sichern":
        ids = [q["id"] for q in akte.get("/quellen/") if q["url"]] if a.alle else [a.quelle]
        if None in ids:
            raise ValueError("Quelle-ID oder --alle angeben.")
        for i in ids:
            akte.post(f"/quellen/{i}/sichern/")
        print(f"Sicherung für {len(ids)} Quelle(n) angestoßen.")
    elif a.befehl == "zitat-pruefen":
        zeige(aktionen.zitat_pruefen(akte, a.beleg, a.quelle, a.warten))
    elif a.befehl == "anhang":
        pfad = Path(a.datei)
        dateien = {"datei": (pfad.name, pfad.read_bytes())}
        if a.quelle:
            q = akte.anfrage("POST", f"/quellen/{a.quelle}/anhang/", files=dateien)
        else:
            felder = {"titel": a.titel or pfad.stem, "herausgeber": a.herausgeber}
            if a.board:
                felder["board"] = a.board
            q = akte.anfrage("POST", "/quellen/aus-datei/", files=dateien, data=felder)
        print(f"Gesichert an Quelle [{q['id']}] {q['titel']}")
    elif a.befehl == "beweis":
        akte.post(f"/boards/{a.board}/beweise/", {"quelle": a.quelle})
        print(f"Beweisstück {a.quelle} liegt auf {a.board}.")
    elif a.befehl == "import":
        zeige(aktionen.importieren(akte, lade_datei(a.datei), trocken=not a.echt))
    elif a.befehl == "fotos":
        zeige(aktionen.fotos_setzen(akte, lade_datei(a.datei)))
    elif a.befehl == "export":
        Path(a.ziel).write_bytes(akte.get("/export/obsidian/"))
        print(f"Vault geschrieben: {a.ziel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
