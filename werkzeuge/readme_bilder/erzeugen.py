#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bilder und Animationen der README, alle aus der erfundenen Demo „Freie Stadt Musterhafen“.

Voraussetzung: eine laufende Akte mit Demo (``manage.py akte_demo --neu --oeffentlich``) und ein Redaktionskonto.

    AKTE_WEB=http://127.0.0.1:8080  AKTE_WEB_LOGIN=…  AKTE_WEB_PASSWORT=…     (Konto, nie ins Repo)
    AKTE_TOKEN=…                    nur für ``terminal`` (Werkzeug-Token: manage.py akte_token <konto>)

    python werkzeuge/readme_bilder/erzeugen.py vorbereiten     # Bühnen-Boards und README-Fahrten anlegen
    python werkzeuge/readme_bilder/erzeugen.py standbilder     # exakte Standbilder, Kartenausschnitte, Oberfläche
    python werkzeuge/readme_bilder/erzeugen.py fahrt           # Kamerafahrt der Demo als Einzelbilder
    python werkzeuge/readme_bilder/erzeugen.py live            # Live-Wand: ein Agent legt Karte und Faden an
    python werkzeuge/readme_bilder/erzeugen.py terminal        # Beweiskette und Zitatprüfung im Terminal
    python werkzeuge/readme_bilder/erzeugen.py kompositionen   # Tafeln: Karten, Faden-Arten, Formate, Kacheln
    python werkzeuge/readme_bilder/erzeugen.py kodieren        # WebP und animiertes WebP mit Größengrenzen
    python werkzeuge/readme_bilder/erzeugen.py pruefen         # README: Links, Anker, Alt-Texte, Größen
    python werkzeuge/readme_bilder/erzeugen.py uebernehmen     # fertige Medien nach docs/bilder/readme/

Zwischenstände liegen in ``ausgabe/readme_bilder/`` (nicht im Repo). Der Browser ist das Chromium von Playwright,
dasselbe wie in ``render/``; heruntergeladen wird nichts. Bildschirmfotos haben doppelte Pixeldichte und werden erst
beim Kodieren verkleinert. Der Leck-Prüfer liest keine Pixel: jedes Bild vor dem Übernehmen selbst ansehen.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import time
from html import escape as html_escape
from pathlib import Path
from urllib.parse import unquote, urlencode

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import szenen  # noqa: E402

WURZEL = HIER.parents[1]
AUSGABE = WURZEL / "ausgabe" / "readme_bilder"
ROH = AUSGABE / "roh"
KODIERT = AUSGABE / "kodiert"
ZIEL = WURZEL / "docs" / "bilder" / "readme"
API = "/api/proxy/api/v1/akte"
FORMATE = {"16x9": (1920, 1080), "9x16": (1080, 1920), "1x1": (1080, 1080)}
CHROMIUM = ["--force-color-profile=srgb", "--hide-scrollbars", "--disable-lcd-text", "--font-render-hinting=none"]


def umgebung() -> tuple[str, str, str]:
    basis = os.environ.get("AKTE_WEB", "http://127.0.0.1:8080").rstrip("/")
    if not re.fullmatch(r"http://(127\.0\.0\.1|localhost)(:\d{1,5})?", basis):
        raise SystemExit("AKTE_WEB nur lokal (http://127.0.0.1:<port>).")
    login, passwort = os.environ.get("AKTE_WEB_LOGIN", ""), os.environ.get("AKTE_WEB_PASSWORT", "")
    if not login or not passwort:
        raise SystemExit("AKTE_WEB_LOGIN und AKTE_WEB_PASSWORT setzen (Redaktionskonto, nie ins Repo).")
    return basis, login, passwort


class Sitzung:
    """Ein Browser-Kontext, auf Wunsch angemeldet; API-Aufrufe laufen über denselben Weg wie die Oberfläche."""

    def __init__(self, browser, breite: int = 1920, hoehe: int = 1080, angemeldet: bool = True,
                 bewegung: str = "reduce", dichte: int = 2) -> None:
        self.basis, login, passwort = umgebung()
        self.kontext = browser.new_context(viewport={"width": breite, "height": hoehe}, device_scale_factor=dichte,
                                           locale="de-DE", timezone_id="Europe/Berlin", reduced_motion=bewegung,
                                           color_scheme="dark")
        if angemeldet:
            antwort = self.kontext.request.post(f"{self.basis}/api/auth/login",
                                                data={"login": login, "password": passwort})
            if not antwort.ok:
                raise SystemExit(f"Anmeldung fehlgeschlagen ({antwort.status}).")

    def api(self, methode: str, pfad: str, daten=None, erlaubt=(200, 201, 204)):
        antwort = self.kontext.request.fetch(f"{self.basis}{API}{pfad}", method=methode, data=daten,
                                             headers={"Origin": self.basis})
        if antwort.status not in erlaubt:
            raise SystemExit(f"{methode} {pfad}: {antwort.status} {antwort.text()[:300]}")
        return antwort.json() if antwort.status != 204 and antwort.body() else None

    def seite(self):
        seite = self.kontext.new_page()
        seite.fehler = []
        seite.on("pageerror", lambda e: seite.fehler.append(str(e)))
        return seite

    def schliessen(self) -> None:
        self.kontext.close()


def fahrt_id(sitzung: Sitzung, board: str, titel: str) -> int:
    wahl = [f["id"] for f in sitzung.api("GET", f"/boards/{board}/")["fahrten"] if f["titel"] == titel]
    if len(wahl) != 1:
        raise SystemExit(f"Fahrt „{titel}“ auf {board}: {len(wahl)} Treffer. Erst `vorbereiten` laufen lassen.")
    return wahl[0]


# ─── vorbereiten ────────────────────────────────────────────────────────────────────────────────────────────

