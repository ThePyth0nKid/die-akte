# SPDX-License-Identifier: MIT
"""Arbeitsschritte an der Wand, gemeinsam für die CLI ``akte`` und den MCP-Server ``akte-mcp``.

Alles gibt Daten zurück und druckt nichts; die Aufrufer entscheiden, wie sie es zeigen.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import Akte, AkteFehler


# ─── Gruppen (Themen-Rahmen) ──────────────────────────────────────────────────

def gruppen_lesen(gruppen: dict) -> dict[str, tuple[str, list[str]]]:
    """{Titel: [Namen]} oder {Titel: {farbe: "#RRGGBB", karten: [Namen]}} → {Titel: (farbe, [Namen])}."""
    aus = {}
    for titel, wert in gruppen.items():
        if isinstance(wert, dict):
            aus[titel] = (wert.get("farbe") or "", list(wert.get("karten") or []))
        else:
            aus[titel] = ("", list(wert))
    return aus


def gruppen_setzen(akte: Akte, board: str, gruppen: dict) -> dict:
    """Jede Gruppe bekommt einen Rahmen; die Karten wandern dafür erst weit auseinander, damit sich keine Rahmen
    überschneiden, dann packt „aufräumen“ alles dicht. Ein Rahmen mit Farbe (#RRGGBB) wird zum Schild.
    ``"@slug"`` legt die Mappe dieses Boards in den Rahmen."""
    gelesen = gruppen_lesen(gruppen)
    w = akte.wand(board)
    je_name: dict[str, dict] = {}
    for k in w["karten"]:
        je_name[k["entitaet_detail"]["name"].lower()] = k
        je_name[k["entitaet_detail"]["slug"]] = k
    for m in w.get("mappen", []):
        je_name["@" + m["ziel"]] = {**m, "_art": "mappe"}
    fehlen = [n for _, namen in gelesen.values() for n in namen if n.lower() not in je_name]
    if fehlen:
        raise ValueError("Nicht auf dem Board: " + ", ".join(fehlen))
    for r in w["rahmen"]:
        if r["titel"] in gelesen:
            akte.delete(f"/boards/{board}/rahmen/{r['id']}/")
    positionen = []
    for i, (titel, (farbe, namen)) in enumerate(gelesen.items()):
        ox = (i + 1) * 20000
        for j, n in enumerate(namen):
            k = je_name[n.lower()]
            positionen.append({"art": k.get("_art", "karte"), "id": k["id"], "x": ox + (j % 4) * 340, "y": (j // 4) * 530})
        zeilen = (len(namen) + 3) // 4
        akte.post(f"/boards/{board}/rahmen/", {"titel": titel, "x": ox - 60, "y": -60, "farbe": farbe,
                                                "breite": min(len(namen), 4) * 340 + 60, "hoehe": zeilen * 530 + 60})
    akte.post(f"/boards/{board}/positionen/", positionen)
    w = akte.post(f"/boards/{board}/aufraeumen/")
    return {"rahmen": len(gelesen), "karten_einsortiert": len(positionen), "karten_auf_wand": len(w["karten"])}


# ─── Zettel, Fotos, Gelenke ──────────────────────────────────────────────────

def zettel_anlegen(akte: Akte, liste: list, board: str | None = None) -> dict:
    """Zettel (Frage, Notiz, Meinung) anlegen; gleicher Text auf derselben Wand wird übersprungen."""
    for i, z in enumerate(liste, 1):
        if not isinstance(z, dict) or not str(z.get("text", "")).strip() or not (board or z.get("board")):
            raise ValueError(f"Zettel {i}: „text“ und „board“ fehlen.")
    waende: dict[str, dict] = {}
    neu = 0
    for z in liste:
        slug = board or z["board"]
        w = waende.get(slug) or waende.setdefault(slug, akte.wand(slug))
        if any(v["text"].strip() == z["text"].strip() for v in w["zettel"]):
            continue
        x = max((k["x"] for k in w["karten"]), default=0) + 500
        y = len(w["zettel"]) * 260
        w["zettel"].append(akte.post(f"/boards/{slug}/zettel/", {"art": z.get("art", "notiz"), "text": z["text"],
                                                                "x": x, "y": y}))
        neu += 1
    return {"neu": neu, "vorhanden": len(liste) - neu}


def bild_aenderung(vorhanden: dict, eintrag: dict) -> dict:
    """Was an Foto und Wikidata-Kennung gesetzt werden darf: nur leere Felder, nie an freigegebenen Karten.
    Foto und Nachweis gehören zusammen (CC BY/BY-SA verlangt die Nennung), also beide oder keins."""
    if vorhanden.get("status") == "freigegeben":
        return {}
    neu = {}
    if eintrag.get("bild_url") and eintrag.get("bild_nachweis") and not vorhanden.get("bild_url"):
        neu["bild_url"] = eintrag["bild_url"]
        neu["bild_nachweis"] = eintrag["bild_nachweis"][:200]
    if eintrag.get("wikidata_qid") and not vorhanden.get("wikidata_qid"):
        neu["wikidata_qid"] = eintrag["wikidata_qid"]
    return neu


def fotos_setzen(akte: Akte, liste: list) -> dict:
    """Fotoliste (name/slug, bild_url, bild_nachweis, wikidata_qid) auf Karten ohne Foto legen."""
    gesetzt, fehlen, fehler = 0, [], []
    for eintrag in liste:
        e = akte.entitaet_finden(eintrag.get("slug") or eintrag["name"]) or akte.entitaet_finden(eintrag["name"])
        if not e:
            fehlen.append(eintrag["name"])
            continue
        try:
            neu = bild_aenderung(akte.get(f"/entitaeten/{e['id']}/"), eintrag)
            if neu:
                akte.patch(f"/entitaeten/{e['id']}/", neu)
                gesetzt += 1
        except AkteFehler as grund:
            # Einzelfehler überspringen; Server kaputt oder Token ungültig bricht den Stapel ab.
            if grund.status >= 500 or grund.status in (401, 403):
                raise
            fehler.append(f"{eintrag['name']}: {grund}")
    return {"geaendert": gesetzt, "nicht_gefunden": fehlen, "abgelehnt": fehler}


def gelenke(akte: Akte, board: str, legen: bool = False) -> dict:
    """Karten, die in mehreren Mappen unter dieser Wand stecken; auf Wunsch auf die Wand holen."""
    w = akte.wand(board)
    liste = w.get("gelenke", [])
    if legen and liste:
        for g in liste:
            akte.auf_board(board, g["id"], wand=w)
        akte.post(f"/boards/{board}/aufraeumen/")
    return {"gelenke": [{"id": g["id"], "name": g["name"]} for g in liste], "gelegt": bool(legen and liste)}


# ─── Fäden und Belege ─────────────────────────────────────────────────────────

def faden_ziehen(akte: Akte, von: str, nach: str, *, typ: str = "sonstiges", beschreibung: str = "",
                 aussageart: str = "belegt", start: str | None = None, ende: str | None = None,
                 aktuell: bool = False, betrag: str | None = None, waehrung: str = "",
                 belege: list[dict] | None = None) -> dict:
    """Faden zwischen zwei Karten (Namen oder Slugs) als Entwurf. ``belege``: [{quelle, zitat_woertlich, fundstelle}]."""
    a, b = akte.entitaet_finden(von), akte.entitaet_finden(nach)
    if not a or not b:
        raise ValueError(f"Unbekannte Karte: {von if not a else nach}. Erst als Karte anlegen.")
    return akte.post("/verbindungen/", {
        "von": a["id"], "nach": b["id"], "typ": typ, "beschreibung": beschreibung, "start": start, "ende": ende,
        "aktuell": aktuell, "betrag": betrag, "waehrung": waehrung, "aussageart": aussageart,
        "belege": [{"quelle": int(x["quelle"]), "zitat_woertlich": x.get("zitat_woertlich", ""),
                    "fundstelle": x.get("fundstelle", "")} for x in (belege or [])],
    })


def beleg_hinzufuegen(akte: Akte, faden_id: int, quelle_id: int, zitat_woertlich: str = "",
                      fundstelle: str = "") -> dict:
    """Einen weiteren Beleg an einen Faden hängen; die vorhandenen Belege bleiben."""
    faden = akte.get(f"/verbindungen/{faden_id}/")
    belege = [{"quelle": b["quelle"], "zitat_woertlich": b.get("zitat_woertlich", ""),
               "fundstelle": b.get("fundstelle", "")} for b in faden.get("belege", [])]
    if any(b["quelle"] == quelle_id for b in belege):
        raise ValueError(f"Quelle {quelle_id} belegt diesen Faden schon. Je Faden und Quelle ein Beleg.")
    belege.append({"quelle": quelle_id, "zitat_woertlich": zitat_woertlich, "fundstelle": fundstelle})
    return akte.patch(f"/verbindungen/{faden_id}/", {"belege": belege})


def zitat_pruefen(akte: Akte, beleg_id: int, quelle_id: int, warten_s: int = 60, takt_s: float = 3.0) -> dict:
    """Fundstelle eines Belegs anstoßen und auf das Ergebnis warten: Steht das Zitat wörtlich an der Quelle?"""
    akte.post(f"/quellen/{quelle_id}/sichern/")
    ende = time.monotonic() + max(0, warten_s)
    while True:
        for s in akte.sicherungen(quelle_id):
            if s["art"] == "fundstelle" and s.get("beleg") == beleg_id and s["status"] in ("fertig", "fehler"):
                gefunden = s["status"] == "fertig"
                return {"ergebnis": "gefunden" if gefunden else "nicht_gefunden_oder_fehler",
                        "sicherung": s["id"], "hinweis": "" if gefunden else (s.get("fehler") or "")}
        if time.monotonic() >= ende:
            return {"ergebnis": "laeuft", "hinweis": "Noch kein Ergebnis; später erneut prüfen."}
        time.sleep(takt_s)


# ─── Import (mit Probelauf) ──────────────────────────────────────────────────

@dataclass
class ImportBericht:
    trocken: bool
    quellen_neu: list[str] = field(default_factory=list)
    karten_neu: list[str] = field(default_factory=list)
    faeden_neu: int = 0
    faeden_vorhanden: int = 0
    fehler: list[str] = field(default_factory=list)

    def als_dict(self) -> dict:
        return self.__dict__.copy()


def importieren(akte: Akte, daten: dict, trocken: bool = True) -> dict:
    """Paket {board?, quellen, entitaeten, verbindungen} wie ``manage.py akte_import``, aber über die API.
    ``trocken`` (Standard) liest nur und meldet, was angelegt würde."""
    bericht = ImportBericht(trocken=trocken)
    quellen: dict[str, int | None] = {}
    for q in daten.get("quellen", []):
        vorhanden = None
        if q.get("url"):
            vorhanden = next((x for x in akte.get("/quellen/", params={"q": q["url"]}) if x["url"] == q["url"]), None)
        if vorhanden:
            quellen[q["schluessel"]] = vorhanden["id"]
        elif trocken:
            bericht.quellen_neu.append(q["titel"])
            quellen[q["schluessel"]] = None
        else:
            obj, _ = akte.quelle(q["titel"], q.get("url", ""), q.get("herausgeber", ""), q.get("guete", "sekundaer"),
                                 q.get("abgerufen_am"), q.get("veroeffentlicht_am"))
            quellen[q["schluessel"]] = obj["id"]
            bericht.quellen_neu.append(q["titel"])
    entitaeten: dict[str, int | None] = {}
    for e in daten.get("entitaeten", []):
        vorhanden = akte.entitaet_finden(e["name"])
        if vorhanden:
            entitaeten[e["schluessel"]] = vorhanden["id"]
            continue
        bericht.karten_neu.append(e["name"])
        if trocken:
            entitaeten[e["schluessel"]] = None
            continue
        obj, _ = akte.entitaet(e["name"], e["typ"], e.get("kurzbeschreibung", ""), e.get("oeffentliche_person", False),
                               e.get("notiz_md", ""))
        entitaeten[e["schluessel"]] = obj["id"]
        neu = bild_aenderung(obj, e)
        if neu:
            akte.patch(f"/entitaeten/{obj['id']}/", neu)
    for v in daten.get("verbindungen", []):
        for teil in ("von", "nach"):
            if v[teil] not in entitaeten:
                bericht.fehler.append(f"Faden {v.get('beschreibung', '')!r}: Schlüssel {v[teil]!r} fehlt unter entitaeten.")
        for b in v.get("belege", []):
            if b["quelle"] not in quellen:
                bericht.fehler.append(f"Faden {v.get('beschreibung', '')!r}: Quelle {b['quelle']!r} fehlt unter quellen.")
    if bericht.fehler:
        return bericht.als_dict()
    vorhanden_faeden = {(f["von"], f["nach"], f["typ"], f["beschreibung"]) for f in akte.get("/verbindungen/")}
    for v in daten.get("verbindungen", []):
        schluessel = (entitaeten[v["von"]], entitaeten[v["nach"]], v["typ"], v.get("beschreibung", ""))
        if None not in schluessel[:2] and schluessel in vorhanden_faeden:
            bericht.faeden_vorhanden += 1
            continue
        bericht.faeden_neu += 1
        if trocken:
            continue
        akte.post("/verbindungen/", {
            "von": schluessel[0], "nach": schluessel[1], "typ": v["typ"], "beschreibung": v.get("beschreibung", ""),
            "start": v.get("start"), "ende": v.get("ende"), "aktuell": v.get("aktuell", False),
            "betrag": v.get("betrag"), "waehrung": v.get("waehrung", ""), "aussageart": v.get("aussageart", "belegt"),
            "belege": [{"quelle": quellen[b["quelle"]], "zitat_woertlich": b.get("zitat_woertlich", ""),
                        "fundstelle": b.get("fundstelle", "")} for b in v.get("belege", [])],
        })
    if "board" in daten and not trocken:
        b = daten["board"]
        if b["slug"] not in {x["slug"] for x in akte.boards()}:
            akte.post("/boards/", {"titel": b["titel"], "slug": b["slug"], "beschreibung": b.get("beschreibung", "")})
        wand = akte.wand(b["slug"])
        for e in daten.get("entitaeten", []):
            if e.get("auf_board", True):
                akte.auf_board(b["slug"], entitaeten[e["schluessel"]], e.get("x"), e.get("y"), wand=wand)
        eltern = b.get("eltern") or []
        for slug in [eltern] if isinstance(eltern, str) else eltern:
            akte.mappe_legen(slug, b["slug"])
    return bericht.als_dict()


# ─── Öffentlicher Export (Datensatz) ─────────────────────────────────────────

EXPORT_SCHEMA = "akte-export/1"
_WEG_BOARD = {"id", "darf_bearbeiten"}
_WEG_WAND = {"darf_bearbeiten", "befunde", "ausgeblendet", "fahrten", "beweise"}


def _sauber(wand: dict) -> dict:
    """Nur was Besucher ohne Konto sehen, ohne interne Schlüssel. Rahmen werden 1..n neu nummeriert."""
    aus = {k: v for k, v in wand.items() if k not in _WEG_WAND}
    aus["board"] = {k: v for k, v in wand["board"].items() if k not in _WEG_BOARD}
    aus["rahmen"] = [{**{k: v for k, v in r.items() if k != "id"}, "nr": i}
                     for i, r in enumerate(sorted(wand.get("rahmen", []), key=lambda r: (r.get("y", 0), r.get("x", 0))), 1)]
    for f in aus.get("faeden", []):
        for k in ("befunde", "ausgeblendet"):
            f.pop(k, None)
        for b in f.get("belege", []):
            if isinstance(b.get("quelle_detail"), dict):
                b["quelle_detail"].pop("stand", None)
    return aus


def _json(daten: Any) -> bytes:
    return (json.dumps(daten, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def _csv(zeilen: list[dict], spalten: list[str]) -> bytes:
    puffer = io.StringIO(newline="")
    schreiber = csv.DictWriter(puffer, fieldnames=spalten, extrasaction="ignore", lineterminator="\n")
    schreiber.writeheader()
    for z in zeilen:
        schreiber.writerow({k: ("" if z.get(k) is None else z.get(k)) for k in spalten})
    return puffer.getvalue().encode("utf-8")


def export_oeffentlich(basis: str, ziel: Path, *, boards: list[str] | None = None, stand: str = "",
                       lizenz: str = "CC-BY-SA-4.0", herausgeber: str = "",
                       privatnamen: list[str] | None = None) -> dict:
    """Schreibt genau das, was ein Besucher ohne Konto sieht, als JSON und CSV mit Prüfsummen.

    Liest anonym (ohne Token), braucht also keinen Zugang zur Datenbank. ``privatnamen``: volle Namen von
    Privatpersonen, die nirgends im Export stehen dürfen (nur zur Laufzeit übergeben, nie gespeichert); ein Treffer
    bricht ab, bevor eine Datei geschrieben wird.
    """
    akte = Akte(basis)
    alle = akte.boards()
    slugs = sorted(b["slug"] for b in alle if boards is None or b["slug"] in boards)
    dateien: dict[str, bytes] = {}
    karten, faeden, belege, quellen, rahmen, zettel = [], [], [], {}, [], []
    for slug in slugs:
        w = _sauber(akte.wand(slug))
        dateien[f"boards/{slug}.json"] = _json(w)
        for k in w.get("karten", []):
            e = k.get("entitaet_detail", {})
            karten.append({"board": slug, "karte": k.get("entitaet"), "name": e.get("name"), "typ": e.get("typ"),
                           "slug": e.get("slug"), "kurzbeschreibung": e.get("kurzbeschreibung"),
                           "oeffentliche_person": e.get("oeffentliche_person"), "bild_url": e.get("bild_url"),
                           "bild_nachweis": e.get("bild_nachweis")})
        for f in w.get("faeden", []):
            faeden.append({"board": slug, "faden": f.get("id"), "von": f.get("von"), "nach": f.get("nach"),
                           "typ": f.get("typ"), "beschreibung": f.get("beschreibung"), "start": f.get("start"),
                           "ende": f.get("ende"), "aktuell": f.get("aktuell"), "betrag": f.get("betrag"),
                           "waehrung": f.get("waehrung"), "aussageart": f.get("aussageart")})
            for b in f.get("belege", []):
                q = b.get("quelle_detail") or {}
                belege.append({"board": slug, "faden": f.get("id"), "quelle": b.get("quelle"),
                               "zitat_woertlich": b.get("zitat_woertlich"), "fundstelle": b.get("fundstelle")})
                if q:
                    quellen[q.get("id")] = {k: q.get(k) for k in ("id", "titel", "url", "herausgeber",
                                                                   "veroeffentlicht_am", "abgerufen_am",
                                                                   "archiv_url", "guete")}
        for r in w.get("rahmen", []):
            rahmen.append({"board": slug, **{k: r.get(k) for k in ("nr", "titel", "farbe", "x", "y", "breite", "hoehe")}})
        for z in w.get("zettel", []):
            zettel.append({"board": slug, "art": z.get("art"), "text": z.get("text")})

    dateien["tabellen/karten.csv"] = _csv(sorted(karten, key=lambda z: (z["board"], str(z["karte"]))),
                                          ["board", "karte", "name", "typ", "slug", "kurzbeschreibung",
                                           "oeffentliche_person", "bild_url", "bild_nachweis"])
    dateien["tabellen/faeden.csv"] = _csv(sorted(faeden, key=lambda z: (z["board"], str(z["faden"]))),
                                          ["board", "faden", "von", "nach", "typ", "beschreibung", "start", "ende",
                                           "aktuell", "betrag", "waehrung", "aussageart"])
    dateien["tabellen/belege.csv"] = _csv(sorted(belege, key=lambda z: (z["board"], str(z["faden"]), str(z["quelle"]))),
                                          ["board", "faden", "quelle", "zitat_woertlich", "fundstelle"])
    dateien["tabellen/quellen.csv"] = _csv([quellen[k] for k in sorted(quellen, key=str)],
                                           ["id", "titel", "url", "herausgeber", "veroeffentlicht_am", "abgerufen_am",
                                            "archiv_url", "guete"])
    dateien["tabellen/rahmen.csv"] = _csv(rahmen, ["board", "nr", "titel", "farbe", "x", "y", "breite", "hoehe"])
    dateien["tabellen/zettel.csv"] = _csv(zettel, ["board", "art", "text"])
    dateien["index.json"] = _json({"schema": EXPORT_SCHEMA, "boards": slugs, "lizenz": lizenz,
                                   "herausgeber": herausgeber, "stand": stand})

    treffer = datenschutz_treffer(dateien, privatnamen or [])
    if treffer:
        raise ValueError("Datenschutz: Name einer Privatperson im Export (" + "; ".join(treffer[:10]) + "). Abbruch.")

    ziel.mkdir(parents=True, exist_ok=True)
    pruefsummen = []
    for name in sorted(dateien):
        pfad = ziel / name
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_bytes(dateien[name])
        pruefsummen.append(f"{hashlib.sha256(dateien[name]).hexdigest()}  {name}")
    (ziel / "pruefsummen.sha256").write_text("\n".join(pruefsummen) + "\n", encoding="utf-8", newline="\n")
    return {"boards": slugs, "dateien": len(dateien) + 1, "karten": len(karten), "faeden": len(faeden),
            "belege": len(belege), "quellen": len(quellen)}


def datenschutz_treffer(dateien: dict[str, bytes], privatnamen: list[str]) -> list[str]:
    """Volle Namen (und ihre URL-Schreibweisen) von Privatpersonen in den erzeugten Dateien suchen."""
    treffer = []
    for name in privatnamen:
        name = name.strip()
        if len(name) < 4:
            continue
        formen = {name.lower(), name.lower().replace(" ", "-"), name.lower().replace(" ", "_"),
                  name.lower().replace(" ", "%20"), name.lower().replace(" ", "+")}
        for datei, inhalt in dateien.items():
            text = inhalt.decode("utf-8", "replace").lower()
            if any(f in text for f in formen):
                treffer.append(f"{datei}")
    return sorted(set(treffer))
