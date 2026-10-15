#!/usr/bin/env python3
"""fotos_suchen — freie Bilder für Akte-Karten auf Wikimedia Commons finden und laden.

Nur Wikimedia Commons, nur CC0, Public Domain, CC BY und CC BY-SA. Lizenz und Urheber kommen
immer aus der Commons-API (extmetadata), nie aus dem Gedächtnis. Weg: Wikidata → Bild-Eigenschaft
je Kartentyp (P18 Bild, P154 Logo, P158 Siegel, P94 Wappen) → Commons-Metadaten. Hat Wikidata
nichts, sucht das Skript direkt auf Commons.

Eingabe für ``suchen`` ist eine JSON-Liste, je Karte:

    [{"name": "Sam Altman", "typ": "person"},
     {"name": "Bundesrat", "typ": "behoerde", "qid": "Q155329"},
     {"name": "§ 24e ASOG Berlin", "typ": "gesetz", "suche": "Abgeordnetenhaus Berlin"}]

``qid`` erzwingt das Wikidata-Objekt, ``wd`` ersetzt den Wikidata-Suchbegriff, ``suche`` den für
Commons (Standard ist jeweils der Name). ``--kurz`` gibt statt JSON eine Tabelle zum Lesen aus.

    python scripts/akte/fotos_suchen.py suchen karten.json -o kandidaten.json
    python scripts/akte/fotos_suchen.py suchen karten.json --kurz
    python scripts/akte/fotos_suchen.py laden "File:Sam Altman 2023.jpg" altman \\
        --motiv "Sam Altman, OpenAI-Chef, 2023" --ordner "C:\\...\\akte-personen"

``laden`` holt die 1280-px-Vorschau (upload.wikimedia.org weist Originale oft mit 429 ab), legt
``<kurzname>_<n>.<endung>`` und daneben eine ``.json`` im Format von QUELLEN-Bilder.json ab.
Das Bild danach selbst ansehen: falsche Person, unscharf oder Wasserzeichen → löschen.
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

UA = os.environ.get("AKTE_ABRUF_KENNUNG", "Die-Akte/0.1 (Fotosuche)")  # nie eine Mail-Adresse im User-Agent
WIKIDATA = "https://www.wikidata.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
ORDNER = Path(os.environ.get("AKTE_FOTO_ORDNER", "fotos"))

#: Welche Wikidata-Eigenschaften je Kartentyp ein Bild liefern, in dieser Reihenfolge.
EIGENSCHAFTEN = {
    "person": ["P18"],
    "ort": ["P18"],
    "firma": ["P18", "P154"],
    "behoerde": ["P18", "P158", "P154", "P94"],
    "organisation": ["P18", "P154", "P158"],
    "partei": ["P154", "P18"],
}
STANDARD_EIGENSCHAFTEN = ["P18", "P154"]  # gesetz, dokument, system, ereignis
#: Kategorien, Urheber- oder Credit-Texte, an denen KI-Bilder auf Commons zu erkennen sind.
KI_MUSTER = re.compile(r"ai-generated|(generated|created) (by|with|using) (ai|artificial intelligence)|pd-algorithm|pd-ai|"
                       r"midjourney|stable diffusion|dall-?e|adobe firefly|nano banana|leonardo\.ai|ideogram", re.I)
#: Endung aus dem MIME-Typ der geladenen Datei.
ENDUNGEN = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
LADE_HOSTS = {"upload.wikimedia.org", "commons.wikimedia.org"}  # Bilder nur von Wikimedia
WIEDERHOLEN = (429, 500, 502, 503, 504)
#: bild_url und bild_nachweis sind in der Akte-API höchstens 200 Zeichen lang.
MAX_LAENGE = 200

s = requests.Session()
s.headers["User-Agent"] = UA
_letzte = 0.0


def api(url: str, **params) -> dict:
    """GET mit Drossel (höchstens 2 Anfragen je Sekunde) und einem zweiten Versuch bei 429/5xx."""
    global _letzte
    params.update(format="json", formatversion=2)
    for versuch in range(3):
        warten = 0.5 - (time.time() - _letzte)
        if warten > 0:
            time.sleep(warten)
        _letzte = time.time()
        r = s.get(url, params=params, timeout=60)
        if r.status_code in WIEDERHOLEN and versuch < 2:
            time.sleep(5 * (versuch + 1))
            continue
        r.raise_for_status()
        return r.json()
    return {}


def ohne_html(text: str) -> str:
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()
    # Commons rendert manche Vorlagen doppelt („Unknown authorUnknown author“)
    halb = len(t) // 2
    return t[:halb] if len(t) % 2 == 0 and t and t[:halb] == t[halb:] else t


def datum(meta: dict) -> str:
    """Aufnahmedatum ohne die unsichtbaren Wikidata-Reste („date QS:P571,…“)."""
    return ohne_html(meta.get("DateTimeOriginal")).split("date QS")[0].strip()[:40]


def lizenz_pruefen(meta: dict) -> tuple[bool, str]:
    """Frei im Sinne der Akte? Liefert (ja/nein, Grund). Maßgeblich ist der Maschinen-Code „License“."""
    code = (meta.get("License") or "").lower()
    kurz = meta.get("LicenseShortName") or code
    ki = KI_MUSTER.search(" ".join(meta.get(f) or "" for f in ("Categories", "Artist", "Credit")))
    if ki:
        return False, f"KI-Verdacht ({ki.group(0)})"
    if meta.get("NonFree") or "fair use" in kurz.lower():
        return False, "unfrei"
    if re.match(r"cc-by-(nc|nd)", code):
        return False, f"{kurz} (NC/ND nicht erlaubt)"
    if code == "cc0" or code.startswith("pd") or re.match(r"cc-by(-sa)?-\d", code):
        return True, kurz
    return False, f"{kurz or 'ohne Lizenz'} (nicht in der erlaubten Liste)"


def bildinfos(titel: list[str], breite: int = 1280) -> dict:
    """Commons-Metadaten für bis zu 50 Dateien je Anfrage; Schlüssel ist der Dateititel."""
    ergebnis = {}
    for i in range(0, len(titel), 50):
        d = api(COMMONS, action="query", titles="|".join(titel[i:i + 50]), prop="imageinfo",
                iiprop="extmetadata|url|size|mime", iiurlwidth=breite)
        for seite in d.get("query", {}).get("pages", []):
            if seite.get("imageinfo"):
                ergebnis[seite["title"]] = seite["imageinfo"][0]
    return ergebnis


def kandidat(titel: str, info: dict, herkunft: str) -> dict:
    """Ein Commons-Treffer als Zeile: Lizenzurteil, Urheber, Maße, Datum, passt die URL in die API?"""
    meta = {k: v.get("value", "") for k, v in info.get("extmetadata", {}).items()}
    frei, grund = lizenz_pruefen(meta)
    return {
        "titel": titel, "herkunft": herkunft, "frei": frei, "lizenz": grund,
        "urheber": ohne_html(meta.get("Artist")), "breite": info.get("width"), "hoehe": info.get("height"),
        "datum": datum(meta), "seite": info.get("descriptionurl"),
        "beschreibung": ohne_html(meta.get("ImageDescription"))[:160],
        "url_passt": len(filepath_url(titel)) <= MAX_LAENGE,  # sonst lehnt die Akte-API die bild_url ab
    }


def suchbegriffe(karte: dict) -> list[str]:
    """„Bundesamt für X (BfX)“ → erst der ganze Name, dann ohne Klammer, dann das Kürzel."""
    name = karte["name"]
    begriffe = [karte.get("wd") or name, re.sub(r"\s*\(.*?\)", "", name)] + re.findall(r"\((.*?)\)", name)
    return list(dict.fromkeys(b.strip() for b in begriffe if b.strip()))


def wikidata_objekt(karte: dict) -> dict | None:
    """Das Wikidata-Objekt zur Karte: erzwungene QID oder bester Suchtreffer (deutsch, dann englisch)."""
    qid = karte.get("qid")
    for begriff in ([] if qid else suchbegriffe(karte)):
        for sprache in ("de", "en"):
            treffer = api(WIKIDATA, action="wbsearchentities", search=begriff,
                          language=sprache, uselang="de", type="item", limit=1).get("search", [])
            if treffer:
                qid = treffer[0]["id"]
                break
        if qid:
            break
    if not qid:
        return None
    d = api(WIKIDATA, action="wbgetentities", ids=qid, props="claims|labels|descriptions", languages="de|en")
    return d.get("entities", {}).get(qid)


def commons_suche(begriff: str, anzahl: int) -> list[str]:
    """Dateititel aus der Commons-Volltextsuche (Namensraum Datei)."""
    d = api(COMMONS, action="query", list="search", srsearch=begriff, srnamespace=6, srlimit=anzahl)
    # nur Bilder (keine PDFs, Videos, Tondateien)
    return [t["title"] for t in d.get("query", {}).get("search", [])
            if re.search(r"\.(jpe?g|png|svg|tiff?|webp|gif)$", t["title"], re.I)]


def suchen(karten: list[dict], anzahl: int, zwischenstand: Path | None = None) -> list[dict]:
    """Je Karte Wikidata-Objekt und Bildkandidaten. Ein Netzfehler kostet nur diese eine Karte.
    Mit ``zwischenstand`` wird nach jeder Karte gespeichert: ein Abbruch nach Karte 100 verliert nicht die 99 davor."""
    ausgabe = []
    for karte in karten:
        try:
            ausgabe.append(karte_suchen(karte, anzahl))
        except requests.RequestException as fehler:
            print(f"{karte['name'][:50]:50} FEHLER {fehler}", file=sys.stderr)
            ausgabe.append({"name": karte["name"], "typ": karte.get("typ", ""), "qid": "", "wikidata": "",
                            "kandidaten": [], "fehler": str(fehler)})
        if zwischenstand:
            zwischenstand.write_text(json.dumps(ausgabe, ensure_ascii=False, indent=2), encoding="utf-8")
    return ausgabe


def karte_suchen(karte: dict, anzahl: int) -> dict:
    obj = wikidata_objekt(karte)
    titel_herkunft: dict[str, str] = {}
    eintrag = {"name": karte["name"], "typ": karte.get("typ", ""), "qid": "", "wikidata": ""}
    if obj:
        eintrag["qid"] = obj["id"]
        label = (obj.get("labels", {}).get("de") or obj.get("labels", {}).get("en") or {}).get("value", "")
        beschr = (obj.get("descriptions", {}).get("de") or obj.get("descriptions", {}).get("en") or {}).get("value", "")
        eintrag["wikidata"] = f"{label} – {beschr}"
        for p in EIGENSCHAFTEN.get(karte.get("typ"), STANDARD_EIGENSCHAFTEN):
            for aussage in obj.get("claims", {}).get(p, []):
                wert = aussage.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(wert, str):
                    titel_herkunft.setdefault(f"File:{wert}", f"Wikidata {p}")
    for t in commons_suche(karte.get("suche") or karte["name"], anzahl):
        titel_herkunft.setdefault(t, "Commons-Suche")
    infos = bildinfos(list(titel_herkunft))
    eintrag["kandidaten"] = [kandidat(t, infos[t], h) for t, h in titel_herkunft.items() if t in infos]
    frei = sum(k["frei"] for k in eintrag["kandidaten"])
    print(f"{karte['name'][:50]:50} {eintrag['qid']:>11}  {frei} frei / {len(eintrag['kandidaten'])}", file=sys.stderr)
    return eintrag


def bildmasse(daten: bytes) -> tuple[int, int] | None:
    """Echte Breite und Höhe aus dem PNG- bzw. JPEG-Kopf. Nötig, weil Commons bei kleinen
    Vorlagen das Original liefert, in thumbwidth/thumbheight aber die hochgerechneten Maße meldet."""
    if daten[:8] == b"\x89PNG\r\n\x1a\n":
        masse = int.from_bytes(daten[16:20], "big"), int.from_bytes(daten[20:24], "big")
        return masse if len(daten) >= 24 and all(masse) else None
    i = 2
    while daten[:2] == b"\xff\xd8" and i + 9 < len(daten):
        if daten[i] != 0xFF:
            i += 1
            continue
        marke, laenge = daten[i + 1], int.from_bytes(daten[i + 2:i + 4], "big")
        if 0xC0 <= marke <= 0xCF and marke not in (0xC4, 0xC8, 0xCC):  # SOF-Block
            masse = int.from_bytes(daten[i + 7:i + 9], "big"), int.from_bytes(daten[i + 5:i + 7], "big")
            return masse if all(masse) else None
        i += 2 + max(laenge, 2)
    return None


def naechster_name(ordner: Path, kurzname: str, endung: str) -> Path:
    """Erster freier Name <kurzname>_<n> im Ordner. Nur Kleinbuchstaben, Ziffern, _ und - erlaubt."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", kurzname):
        raise SystemExit(f"Kurzname nur aus a-z, 0-9, _ und -: {kurzname!r}")
    n = 1
    while any(ordner.glob(f"{kurzname}_{n}.*")):
        n += 1
    return ordner / f"{kurzname}_{n}{endung}"