def vorbereiten(browser) -> None:
    s = Sitzung(browser)
    try:
        demo = s.api("GET", f"/boards/{szenen.DEMO}/")
        ids = {k["entitaet_detail"]["name"]: k["entitaet"] for k in demo["karten"]}
        for slug, buehne in szenen.BUEHNEN.items():
            buehne_aufbauen(s, ids, slug, buehne["titel"], buehne["karten"])
        for board in {f["board"] for f in szenen.FAHRTEN}:
            for f in s.api("GET", f"/boards/{board}/")["fahrten"]:
                if f["titel"].startswith(szenen.PRAEFIX):
                    s.api("DELETE", f"/boards/{board}/fahrten/{f['id']}/")
        for f in szenen.FAHRTEN:
            s.api("POST", f"/boards/{f['board']}/fahrten/aus-beschreibung/",
                  {"titel": f["titel"], "format": f["format"], "stationen": f["stationen"]})
            print(f"Fahrt {f['titel']} auf {f['board']}")
    finally:
        s.schliessen()


def buehne_aufbauen(s: Sitzung, ids: dict[str, int], slug: str, titel: str, karten: dict) -> None:
    """Ein Board mit Demo-Karten an festen Stellen; gibt es das Board schon, werden nur die Karten gesetzt."""
    if not _gibt_es(s, slug):
        s.api("POST", "/boards/", {"titel": titel, "slug": slug,
                                   "beschreibung": "Bühne für die Bilder der README. Alle Namen sind erfunden."})
    liegt = {k["entitaet"]: k["id"] for k in s.api("GET", f"/boards/{slug}/")["karten"]}
    positionen = []
    for name, (x, y) in karten.items():
        if ids[name] in liegt:
            positionen.append({"art": "karte", "id": liegt[ids[name]], "x": x, "y": y})
        else:
            s.api("POST", f"/boards/{slug}/karten/", {"entitaet": ids[name], "x": x, "y": y})
    if positionen:
        s.api("POST", f"/boards/{slug}/positionen/", positionen)
    print(f"Bühne {slug}: {len(karten)} Karten")


def _gibt_es(s: Sitzung, slug: str) -> bool:
    status = s.kontext.request.get(f"{s.basis}{API}/boards/{slug}/").status
    if status not in (200, 404):
        raise SystemExit(f"Board {slug}: Antwort {status} (angemeldet? Akte erreichbar?)")
    return status == 200


def _versuchen(fehler: list[str], schritt, *args) -> None:
    """Aufräumen läuft weiter, auch wenn ein Schritt scheitert; die Fehler kommen am Ende gesammelt."""
    try:
        schritt(*args)
    except (SystemExit, Exception) as e:  # noqa: BLE001 – Aufräumen darf an keinem Schritt hängen bleiben
        fehler.append(str(e))


# ─── standbilder ────────────────────────────────────────────────────────────────────────────────────────────

def render_seite(s: Sitzung, board: str, fahrt: str, format_: str, look: str, **zusatz: str):
    seite = s.seite()
    q = urlencode({"fahrt": fahrt_id(s, board, fahrt), "format": format_, "halte": 3000, "look": look, **zusatz})
    seite.goto(f"{s.basis}/akte/{board}/render?{q}", wait_until="networkidle", timeout=60000)
    seite.wait_for_function("() => !!window.__akteRender", timeout=60000)
    info = seite.evaluate("() => window.__akteRender.bereit()")
    if info["fehlendeBilder"]:
        raise SystemExit(f"{board}: Bilder nicht geladen: {info['fehlendeBilder'][:3]}")
    return seite, info


# Passt die genannten Karten samt Fadenbeschriftungen ins Fenster. Nur für README-Standbilder: Die Karten bleiben in
# der Detailstufe der Render-Kamera, weil React Flow seinen Zoom aus dem eigenen Zustand liest, nicht aus dem CSS.
EINPASSEN = """([namen, rand]) => {
  const vp = document.querySelector('.react-flow__viewport')
  const lage = (el) => {
    const m = /translate\\(([-\\d.]+)px,\\s*([-\\d.]+)px\\)/.exec(el.style.transform)
    return m ? [Number(m[1]), Number(m[2])] : null
  }
  const teile = [...document.querySelectorAll('.react-flow__node')]
    .filter((n) => namen.some((name) => n.textContent.includes(name)))
  if (teile.length !== namen.length) return `nur ${teile.length} von ${namen.length} Karten gefunden`
  const alt = new DOMMatrixReadOnly(getComputedStyle(vp).transform)
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  const nimm = (x, y, b, h) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x + b); y1 = Math.max(y1, y + h) }
  for (const n of teile) { const [x, y] = lage(n); nimm(x, y, n.offsetWidth, n.offsetHeight) }
  // Beschriftungen der Fäden zwischen den Karten gehören ins Bild (Bildschirm- in Wandkoordinaten umrechnen).
  for (const l of document.querySelectorAll('.react-flow__edgelabel-renderer > *')) {
    const r = l.getBoundingClientRect()
    if (!r.width || getComputedStyle(l).opacity === '0') continue
    const x = (r.left - alt.e) / alt.a, y = (r.top - alt.f) / alt.a
    if (x > x0 - 400 && x < x1 + 400 && y > y0 - 400 && y < y1 + 400) nimm(x, y, r.width / alt.a, r.height / alt.a)
  }
  const W = innerWidth, H = innerHeight
  const z = Math.min(W * (1 - 2 * rand) / (x1 - x0), H * (1 - 2 * rand) / (y1 - y0))
  vp.style.transform = `translate(${W / 2 - z * (x0 + x1) / 2}px, ${H / 2 - z * (y0 + y1) / 2}px) scale(${z})`
  return ''
}"""


def render_standbilder(browser) -> None:
    for sz in szenen.STANDBILDER:
        b, h = sz.get("groesse") or FORMATE[sz["format"]]
        s = Sitzung(browser, b, h)
        try:
            seite, info = render_seite(s, sz["board"], sz["fahrt"], sz["format"], sz["look"])
            station = info["stationen"][sz.get("station", 0)]
            zeit = station["ankunft"] + 200 if sz.get("zeitpunkt") == "ankunft" else station["standbild"]
            seite.evaluate("ms => window.__akteRender.setzeZeit(ms)", zeit)
            if sz.get("rahmen"):
                fehler = seite.evaluate(EINPASSEN, [sz["rahmen"], 0.05])
                if fehler:
                    raise SystemExit(f"{sz['name']}: {fehler}")
                seite.wait_for_timeout(300)
            seite.screenshot(path=str(ROH / f"{sz['name']}.png"))
            _fehler_melden(seite, sz["name"])
        finally:
            s.schliessen()
        print("Standbild", sz["name"])


def kartenausschnitte(browser) -> None:
    """Jede Galerie-Karte allein im Fokus, ausgeschnitten mit etwas Rand (Nadel und Schatten bleiben dran)."""
    s = Sitzung(browser)
    try:
        seite, info = render_seite(s, "readme-karten", szenen.PRAEFIX + "Karten", "16x9", "dunkel")
        for i, (name, _, _) in enumerate(szenen.GALERIE):
            seite.evaluate("ms => window.__akteRender.setzeZeit(ms)", info["stationen"][i]["standbild"])
            box = seite.locator(".react-flow__node").filter(has_text=name).first.bounding_box()
            if not box:
                raise SystemExit(f"Karte „{name}“ ist nicht zu sehen.")
            rand = 0.12 * box["width"]
            seite.screenshot(path=str(ROH / f"karte-{i}.png"), clip={
                "x": box["x"] - rand, "y": box["y"] - rand, "width": box["width"] + 2 * rand,
                "height": box["height"] + 2 * rand})
            print("Karte", name)
        _fehler_melden(seite, "karten")
    finally:
        s.schliessen()


def _fehler_melden(seite, name: str) -> None:
    if seite.fehler:
        print(f"Warnung {name}: {' | '.join(seite.fehler[:3])}", file=sys.stderr)


# ─── Oberfläche (1440 × 900, doppelte Pixeldichte) ──────────────────────────────────────────────────────────

def wand_seite(s: Sitzung, board: str, karte: str = ""):
    """Die Wand wie im Browser; ``karte`` (Kurzname) fährt auf eine Karte und öffnet ihre Notiz."""
    seite = s.seite()
    seite.goto(f"{s.basis}/akte/{board}" + (f"?karte={karte}" if karte else ""), wait_until="networkidle",
               timeout=60000)
    seite.wait_for_selector(".react-flow__node", timeout=60000)
    seite.wait_for_timeout(1500)
    return seite


def foto(seite, name: str) -> None:
    seite.wait_for_load_state("networkidle")
    seite.wait_for_timeout(500)
    seite.screenshot(path=str(ROH / f"{name}.png"))
    _fehler_melden(seite, name)
    print("Oberfläche", name)


# Beim Unterschrift-Dialog darf der Browser nur zwei Dinge schreiben: seinen Schlüssel anmelden (beim ersten Mal) und
# die Freigabe vorbereiten (das ergibt die Bytes, die der Dialog zeigt). Alles andere wird abgebrochen.
ERLAUBT_BEIM_DIALOG = re.compile(r"/api/v1/akte/beweis/(schluessel|freigabe/vorbereiten)/(\?.*)?$")
FADEN_SPEICHERN = re.compile(r"/api/v1/akte/verbindungen/\d+/?(\?.*)?$")


def unterschrift_zeigen(s: Sitzung, name: str, karte: str, nach: str) -> None:
    """Faden öffnen, „Freigeben (unterschreiben)“ wählen, Dialog fotografieren, abbrechen: es wird nichts signiert,
    und Karten, Fäden und Belege bleiben, wie sie sind."""
    seite = wand_seite(s, szenen.DEMO, karte)
    abgefangen: list[str] = []

    def nur_lesen(route) -> None:
        anfrage = route.request
        if anfrage.method in ("GET", "HEAD", "OPTIONS") or ERLAUBT_BEIM_DIALOG.search(anfrage.url):
            route.continue_()
        elif anfrage.method in ("PATCH", "PUT") and FADEN_SPEICHERN.search(anfrage.url):
            # Das Formular speichert vor dem Dialog; die Antwort kommt hier vom unveränderten Faden.
            abgefangen.append(anfrage.url)
            route.fulfill(response=route.fetch(method="GET", post_data=""))
        else:
            route.abort()

    seite.route("**/api/proxy/**", nur_lesen)
    seite.get_by_role("button", name=re.compile(rf"^→ {re.escape(nach)}")).first.click()
    seite.locator("select:has(option[value=freigegeben])").select_option("freigegeben")
    seite.get_by_role("button", name=re.compile("speichern|unterschreiben", re.IGNORECASE)).last.click()
    dialog = seite.locator("[aria-labelledby=unterschrift-titel]")
    dialog.wait_for(timeout=20000)
    if not abgefangen:
        raise SystemExit(f"{name}: Das Speichern des Fadens wurde nicht abgefangen; Bild verworfen.")
    foto(seite, name)
    dialog.get_by_role("button", name="Abbrechen").last.click()
    seite.wait_for_timeout(800)


# Klickt „Groß zeigen“ am Beleg aus der genannten Quelle (kleinster Block, der genau einen solchen Knopf hat).
GROSS_ZEIGEN = """(quelle) => {
  for (const knopf of document.querySelectorAll('button')) {
    if (!knopf.innerText.includes('Groß zeigen')) continue
    for (let p = knopf.parentElement; p; p = p.parentElement) {
      const knoepfe = [...p.querySelectorAll('button')].filter((b) => b.innerText.includes('Groß zeigen'))
      if (knoepfe.length > 1) break
      if (p.innerText.includes(quelle)) { knopf.click(); return true }
    }
  }
  return false
}"""


def buehnen_abbauen(browser) -> None:
    """Bühnen und README-Fahrten wieder entfernen: In der Oberfläche stünden sie sonst unter „Kommt vor in“."""
    s = Sitzung(browser)
    fehler: list[str] = []
    try:
        for slug in [*szenen.BUEHNEN, szenen.LIVE["board"]]:
            _versuchen(fehler, lambda sl: _gibt_es(s, sl) and s.api("DELETE", f"/boards/{sl}/"), slug)
        for f in s.api("GET", f"/boards/{szenen.DEMO}/")["fahrten"]:
            if f["titel"].startswith(szenen.PRAEFIX):
                _versuchen(fehler, s.api, "DELETE", f"/boards/{szenen.DEMO}/fahrten/{f['id']}/")
    finally:
        s.schliessen()
    if fehler:
        raise SystemExit("Aufräumen unvollständig: " + " | ".join(fehler))