def laden(titel: str, kurzname: str, motiv: str, ordner: Path, art: str, breite: int) -> dict:
    """Vorschau einer freien Commons-Datei laden, Datei und .json (Format QUELLEN-Bilder.json) schreiben."""
    titel = titel if titel.startswith("File:") else f"File:{titel}"
    if len(filepath_url(titel)) > MAX_LAENGE:
        raise SystemExit(f"bild_url wäre {len(filepath_url(titel))} Zeichen lang (erlaubt {MAX_LAENGE}): {titel}")
    info = bildinfos([titel], breite).get(titel)
    if not info:
        raise SystemExit(f"Nicht auf Commons: {titel}")
    meta = {k: v.get("value", "") for k, v in info.get("extmetadata", {}).items()}
    frei, lizenz = lizenz_pruefen(meta)
    if not frei:
        raise SystemExit(f"Nicht frei: {titel} ({lizenz})")
    url = info.get("thumburl") or info["url"]
    if urlparse(url).hostname not in LADE_HOSTS:
        raise SystemExit(f"Unerwartete Adresse {url!r} für {titel}")
    for versuch in range(4):
        r = s.get(url, timeout=120)
        if r.status_code not in WIEDERHOLEN:
            break
        time.sleep(10 * (versuch + 1))
    r.raise_for_status()
    mime = r.headers.get("Content-Type", "").split(";")[0].strip()
    if mime not in ENDUNGEN:
        raise SystemExit(f"Unerwarteter Dateityp {mime!r} für {titel}")
    ziel = naechster_name(ordner, kurzname, ENDUNGEN[mime])
    urheber = ohne_html(meta.get("Artist")) or ohne_html(meta.get("Credit")) or "unbekannt"
    if urheber.lower() in ("unknown author", "unknown", "unbekannt"):
        urheber = "Urheber unbekannt"
    # Bei Logos, Wappen und Siegel steht im Artist-Feld oft die Vorlage oder der Vektorisierer:
    # nachweis_text danach von Hand auf die Einrichtung kürzen, urheber bleibt der API-Text.
    nachweis = f"{art}: {urheber}, {lizenz}, Wikimedia Commons"
    if len(nachweis) > MAX_LAENGE:
        print(f"Hinweis: Nachweis hat {len(nachweis)} Zeichen, vor dem Import auf die Einrichtung kürzen.",
              file=sys.stderr)
    ziel.write_bytes(r.content)
    daten = {
        "datei": ziel.name, "motiv": motiv, "commons_titel": titel, "commons_seite": info["descriptionurl"],
        "urheber": urheber, "lizenz": lizenz, "lizenz_url": meta.get("LicenseUrl", ""),
        "credit": ohne_html(meta.get("Credit"))[:600], "beschreibung": ohne_html(meta.get("ImageDescription"))[:400],
        "aufnahmedatum": datum(meta),
        "original_breite": info["width"], "original_hoehe": info["height"],
        "nachweis_text": nachweis,
        "sha256": hashlib.sha256(r.content).hexdigest(), "geladen_am": date.today().isoformat(),
        "original_url": info["url"], "geladene_url": url,
    }
    breite_hoehe = bildmasse(r.content) or (info.get("thumbwidth") or info["width"],
                                            info.get("thumbheight") or info["height"])
    daten["geladen_breite"], daten["geladen_hoehe"] = breite_hoehe
    ziel.with_suffix(".json").write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    return daten