def oberflaeche(browser) -> None:
    s = Sitzung(browser, 1440, 900)
    try:
        seite = wand_seite(s, szenen.DEMO)
        seite.get_by_role("button", name="Regeln", exact=True).click()
        seite.get_by_role("dialog").first.wait_for()
        foto(seite, "regeln")

        unterschrift_zeigen(s, "unterschrift", "kranich-holding-ag", szenen.KAMERAS)
        unterschrift_zeigen(s, "gesperrt", "thea-beispiel", szenen.MAX)

        seite = wand_seite(s, szenen.DEMO, "senat-der-freien-stadt-musterhafen")
        if not seite.evaluate(GROSS_ZEIGEN, szenen.BELEG_QUELLE):
            raise SystemExit(f"Kein Beleg aus „{szenen.BELEG_QUELLE}“ in der Notiz des Senats.")
        seite.locator("[role=dialog][aria-modal=true]").first.wait_for()
        foto(seite, "beleg")

        foto(wand_seite(s, szenen.DEMO, "erika-mustermann"), "siegel")
    finally:
        s.schliessen()
    leser = Sitzung(browser, 1440, 900, angemeldet=False)
    try:
        foto(wand_seite(leser, szenen.DEMO, "max-mustermann"), "leseansicht")
    finally:
        leser.schliessen()


def standbilder(browser) -> None:
    try:
        vorbereiten(browser)
        render_standbilder(browser)
        kartenausschnitte(browser)
    finally:
        buehnen_abbauen(browser)  # auch nach einem Fehler: die Bühnen stünden sonst unter „Kommt vor in“
    oberflaeche(browser)


# ─── Animationen ────────────────────────────────────────────────────────────────────────────────────────────

FPS = 12


def _ordner_leeren(ordner: Path) -> Path:
    ordner.mkdir(parents=True, exist_ok=True)
    for alt in ordner.glob("*.png"):
        alt.unlink()
    return ordner


def fahrt(browser) -> None:
    """Die Kamerafahrt der Demo, Bild für Bild (12 je Sekunde) aus der Render-Ansicht, mit Stichworten."""
    ziel = _ordner_leeren(AUSGABE / "fahrt")
    s = Sitzung(browser, 1920, 1080, dichte=1)
    try:
        seite, info = render_seite(s, szenen.DEMO, szenen.DEMO_FAHRT, "16x9", "dunkel", stichworte="1")
        bilder = math.ceil(info["dauerMs"] / 1000 * FPS)
        for k in range(bilder):
            seite.evaluate("ms => window.__akteRender.setzeZeit(ms)", k * 1000 / FPS)
            seite.screenshot(path=str(ziel / f"{k:05d}.png"))
        seite.evaluate("ms => window.__akteRender.setzeZeit(ms)", info["stationen"][1]["standbild"])
        seite.screenshot(path=str(ROH / "fahrt-standbild.png"))
        _fehler_melden(seite, "fahrt")
    finally:
        s.schliessen()
    print(f"Fahrt: {bilder} Bilder")


def _quelle_id(s: Sitzung, titel: str) -> int:
    for v in _verbindungen(s):
        for b in v["belege"]:
            if (b.get("quelle_detail") or {}).get("titel", "").startswith(titel):
                return b["quelle"]
    raise SystemExit(f"Keine Quelle „{titel}“ in der Demo.")


def _verbindungen(s: Sitzung) -> list[dict]:
    antwort = s.api("GET", "/verbindungen/")
    return antwort["results"] if isinstance(antwort, dict) else antwort


# Setzt den Ausschnitt der Wand auf ein Rechteck in Wandkoordinaten, unterhalb der Kopfleiste. Die Wand zeichnet alle
# Karten (auch außerhalb des Fensters), und React Flow setzt die Transformation nur neu, wenn sich sein Zoom ändert.
RECHTECK = """([x0, y0, x1, y1]) => {
  const vp = document.querySelector('.react-flow__viewport')
  const knopf = [...document.querySelectorAll('button')].find((b) => b.innerText.trim() === 'Abmelden')
  const oben = (knopf ? knopf.getBoundingClientRect().bottom : 110) + 18, unten = innerHeight - 46
  const z = Math.min(innerWidth / (x1 - x0), (unten - oben) / (y1 - y0))
  const tx = innerWidth / 2 - z * (x0 + x1) / 2, ty = (oben + unten) / 2 - z * (y0 + y1) / 2
  vp.style.transform = `translate(${tx}px, ${ty}px) scale(${z})`
}"""


def live(browser) -> None:
    """Ein Agent legt eine Karte und einen belegten Faden an; die offene Wand nimmt beides ohne Neuladen auf.

    Aufgenommen wird in Echtzeit, denn die Wand fragt alle 4 s nach. Danach räumt das Werkzeug alles wieder ab.
    """
    ld = szenen.LIVE
    ziel = _ordner_leeren(AUSGABE / "live")
    s = Sitzung(browser, 1280, 720, dichte=1, bewegung="no-preference")
    angelegt: dict[str, int] = {}
    try:
        demo = s.api("GET", f"/boards/{szenen.DEMO}/")
        ids = {k["entitaet_detail"]["name"]: k["entitaet"] for k in demo["karten"]}
        quelle = _quelle_id(s, ld["faden"]["quelle"])
        _live_reste_entfernen(s)
        buehne_aufbauen(s, ids, ld["board"], ld["titel"], ld["karten"])
        seite = wand_seite(s, ld["board"])
        seite.evaluate(RECHTECK, list(ld["ausschnitt"]))
        seite.wait_for_timeout(800)

        def karte_anlegen() -> None:
            k = ld["karte"]
            e = s.api("POST", "/entitaeten/", {"name": k["name"], "typ": k["typ"], "kurzbeschreibung": k["kurz"]})
            angelegt["entitaet"] = e["id"]
            s.api("POST", f"/boards/{ld['board']}/karten/", {"entitaet": e["id"], "x": k["x"], "y": k["y"]})

        def faden_anlegen() -> None:
            f = ld["faden"]
            angelegt["faden"] = s.api("POST", "/verbindungen/", {
                "von": angelegt["entitaet"], "nach": ids[f["nach"]], "typ": f["typ"], "beschreibung": f["text"],
                "start": f["start"], "aktuell": False, "aussageart": "belegt",
                "belege": [{"quelle": quelle, "zitat_woertlich": f["zitat"], "fundstelle": f["fundstelle"]}]})["id"]

        schritte = [(ld["schritte_s"][0], karte_anlegen), (ld["schritte_s"][1], faden_anlegen)]
        t0, k = time.monotonic(), 0
        while (jetzt := time.monotonic() - t0) < ld["dauer_s"]:
            if schritte and jetzt >= schritte[0][0]:
                schritte.pop(0)[1]()
            seite.screenshot(path=str(ziel / f"{k:05d}.png"))
            k += 1
            seite.wait_for_timeout(max(0, int((t0 + k / FPS - time.monotonic()) * 1000)))
        (ziel / "fps.txt").write_text(f"{k / (time.monotonic() - t0):.3f}", encoding="utf-8")
        seite.screenshot(path=str(ROH / "live-standbild.png"))
        _fehler_melden(seite, "live")
        print(f"Live: {k} Bilder")
    finally:
        fehler: list[str] = []
        if "faden" in angelegt:
            _versuchen(fehler, s.api, "DELETE", f"/verbindungen/{angelegt['faden']}/")
        if "entitaet" in angelegt:
            _versuchen(fehler, s.api, "DELETE", f"/entitaeten/{angelegt['entitaet']}/")
        _versuchen(fehler, lambda: _gibt_es(s, ld["board"]) and s.api("DELETE", f"/boards/{ld['board']}/"))
        s.schliessen()
        if fehler:
            print("Aufräumen unvollständig: " + " | ".join(fehler), file=sys.stderr)


def _live_reste_entfernen(s: Sitzung) -> None:
    """Nach einem harten Abbruch können Karte, Faden und Bühne der Live-Szene liegen geblieben sein."""
    name = szenen.LIVE["karte"]["name"]
    for v in _verbindungen(s):
        if name in ((v.get("von_detail") or {}).get("name", ""), (v.get("nach_detail") or {}).get("name", "")):
            s.api("DELETE", f"/verbindungen/{v['id']}/")
    antwort = s.api("GET", "/entitaeten/")
    for e in antwort["results"] if isinstance(antwort, dict) else antwort:
        if e["name"] == name:
            s.api("DELETE", f"/entitaeten/{e['id']}/")
    if _gibt_es(s, szenen.LIVE["board"]):
        s.api("DELETE", f"/boards/{szenen.LIVE['board']}/")


# Eine Ebene über einer Seite der Akte: Sie erbt deren Schriften (Anton, Inter, IBM Plex Mono). Eigene Dateien
# liefert das Werkzeug unter /__readme/<name> aus ROH aus.
LEINWAND = """([html, hintergrund]) => {
  const alt = document.getElementById('readme-leinwand'); if (alt) alt.remove()
  const d = document.createElement('div')
  d.id = 'readme-leinwand'
  d.style.cssText = `position:fixed;inset:0;z-index:2147483647;background:${hintergrund};overflow:hidden`
  d.innerHTML = html
  document.getElementById('akte-wurzel').appendChild(d)
  const bilder = [...d.querySelectorAll('img')]
  return document.fonts.ready
    .then(() => Promise.all(bilder.map((i) => i.decode().catch(() => null))))
    .then(() => bilder.filter((i) => !i.naturalWidth).map((i) => i.getAttribute('src')))
}"""


def _readme_datei(route) -> None:
    name = Path(route.request.url.split("?")[0]).name
    datei = ROH / name
    if re.fullmatch(r"[\w.-]+\.png", name) and datei.is_file():
        route.fulfill(path=str(datei))
    else:
        route.fulfill(status=404, body="")


def leinwand(s: Sitzung):
    seite = s.seite()
    seite.route("**/__readme/**", _readme_datei)
    seite.goto(f"{s.basis}/akte", wait_until="networkidle", timeout=60000)
    seite.wait_for_selector("#akte-wurzel")
    return seite


def zeichnen(seite, html: str, hintergrund: str = "#0A0A0F", warten_ms: int = 150) -> None:
    leer = seite.evaluate(LEINWAND, [html, hintergrund])
    if leer:
        raise SystemExit(f"Bilder nicht geladen: {', '.join(leer)} (erst `standbilder` laufen lassen)")
    seite.wait_for_timeout(warten_ms)


TERMINAL_CSS = """
<style>
#t { position:absolute; inset:28px; border:1px solid #232635; border-radius:6px; background:#0d0e14;
     display:flex; flex-direction:column; overflow:hidden; box-shadow:0 18px 40px rgba(0,0,0,.6) }
#t header { display:flex; align-items:center; gap:8px; padding:10px 14px; border-bottom:1px solid #232635;
     font:600 12px/1 var(--font-akte-mono); letter-spacing:.16em; text-transform:uppercase; color:#8A94A0 }
#t header i { width:10px; height:10px; background:#232635; transform:rotate(45deg) }
#t .flaeche { flex:1; display:flex; flex-direction:column; justify-content:flex-end; padding:18px 22px; overflow:hidden }
#t pre { margin:0; font:400 17px/1.5 var(--font-akte-mono); color:#F2F7FB; white-space:pre-wrap; word-break:break-word }
.p { color:#FF1744 } .ok { color:#f0c674 } .gut { color:#F2F7FB; font-weight:600 } .nein { color:#FF1744; font-weight:600 }
.leise { color:#8A94A0 } .cursor { background:#F2F7FB; color:#0d0e14 }
</style>"""


def _farbig(zeile: str) -> str:
    """Eine Zeile der CLI-Ausgabe, eingefärbt wie in der App (geprüft wird am Rohtext, ausgegeben escaped)."""
    z = html_escape(zeile)
    roh = zeile.strip()
    if roh.startswith("✓"):
        return f'<span class="ok">{z}</span>'
    if roh.startswith("GÜLTIG") or '"gefunden"' in roh:
        return f'<span class="gut">{z}</span>'
    if "nicht_gefunden" in roh or roh.startswith("UNGÜLTIG"):
        return f'<span class="nein">{z}</span>'
    if roh.startswith(('"grund"', '"naechster_schritt"')):
        return z
    return f'<span class="leise">{z}</span>'