def filepath_url(titel: str, breite: int = 800) -> str:
    """Einbettbarer Link für die Akte-Karte (Special:FilePath leitet auf die Vorschau um)."""
    name = titel.removeprefix("File:").replace(" ", "_")
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(name, safe='()')}?width={breite}"


def tabelle(ergebnis: list[dict]) -> str:
    """Lesbare Kandidatenliste; [URL>200] markiert Dateinamen, die die Akte-API ablehnt."""
    zeilen = []
    for e in ergebnis:
        zeilen.append(f"\n## {e['name']} ({e['typ']})  {e['qid']}  {e['wikidata']}")
        for k in e["kandidaten"]:
            zeilen.append(f"  {k['lizenz'][:22]:22} {k['breite']:>5}×{k['hoehe']:<5} {k['datum'][:10]:10} "
                          f"{k['herkunft'][:14]:14} {'' if k['url_passt'] else '[URL>200] '}{k['titel']}"
                          f"  | {k['urheber'][:30]}")
    return "\n".join(zeilen)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="befehl", required=True)
    a = sub.add_parser("suchen", help="Kandidaten mit Lizenz und Maßen je Karte")
    a.add_argument("eingabe", type=Path)
    a.add_argument("-o", "--ausgabe", type=Path)
    a.add_argument("--anzahl", type=int, default=8, help="Treffer der Commons-Suche je Karte")
    a.add_argument("--alle", action="store_true", help="auch unfreie Kandidaten ausgeben")
    a.add_argument("--kurz", action="store_true", help="Tabelle statt JSON")
    b = sub.add_parser("laden", help="eine Datei laden und .json daneben schreiben")
    b.add_argument("titel")
    b.add_argument("kurzname")
    b.add_argument("--motiv", required=True)
    b.add_argument("--art", default="Foto", choices=["Foto", "Logo", "Siegel", "Wappen"])
    b.add_argument("--ordner", type=Path, default=ORDNER)
    b.add_argument("--breite", type=int, default=1280)
    args = ap.parse_args()

    if args.befehl == "suchen":
        zwischen = args.ausgabe if args.ausgabe and not args.kurz else None
        ergebnis = suchen(json.loads(args.eingabe.read_text(encoding="utf-8")), args.anzahl, zwischen)
        if not args.alle:
            for e in ergebnis:
                e["kandidaten"] = [k for k in e["kandidaten"] if k["frei"]]
        text = tabelle(ergebnis) if args.kurz else json.dumps(ergebnis, ensure_ascii=False, indent=2)
        args.ausgabe.write_text(text, encoding="utf-8") if args.ausgabe else print(text)
    else:
        d = laden(args.titel, args.kurzname, args.motiv, args.ordner, args.art, args.breite)
        print(f"{d['datei']}  {d['geladen_breite']}×{d['geladen_hoehe']}  {d['nachweis_text']}")
        url = filepath_url(d["commons_titel"])
        print(url)


if __name__ == "__main__":
    main()