# Was der CLI-Prozess von der Umgebung sieht: das Nötige, nicht das Passwort des Browser-Kontos.
CLI_UMGEBUNG = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                "AKTE_TOKEN")


TERMINAL_ZEILEN = 26  # so viele Zeilen passen in das Fenster
PAUSE_S = 2.2         # Pause nach jeder Ausgabe


def terminal(browser) -> None:
    """Echte Ausgaben der Kommandozeile `akte`, im Look der App getippt: Beweiskette (auch mit dem Atlas-Prüfer),
    dann die Zitatprüfung, einmal gefunden und einmal nicht."""
    token = os.environ.get("AKTE_TOKEN", "")
    if not token:
        raise SystemExit("AKTE_TOKEN setzen (Werkzeug-Token: manage.py akte_token <konto>).")
    ziel = _ordner_leeren(AUSGABE / "terminal")
    s = Sitzung(browser, 1280, 760, dichte=1)
    try:
        belege = {b["zitat_woertlich"]: b["id"] for v in _verbindungen(s) for b in v["belege"]}
        befehle = [["pruefe-signaturen", "--atlas"]] + [["zitat-pruefen", str(belege[z])] for z in szenen.TERMINAL_ZITATE]
        python = os.environ.get("AKTE_PYTHON", sys.executable)
        umg = {k: v for k, v in os.environ.items() if k.upper() in CLI_UMGEBUNG}
        umg |= {"AKTE_BASIS": s.basis, "PYTHONPATH": str(WURZEL / "mcp" / "src"), "PYTHONIOENCODING": "utf-8"}
        geheim = [token, token[:8], token[-8:], os.environ.get("AKTE_WEB_PASSWORT", "")]
        bloecke = []
        for befehl in befehle:
            lauf = subprocess.run([python, "-m", "akte_client.cli", *befehl], capture_output=True, text=True,
                                  encoding="utf-8", env=umg, timeout=120)
            text = lauf.stdout + lauf.stderr
            if any(g and g in text for g in geheim):
                raise SystemExit("Token oder Passwort stünden in der Ausgabe – abgebrochen.")
            if "Traceback" in text or not lauf.stdout.strip():
                raise SystemExit(f"akte {' '.join(befehl)} lief nicht sauber (Rückgabe {lauf.returncode}).")
            bloecke.append(("akte " + " ".join(befehl), text.rstrip("\n").splitlines()))
        # Zeitplan: tippen (2 Zeichen je Bild), Ausgabe Zeile für Zeile, dann Pause.
        bilder: list[list[str]] = []
        fertig: list[str] = []
        for befehl, ausgabe in bloecke:
            for n in range(0, len(befehl) + 1, 2):
                bilder.append(fertig + [f'<span class="p">$</span> {html_escape(befehl[:n])}<span class="cursor"> </span>'])
            bilder += [fertig + [f'<span class="p">$</span> {html_escape(befehl)}']] * 4
            fertig = fertig + [f'<span class="p">$</span> {html_escape(befehl)}']
            for zeile in ausgabe:
                fertig = fertig + [_farbig(zeile)]
                bilder.append(list(fertig))
            fertig = fertig + [""]
            bilder += [fertig + ['<span class="p">$</span> <span class="cursor"> </span>']] * int(PAUSE_S * FPS)
        bilder += [bilder[-1]] * FPS
        seite = leinwand(s)
        for k, zeilen in enumerate(bilder):
            zeichnen(seite, TERMINAL_CSS + '<div id="t"><header><i></i><i></i><i></i>&nbsp;akte · Terminal</header>'
                     '<div class="flaeche"><pre>' + "\n".join(zeilen[-TERMINAL_ZEILEN:]) + '</pre></div></div>',
                     warten_ms=30)
            seite.screenshot(path=str(ziel / f"{k:05d}.png"))
        seite.screenshot(path=str(ROH / "terminal-standbild.png"))
        print(f"Terminal: {len(bilder)} Bilder")
    finally:
        s.schliessen()


# ─── Tafeln ────────────────────────────────────────────────────────────────────────────────────────────────

TAFEL_CSS = """
<style>
#tafel { position:absolute; inset:0; padding:56px 64px; display:grid; gap:36px; align-content:start; color:#F2F7FB;
     font-family:var(--font-akte-text) }
.etikett { font:600 13px/1.3 var(--font-akte-mono); letter-spacing:.18em; text-transform:uppercase; color:#8A94A0 }
.titel { font:400 30px/1.05 var(--font-akte-titel); text-transform:uppercase; color:#F2F7FB }
.reihe { display:flex; gap:28px; justify-content:center; align-items:flex-start }
figure { margin:0; display:grid; gap:12px; justify-items:center; align-content:start }
figcaption { display:grid; gap:4px; text-align:center; max-width:300px }
figcaption b { font:600 13px/1.3 var(--font-akte-mono); letter-spacing:.16em; text-transform:uppercase; color:#FF1744 }
figcaption span { font-size:17px; color:#c9d1d9 }
img { display:block; max-width:none }  /* die App begrenzt Bilder sonst auf die Kachelbreite */
</style>"""


def _tafel(s: Sitzung, name: str, html: str, breite: int, hoehe: int) -> None:
    seite = leinwand(s)
    seite.set_viewport_size({"width": breite, "height": hoehe})
    zeichnen(seite, TAFEL_CSS + f'<div id="tafel">{html}</div>')
    seite.screenshot(path=str(ROH / f"{name}.png"))
    seite.close()
    print("Tafel", name)


def kompositionen(browser) -> None:
    s = Sitzung(browser, 1660, 1000)
    try:
        karten = [f'<figure><img src="/__readme/karte-{i}.png" style="width:300px">'
                  f'<figcaption><b>{art}</b><span>{text}</span></figcaption></figure>'
                  for i, (_, art, text) in enumerate(szenen.GALERIE)]
        _tafel(s, "kartengalerie", f'<div class="reihe">{"".join(karten[:4])}</div>'
                                   f'<div class="reihe">{"".join(karten[4:])}</div>', 1660, 1180)

        def faden(art: str, strich: str, breite: float, farbe: str, stempel: str) -> str:
            marke = (f'<text x="230" y="58" text-anchor="middle" font-family="var(--font-akte-mono)" font-weight="600" '
                     f'font-size="15" letter-spacing="3" fill="{farbe}">{stempel}</text>'
                     f'<rect x="{230 - 12 * len(stempel) / 2 - 22}" y="38" width="{12 * len(stempel) + 44}" height="30" '
                     f'fill="none" stroke="{farbe}" stroke-width="2.5"/>') if stempel else ""
            return (f'<svg width="460" height="150" viewBox="0 0 460 150"><path d="M40 100 Q230 150 420 100" fill="none" '
                    f'stroke="{farbe}" stroke-width="{breite}" stroke-dasharray="{strich}" stroke-linecap="round"/>'
                    f'<circle cx="40" cy="100" r="9" fill="#FF1744"/><circle cx="420" cy="100" r="9" fill="#FF1744"/>{marke}</svg>')

        spalten = "".join(
            f'<figure>{faden(*stil)}<figcaption style="max-width:420px"><span class="titel">{titel}</span>'
            f'<span>{text}</span></figcaption></figure>'
            for titel, stil, text in szenen.FADEN_ARTEN)
        _tafel(s, "faden-arten", f'<div class="reihe" style="gap:40px">{spalten}</div>', 1660, 400)

        formate = "".join(
            f'<figure><img src="/__readme/format-{f}.png" style="height:440px"><figcaption><b>{f.replace("x", ":")}</b>'
            f'<span>{wofuer}</span></figcaption></figure>' for f, wofuer in szenen.FORMATE_TEXT)
        _tafel(s, "formate", f'<div class="reihe" style="align-items:flex-end">{formate}</div>', 1660, 640)

        kacheln = "".join(
            f'<figure style="gap:16px"><div style="width:480px;height:340px;overflow:hidden;border:1px solid #232635;'
            f'background:#0A0A0F"><img src="/__readme/{datei}.png" style="width:{breite}px;margin:{-oben}px 0 0 {-links}px">'
            f'</div><figcaption style="max-width:440px"><b>{titel}</b><span>{text}</span></figcaption></figure>'
            for titel, datei, breite, links, oben, text in szenen.KACHELN)
        _tafel(s, "kacheln", f'<div class="reihe">{kacheln}</div>', 1660, 560)
    finally:
        s.schliessen()


# ─── kodieren, pruefen, uebernehmen ─────────────────────────────────────────────────────────────────────────

def _webp(quelle: Path, ziel: Path, breite: int, max_kb: int) -> None:
    from PIL import Image

    with Image.open(quelle) as roh:
        bild = roh.convert("RGB")
    if bild.width > breite:
        bild = bild.resize((breite, round(bild.height * breite / bild.width)), Image.Resampling.LANCZOS)
    for q in (86, 82, 78, 74, 70, 65, 60, 55):
        bild.save(ziel, "WEBP", quality=q, method=6)  # ohne EXIF und ICC: Pillow schreibt nur, was man übergibt
        if ziel.stat().st_size <= max_kb * 1024:
            return
    ziel.unlink(missing_ok=True)  # sonst übernähme `uebernehmen` die zu große Datei
    raise SystemExit(f"{ziel.name}: auch mit Qualität 55 über {max_kb} KB")


def _animiert(ordner: Path, ziel: Path, breite: int, max_kb: int, fps: float) -> None:
    ffmpeg = shutil.which(os.environ.get("FFMPEG", "ffmpeg"))
    if not ffmpeg:
        raise SystemExit("ffmpeg nicht gefunden (PATH oder FFMPEG=…); es braucht den Encoder libwebp_anim.")
    for q in (70, 60, 50, 40, 32):
        lauf = subprocess.run([ffmpeg, "-v", "error", "-y", "-framerate", f"{fps:.3f}", "-i", str(ordner / "%05d.png"),
                               "-vf", f"scale={breite}:-2:flags=lanczos", "-c:v", "libwebp_anim", "-loop", "0",
                               "-q:v", str(q), "-compression_level", "6", "-map_metadata", "-1", str(ziel)],
                              capture_output=True, text=True, timeout=900)
        if lauf.returncode != 0:
            ziel.unlink(missing_ok=True)
            raise SystemExit(f"ffmpeg ({ziel.name}): {lauf.stderr[-400:]}")
        if ziel.stat().st_size <= max_kb * 1024:
            return
    ziel.unlink(missing_ok=True)
    raise SystemExit(f"{ziel.name}: auch mit Qualität 32 über {max_kb} KB")


def kodieren(_browser=None) -> None:
    KODIERT.mkdir(parents=True, exist_ok=True)
    for name, (breite, max_kb) in szenen.MEDIEN.items():
        ziel = KODIERT / name
        stamm = name.removesuffix(".webp")
        ordner = AUSGABE / stamm
        if (ordner / "00000.png").exists() and not stamm.endswith("-standbild"):
            fps_datei = ordner / "fps.txt"
            fps = float(fps_datei.read_text(encoding="utf-8")) if fps_datei.exists() else FPS
            _animiert(ordner, ziel, breite, max_kb, fps)
        elif (ROH / f"{stamm}.png").exists():
            _webp(ROH / f"{stamm}.png", ziel, breite, max_kb)
        else:
            print(f"fehlt noch: {name}", file=sys.stderr)
            continue
        print(f"{name}: {ziel.stat().st_size // 1024} KB")
    for name in szenen.MARKEN:
        shutil.copyfile(HIER / "marken" / name, KODIERT / name)


def _slug(ueberschrift: str) -> str:
    """Anker wie bei GitHub: klein, Satzzeichen weg (Umlaute bleiben), Leerzeichen zu Bindestrichen."""
    text = re.sub(r"\s+#+\s*$", "", ueberschrift)               # schließende # einer Überschrift
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)      # von Links zählt nur der Text
    text = re.sub(r"<[^>]+>|`", "", text).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _ohne_code(text: str) -> str:
    """Codeblöcke (``` und ~~~, auch länger) und Inline-Code entfernen; ein offener Block reicht bis zum Ende."""
    zeilen, zaun = [], ""
    for zeile in text.splitlines():
        m = re.match(r" {0,3}(`{3,}|~{3,})", zeile)
        if zaun:
            if m and m.group(1)[0] == zaun[0] and len(m.group(1)) >= len(zaun) and not zeile.strip(" `~"):
                zaun = ""
            zeilen.append("")
        elif m:
            zaun = m.group(1)
            zeilen.append("")
        else:
            zeilen.append(re.sub(r"(`+)[^`\n]*?\1", "", zeile))
    return "\n".join(zeilen)


def _ziele(text: str) -> list[str]:
    """Link- und Bildziele aus Markdown und HTML, auch das äußere Ziel bei [![Bild](a)](b) und jede srcset-Quelle."""
    ziele = re.findall(r"\]\(([^)\s]+)", text)
    for wert in re.findall(r"""\b(?:src|href)=["']([^"']+)["']""", text):
        ziele.append(wert)
    for wert in re.findall(r"""\bsrcset=["']([^"']+)["']""", text):
        ziele += [teil.strip().split()[0] for teil in wert.split(",") if teil.strip()]
    return ziele


def readme_pruefen(datei: Path, medien: Path) -> list[str]:
    """Links, Bilder, Anker, Alt-Texte und Größen einer README. Gibt Befunde als Sätze zurück."""
    befunde: list[str] = []
    text = datei.read_text(encoding="utf-8")
    if len(text.encode()) > 500 * 1024:
        befunde.append(f"{datei.name} ist größer als 500 KiB; GitHub schneidet ab.")
    ohne_code = _ohne_code(text)
    anker: dict[str, int] = {}
    for zeile in ohne_code.splitlines():
        if m := re.match(r" {0,3}#{1,6}\s+(.*)", zeile):
            s = _slug(m.group(1))
            anker[s] = anker.get(s, -1) + 1
    # GitHub: erste Überschrift ohne Nummer, jede weitere gleiche mit -1, -2, …
    vorhanden = set(anker) | {f"{s}-{i}" for s, n in anker.items() for i in range(1, n + 1)}
    for z in _ziele(ohne_code):
        if z.startswith(("http://", "https://", "mailto:")):
            continue
        pfad, _, frag = unquote(z.split("?")[0]).partition("#")
        if pfad:
            if "/v0." in pfad:
                befunde.append(f"Versionsnummer im Pfad {z}")
            if not (datei.parent / pfad).exists() and not (pfad.startswith("docs/bilder/readme/") and
                                                           (medien / Path(pfad).name).exists()):
                befunde.append(f"Ziel fehlt: {z}")
        elif frag and frag not in vorhanden:
            befunde.append(f"Anker fehlt: #{frag}")
    for alt in re.findall(r"!\[([^\]]*)\]\(", ohne_code) + re.findall(r'<img[^>]*?\salt="([^"]*)"', ohne_code):
        if len(alt.strip()) < 12:
            befunde.append(f"Alt-Text zu kurz: „{alt}“")
    for tag in re.findall(r"<img(?![^>]*\salt=)[^>]*>", ohne_code):
        befunde.append(f"Bild ohne Alt-Text: {tag[:80]}")
    return befunde


def pruefen(_browser=None) -> None:
    befunde: list[str] = []
    medien = ZIEL if any(ZIEL.glob("*.webp")) else KODIERT
    gesamt = 0
    for name, (_, max_kb) in szenen.MEDIEN.items():
        datei = medien / name
        if not datei.exists():
            befunde.append(f"fehlt: {name}")
            continue
        kb = datei.stat().st_size / 1024
        gesamt += kb
        if kb > max_kb:
            befunde.append(f"{name}: {kb:.0f} KB > {max_kb} KB")
    for a, b in szenen.PAARE:
        if (medien / a).exists() and (medien / b).exists():
            if ((medien / a).stat().st_size + (medien / b).stat().st_size) / 1024 > 500:
                befunde.append(f"{a} + {b} zusammen über 500 KB")
    if gesamt > szenen.GESAMT_KB:
        befunde.append(f"alle Medien zusammen {gesamt / 1024:.1f} MB > {szenen.GESAMT_KB // 1024} MB")
    for readme in ("README.md", "README.en.md"):
        befunde += [f"{readme}: {b}" for b in readme_pruefen(WURZEL / readme, medien)]
    for b in befunde:
        print("✗", b)
    print(f"{len(befunde)} Befund(e); Medien {gesamt / 1024:.1f} MB")
    if befunde:
        raise SystemExit(1)


def uebernehmen(_browser=None) -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    namen = [*szenen.MEDIEN, *szenen.MARKEN]
    fehlen = [n for n in namen if not (KODIERT / n).exists()]
    if fehlen:
        raise SystemExit(f"Erst kodieren, es fehlen: {', '.join(fehlen)}")
    for n in namen:
        shutil.copyfile(KODIERT / n, ZIEL / n)
    print(f"{len(namen)} Dateien nach {ZIEL.relative_to(WURZEL)}")


# ─── Aufruf ────────────────────────────────────────────────────────────────────────────────────────────────

BEFEHLE = {"vorbereiten": vorbereiten, "standbilder": standbilder, "fahrt": fahrt, "live": live, "terminal": terminal,
           "kompositionen": kompositionen, "kodieren": kodieren, "pruefen": pruefen, "uebernehmen": uebernehmen}
OHNE_BROWSER = {"kodieren", "pruefen", "uebernehmen"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("befehl", choices=list(BEFEHLE))
    a = p.parse_args(argv)
    for strom in (sys.stdout, sys.stderr):
        if hasattr(strom, "reconfigure"):
            strom.reconfigure(encoding="utf-8", errors="replace")  # ✗ und Umlaute auch in umgeleiteter Ausgabe
    for ordner in (ROH, KODIERT):
        ordner.mkdir(parents=True, exist_ok=True)
    if a.befehl in OHNE_BROWSER:
        BEFEHLE[a.befehl]()
        return 0
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=CHROMIUM)
        try:
            BEFEHLE[a.befehl](browser)
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
