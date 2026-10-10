"""Seiten fotografieren und Fundstellen markieren.

* ``seite_rendern``: ganzseitiges Bild (JPEG) und PDF einer Webseite, so wie sie am Tag
  der Sicherung aussah. Läuft im Sicherungs-Worker mit Chromium (Playwright).
* ``fundstelle_html``: das Zitat auf der Seite suchen, gelb markieren und den Ausschnitt
  darum fotografieren — das Bild für die Beweis-Ansicht im Video.
* ``fundstelle_pdf``: dasselbe für PDFs, ohne Browser (pdfium): Seite mit dem Treffer
  rendern, Trefferzeichen gelb hinterlegen, Ausschnitt schneiden.

Auch der Browser darf nur ins offene Internet: jede Verbindung läuft über den Prüf-Proxy
(``pruefproxy.py``), der die tatsächlich angewählte IP prüft; zusätzlich filtert ``route`` jede
Anfrage der Seite vorab mit derselben Adressprüfung wie ``abruf.py``.
"""

import asyncio
import bisect
import io
import logging
import re
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings

from .abruf import AbrufFehler, pruefe_url
from .pruefproxy import PruefProxy

logger = logging.getLogger(__name__)

BREITE = 1280
MAX_HOEHE = 16000
ZEIT_MS = 30000
RAND = 260
GELB = (255, 213, 79)

# Erst ablehnen (datensparsam), dann zustimmen, damit das Banner nicht das Bild verdeckt.
_BANNER_KNOEPFE = [
    "Nur notwendige", "Alle ablehnen", "Ablehnen", "Reject all", "Decline",
    "Alle akzeptieren", "Akzeptieren", "Zustimmen", "Einverstanden", "Accept all", "Accept", "I agree",
]


#: Grenzen für fremde PDFs, damit ein präpariertes Dokument den Worker nicht lahmlegt.
PDF_MAX_SEITEN = 500
PDF_MAX_PIXEL = 6000


def _host_erlaubt(schema: str, host: str, port: int) -> bool:
    """Vorfilter ohne Zwischenspeicher; die verbindliche Prüfung macht der Prüf-Proxy je Verbindung."""
    try:
        pruefe_url(f"{schema}://{host}:{port}/")
        return True
    except AbrufFehler:
        return False


def _anfrage_pruefen(route):
    url = route.request.url
    if url.startswith(("data:", "blob:")):
        return route.continue_()
    teile = urlparse(url)
    port = teile.port or (443 if teile.scheme == "https" else 80)
    if teile.scheme in ("http", "https") and teile.hostname and _host_erlaubt(teile.scheme, teile.hostname, port):
        return route.continue_()
    return route.abort()


@contextmanager
def _browser_schleife():
    """Nur Windows-Entwicklung: Daphne stellt asyncio auf die Selector-Schleife um, die keine
    Unterprozesse starten kann — Chromium aber ist einer. Für die Dauer des Renderns auf Proactor.
    Unter Linux und macOS tut das nichts."""
    if sys.platform != "win32":
        yield
        return
    # Die Policy gilt für den ganzen Prozess: nur ein Rendern zur Zeit darf sie umstellen.
    with _SCHLEIFEN_SPERRE:
        alt = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            yield
        finally:
            asyncio.set_event_loop_policy(alt)


_SCHLEIFEN_SPERRE = threading.Lock()


# Kürzester Suchtext für die exakte Suche in einem Zitat OHNE Auslassung. Mit Auslassung und für jede unscharfe Suche
# gilt _UNSCHARF_MIN: „Die Bundesregierung […] hat zugestimmt“ hätte sonst irgendeine Stelle mit „Die Bundesregierung“
# gelb markiert, also einen falschen Beleg ins Video gebracht (Review 07.10.2026).
_EXAKT_MIN = 12
_UNSCHARF_MIN = 25
# Größter Abstand (angeglichene Zeichen, ≈ 2 Seiten) zwischen zwei Stücken eines Zitats mit Auslassung. Ohne Grenze
# stünde ein 25-Zeichen-Stück in einer 100-Seiten-Drucksache leicht irgendwo und „bestätigte“ eine falsche Ankerstelle
# (zweites Review 07.10.2026); der Seitenumbruch-Fall („[…]“ über zwei Seiten) bleibt abgedeckt.
_MAX_LUECKE = 6000
_AUSLASSUNG = re.compile(r"\[\s*(?:…|\.\.\.)\s*\]|…|\.\.\.")


def _kopf(text: str) -> str:
    """Die ersten gut 80 Zeichen eines Stücks, am Wortende geschnitten — so findet die Suche den Anfang."""
    return text[:90].rsplit(" ", 1)[0] if len(text) > 90 else text


def _zitat_stuecke(zitat: str) -> tuple[list[str], bool]:
    """Zitat ohne äußere Anführungszeichen, an Auslassungen („[…]“, „[...]“, „…“, „...“) geteilt, und ob es eine gab."""
    text = re.sub(r"\s+", " ", zitat).strip().strip("„“”\"'‚‘’»«")
    stuecke = [s.strip() for s in _AUSLASSUNG.split(text)]
    return [s for s in stuecke if s], len(stuecke) > 1


def _zitat_suchtext(zitat: str) -> str:
    """Suchtext für die Webseite: Anfang des ersten Stücks. Mit Auslassung nur, wenn das erste Stück mindestens
    _UNSCHARF_MIN Zeichen hat, sonst leer (dann keine Fundstelle). Früher blieb bei „[…]“ ein „[“ stehen (eine Bundestags-Drucksache)."""
    stuecke, auslassung = _zitat_stuecke(zitat)
    if not stuecke or (auslassung and len(stuecke[0]) < _UNSCHARF_MIN):
        return ""
    return _kopf(stuecke[0])


# pdfium setzt für eine Silbentrennung am Zeilenende U+FFFE in den Seitentext (im begrenzten Text U+0002);
# dazu das weiche Trennzeichen U+00AD. Als chr() geschrieben: U+FFFE wäre im Quelltext unsichtbar.
# Typografische Zeichen werden für die Suche einheitlich.
_TRENNUNG = chr(0xFFFE) + chr(0x02) + chr(0xAD)
_GLEICH = str.maketrans({"„": '"', "“": '"', "”": '"', "«": '"', "»": '"', "‚": "'", "‘": "'", "’": "'",
                         "–": "-", "—": "-", "\xa0": " "})


def _flach(text: str, bindestrich: str = "bleibt") -> tuple[str, list[int]]:
    """Text für die Suche angleichen und je Zeichen den Index im Original merken (für die Zeichenboxen).

    Die Trennung fällt weg (samt Umbruch danach), jede Folge von Leerraum wird ein Leerzeichen, alles klein.
    Ein echter Bindestrich direkt vor einem Umbruch: ``bleibt`` („Gesundheits- und“), ``klebt`` am nächsten Wort
    („Social-Media“) oder fällt ``weg`` („Bundes-⏎regierung“ → „bundesregierung“)."""
    zeichen: list[str] = []
    index: list[int] = []
    schlucken = False
    for i, roh in enumerate(text):
        am_umbruch = text[i + 1:i + 2] in ("\r", "\n")
        z = roh.translate(_GLEICH)  # erst angleichen, dann entscheiden („–“ am Zeilenende wie „-“)
        if roh in _TRENNUNG or (z == "-" and am_umbruch and bindestrich == "weg"):
            schlucken = True
            continue
        if z.isspace():
            if schlucken or not zeichen or zeichen[-1] == " ":
                continue
            z = " "
        else:
            klein = z.lower()
            # Wird ein Zeichen klein länger („İ“), bleibt es, wie es ist: sonst stimmen die Indizes nicht mehr 1:1.
            z = klein if len(klein) == 1 else z
            schlucken = z == "-" and am_umbruch and bindestrich == "klebt"
        zeichen.append(z)
        index.append(i)
    return "".join(zeichen), index


def _angeglichen(text: str) -> str:
    return _flach(text)[0].strip()


@dataclass(frozen=True)
class _Plan:
    """Wonach im PDF gesucht wird. Der ``anker`` wird markiert; die übrigen langen Stücke des Zitats müssen im
    Dokument in Zitatreihenfolge ``davor`` bzw. ``dahinter`` stehen (angeglichen). ``ende`` (nur ohne Auslassung)
    entscheidet, wenn der Anker mehrfach vorkommt; ``laenge`` ist das ganze Zitat, angeglichen."""

    anker: str
    davor: tuple[str, ...] = ()
    dahinter: tuple[str, ...] = ()
    ende: str = ""
    laenge: int = 0


def _suchplaene(zitat: str) -> list[_Plan]:
    """Ohne Auslassung: Anfang des Zitats (≥ _EXAKT_MIN), dazu sein Ende. Mit Auslassung zählen nur Stücke mit
    ≥ _UNSCHARF_MIN Zeichen: erst das erste Stück als Anker, sonst das längste, dann die übrigen nach Länge.
    Kürzere Stücke werden nicht geprüft: bei „A […] B“ mit B unter 25 Zeichen trägt allein A die Fundstelle."""
    stuecke, auslassung = _zitat_stuecke(zitat)
    if not stuecke:
        return []
    if not auslassung:
        ganz = stuecke[0]
        anker = _kopf(ganz)
        if len(anker) < _EXAKT_MIN:
            return []
        ende = ""
        if len(ganz) > len(anker):
            schluss = ganz[-60:]
            ende = _angeglichen(schluss.split(" ", 1)[1] if " " in schluss else schluss)
        return [_Plan(anker, ende=ende, laenge=len(_angeglichen(ganz)))]
    lang = [i for i, s in enumerate(stuecke) if len(s) >= _UNSCHARF_MIN]
    reihe = ([0] if 0 in lang else []) + sorted((i for i in lang if i != 0), key=lambda i: -len(stuecke[i]))
    return [
        _Plan(_kopf(stuecke[i]),
              davor=tuple(_angeglichen(_kopf(stuecke[j])) for j in lang if j < i),
              dahinter=tuple(_angeglichen(_kopf(stuecke[j])) for j in lang if j > i))
        for i in reihe
    ]


class _Seite:
    """Eine PDF-Seite für die Suche: Textseite, Volltext, angeglichene Fassungen je Bindestrich-Modus (bei Bedarf)."""

    def __init__(self, dokument, nummer: int):
        self.nummer = nummer
        self.seite = dokument[nummer]
        self.text = self.seite.get_textpage()
        anzahl = self.text.count_chars()
        self.roh = self.text.get_text_range(0, anzahl, force_this=True) if anzahl > 0 else ""
        # Nur wenn der Volltext Zeichen für Zeichen zu den Indizes passt, darf im angeglichenen Text gesucht und
        # gerechnet werden (Zeichen außerhalb der BMP o. Ä. verschieben sonst die Zeichenboxen).
        self.treu = anzahl > 0 and len(self.roh) == anzahl
        # „klebt“ und „weg“ unterscheiden sich von „bleibt“ nur bei einem Bindestrich vor einem Umbruch.
        self.modi = ("bleibt", "klebt", "weg") if re.search(r"[-–—][\r\n]", self.roh) else ("bleibt",)
        self._flach: dict[str, tuple[str, list[int]]] = {}

    def flach(self, modus: str) -> tuple[str, list[int]]:
        if modus not in self._flach:
            self._flach[modus] = _flach(self.roh, modus)
        return self._flach[modus]

    def schliessen(self) -> None:
        self.text.close()
        self.seite.close()


def _anker_stellen(seite: _Seite, anker: str) -> dict[int, int]:
    """Alle Stellen des Ankers auf der Seite als {erstes Zeichen: Anzahl}: pdfiums exakte Suche und, ab
    _UNSCHARF_MIN Zeichen, die Suche im angeglichenen Text (über Silbentrennung und Zeilenumbruch hinweg,
    „Bren-⏎de“ in Bundestags-Drucksachen). Beide zusammen, damit eine Mehrdeutigkeit nicht übersehen wird."""
    stellen: dict[int, int] = {}
    suche = seite.text.search(anker, match_case=False, match_whole_word=False)
    try:
        while fund := suche.get_next():
            stellen.setdefault(fund[0], fund[1])
    finally:
        suche.close()
    nadel = _angeglichen(anker)
    if len(nadel) < _UNSCHARF_MIN or not seite.treu:
        return stellen
    for modus in seite.modi:
        flach, index = seite.flach(modus)
        pos = flach.find(nadel)
        while pos >= 0:
            erstes, letztes = index[pos], index[pos + len(nadel) - 1]
            # Gegenprobe nur der Index-Treue: liefert pdfium für genau diese Indizes denselben Text? Ob es die
            # inhaltlich gemeinte Stelle ist, entscheiden erst die übrigen Stücke und die Eindeutigkeit.
            spanne = seite.text.get_text_range(erstes, letztes - erstes + 1, force_this=True)
            if nadel in _flach(spanne, modus)[0]:
                stellen.setdefault(erstes, letztes - erstes + 1)
            pos = flach.find(nadel, pos + 1)
    return stellen


class _Volltext:
    """Angeglichener Text aller Seiten hintereinander, je Bindestrich-Modus, mit dem Versatz jeder Seite. Eine
    Auslassung „[…]“ verbindet oft Stellen über einen Seitenumbruch (am 07.10.2026 bei 29 von 31 Belegen mit eindeutigem
    Anker); die Reihenfolge der Stücke wird deshalb im ganzen Dokument geprüft, nicht nur auf der Seite des Ankers."""

    def __init__(self, seiten: list[_Seite]):
        self.seiten = seiten
        self.modi = ("bleibt", "klebt", "weg") if any(len(s.modi) > 1 for s in seiten) else ("bleibt",)
        self._text: dict[str, tuple[str, dict[int, int]]] = {}

    def text(self, modus: str) -> tuple[str, dict[int, int]]:
        if modus not in self._text:
            teile, versatz, pos = [], {}, 0
            for s in self.seiten:
                versatz[s.nummer] = pos
                flach = s.flach(modus if modus in s.modi else "bleibt")[0]
                teile.append(flach)
                pos += len(flach) + 1
            self._text[modus] = (" ".join(teile), versatz)
        return self._text[modus]


def _stuecke_passen(volltext: _Volltext, seite: _Seite, start: int, anzahl: int, plan: _Plan,
                    mit_ende: bool = False) -> bool:
    """Stehen die übrigen Stücke in Zitatreihenfolge vor bzw. hinter dem Anker (über Seiten hinweg, je Stück höchstens
    _MAX_LUECKE vom vorigen entfernt), und mit ``mit_ende`` das Zitatende in Zitatlänge hinter dem Anfang?"""
    if not (plan.davor or plan.dahinter or mit_ende):
        return True
    if not seite.treu:
        # Nicht prüfbar (Indizes passen nicht zum Volltext): die Stelle bleibt Kandidat, damit ein zweites Vorkommen
        # nicht still verschwindet und eine andere Stelle fälschlich eindeutig wirkt (drittes Review 07.10.2026).
        # Als Bestätigung zählt das nicht; das entscheidet ``_fund_im_dokument``.
        return True
    for modus in volltext.modi:
        flach, versatz = volltext.text(modus)
        index = seite.flach(modus if modus in seite.modi else "bleibt")[1]
        a0 = versatz[seite.nummer] + bisect.bisect_left(index, start)
        a1 = versatz[seite.nummer] + bisect.bisect_right(index, start + anzahl - 1)
        ok, zeiger = True, a1
        for stueck in plan.dahinter:
            pos = flach.find(stueck, zeiger, zeiger + _MAX_LUECKE + len(stueck))
            if pos < 0:
                ok = False
                break
            zeiger = pos + len(stueck)
        zeiger = a0
        for stueck in reversed(plan.davor if ok else ()):
            pos = flach.rfind(stueck, max(0, zeiger - _MAX_LUECKE - len(stueck)), zeiger)
            if pos < 0:
                ok = False
                break
            zeiger = pos
        if ok and mit_ende:
            ok = bool(plan.ende) and flach.find(plan.ende, a0, a0 + plan.laenge + 40) >= 0
        if ok:
            return True
    return False


def _fund_im_dokument(dokument, zitat: str) -> tuple[int, int, int] | None:
    """(Seite, erstes Zeichen, Anzahl) — nur, wenn die Stelle eindeutig ist; sonst ``None``.

    Je Plan alle Stellen des Ankers im ganzen Dokument (exakt und angeglichen), davon nur die, hinter bzw. vor denen
    die übrigen Stücke in Zitatreihenfolge und in Reichweite stehen. Mehrere Stellen: ohne Auslassung entscheidet das
    Zitatende; bleibt es mehrdeutig, kommt der nächste Plan, zuletzt ``None``. Lieber kein Beweisblatt als ein falsches.

    Wurden Seiten übersprungen (zu groß, über PDF_MAX_SEITEN), gilt „eindeutig“ nur für die gelesenen: dann zählt ein
    Treffer nur, wenn weitere Stücke oder das Zitatende ihn bestätigen (zweites Review 07.10.2026)."""
    plaene = _suchplaene(zitat)
    if not plaene:
        return None
    seiten = []
    try:
        ausgelassen = len(dokument) > PDF_MAX_SEITEN
        for nummer in range(min(len(dokument), PDF_MAX_SEITEN)):
            seite = dokument[nummer]
            passt = max(seite.get_width(), seite.get_height()) * 2.0 <= PDF_MAX_PIXEL
            seite.close()
            if passt:
                seiten.append(_Seite(dokument, nummer))
            else:
                ausgelassen = True
        # Seiten mit Text, deren Indizes nicht treu sind, kann die unscharfe Suche nicht lesen: ein Vorkommen dort bliebe
        # unsichtbar. Sie zählen deshalb wie übersprungene Seiten (leere Seiten nicht, dort steht kein Anker).
        if any(s.roh and not s.treu for s in seiten):
            ausgelassen = True
        volltext = _Volltext(seiten)
        for plan in plaene:
            treffer = [(s, start, anzahl) for s in seiten for start, anzahl in sorted(_anker_stellen(s, plan.anker).items())
                       if _stuecke_passen(volltext, s, start, anzahl, plan)]
            if len(treffer) > 1 and plan.ende:
                treffer = [t for t in treffer if _stuecke_passen(volltext, *t, plan, mit_ende=True)]
            if len(treffer) != 1:
                continue
            s, start, anzahl = treffer[0]
            stuecke = bool(plan.davor or plan.dahinter)
            if stuecke and not s.treu:
                logger.warning("Fundstelle verworfen: Stücke auf einer nicht lesbaren Seite nicht prüfbar")
                continue
            if ausgelassen and not stuecke and not (
                    plan.ende and s.treu and _stuecke_passen(volltext, s, start, anzahl, plan, mit_ende=True)):
                logger.warning("Fundstelle verworfen: Seiten übersprungen oder nicht lesbar, Treffer nicht bestätigt")
                continue
            return s.nummer, start, anzahl
        return None
    finally:
        for s in seiten:
            s.schliessen()


def _browser_seite(pw, url, proxy):
    browser = pw.chromium.launch(
        proxy={"server": proxy},
        # Ohne diese Liste ginge Chromium bei localhost/127.0.0.1 am Proxy vorbei (auch WebSockets).
        args=["--disable-dev-shm-usage", "--proxy-bypass-list=<-loopback>"],
    )
    kontext = browser.new_context(
        viewport={"width": BREITE, "height": 900}, locale="de-DE", java_script_enabled=True,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   f"Chrome/145.0 Safari/537.36 {settings.AKTE_ABRUF_KENNUNG}",
    )
    kontext.route("**/*", _anfrage_pruefen)
    seite = kontext.new_page()
    try:
        seite.goto(url, wait_until="networkidle", timeout=ZEIT_MS)
    except Exception:  # noqa: BLE001 — langsame Seiten: was bis dahin geladen ist, zählt
        pass
    for text in _BANNER_KNOEPFE:
        knopf = seite.get_by_role("button", name=text, exact=False)
        try:
            if knopf.count() and knopf.first.is_visible():
                knopf.first.click(timeout=1500)
                seite.wait_for_timeout(600)
                break
        except Exception:  # noqa: BLE001
            continue
    return browser, seite


def seite_rendern(url: str) -> tuple[bytes, bytes]:
    """(Bild als JPEG, PDF) der ganzen Seite."""
    pruefe_url(url)
    from playwright.sync_api import sync_playwright

    with _browser_schleife(), PruefProxy() as proxy, sync_playwright() as pw:
        browser, seite = _browser_seite(pw, url, proxy)
        try:
            hoehe = min(seite.evaluate("document.documentElement.scrollHeight") or 900, MAX_HOEHE)
            bild = seite.screenshot(
                type="jpeg", quality=82, full_page=True,
                clip=None if hoehe <= MAX_HOEHE else {"x": 0, "y": 0, "width": BREITE, "height": MAX_HOEHE},
            )
            pdf = seite.pdf(format="A4", print_background=True)
        finally:
            browser.close()
    return bild, pdf


_MARKIEREN = """
(text) => {
  window.getSelection().removeAllRanges();
  if (!window.find(text, false, false, false, false, true, false)) return null;
  const bereich = window.getSelection().getRangeAt(0).cloneRange();
  // Steht der Suchtext ein zweites Mal auf der Seite, ist die Stelle nicht eindeutig: lieber keine Fundstelle als
  // eine falsche (Review 07.10.2026). Die Suche läuft ab dem ersten Treffer weiter, ohne Umbruch nach oben.
  const zweiter = window.find(text, false, false, false, false, true, false);
  window.getSelection().removeAllRanges();
  if (zweiter) return 'mehrdeutig';
  const rechtecke = [...bereich.getClientRects()];
  if (!rechtecke.length) return null;
  const oben = window.scrollY;
  for (const r of rechtecke) {
    const m = document.createElement('div');
    Object.assign(m.style, {position: 'absolute', left: (r.left + window.scrollX - 2) + 'px', top: (r.top + oben - 2) + 'px',
      width: (r.width + 4) + 'px', height: (r.height + 4) + 'px', background: 'rgba(255, 213, 79, 0.55)',
      mixBlendMode: 'multiply', zIndex: 2147483647, pointerEvents: 'none', borderRadius: '2px'});
    document.body.appendChild(m);
  }
  const y0 = Math.min(...rechtecke.map(r => r.top)) + oben;
  const y1 = Math.max(...rechtecke.map(r => r.bottom)) + oben;
  return [y0, y1];
}
"""


class FundstelleMehrdeutig(Exception):
    """Der Suchtext steht mehrfach auf der Seite; welche Stelle gemeint ist, lässt sich nicht sagen."""


def fundstelle_html(url: str, zitat: str) -> bytes | None:
    """Ausschnitt der Seite mit gelb markiertem Zitat, oder ``None``, wenn es nicht gefunden wird.
    Steht der Suchtext mehrfach auf der Seite: ``FundstelleMehrdeutig`` (die Sicherung hält das als Fehler fest).

    Anders als im PDF wird hier NUR das erste Stück des Zitats gesucht (``_zitat_suchtext``: bei Auslassung erst ab
    _UNSCHARF_MIN Zeichen); Stücke hinter „[…]“ prüft ``window.find`` nicht. Schutz gegen eine falsche Stelle ist
    allein die Eindeutigkeit des ersten Stücks auf der Seite."""
    suchtext = _zitat_suchtext(zitat)
    if len(suchtext) < _EXAKT_MIN:
        return None
    pruefe_url(url)
    from playwright.sync_api import sync_playwright

    with _browser_schleife(), PruefProxy() as proxy, sync_playwright() as pw:
        browser, seite = _browser_seite(pw, url, proxy)
        try:
            treffer = seite.evaluate(_MARKIEREN, suchtext)
            if treffer == "mehrdeutig":
                raise FundstelleMehrdeutig("Zitat steht mehrfach auf der Seite, Stelle nicht eindeutig.")
            if not treffer:
                return None
            y0, y1 = treffer
            oben = max(0, y0 - RAND)
            hoehe = min(max(y1 - y0 + 2 * RAND, 700), 2400)
            seite.evaluate(f"window.scrollTo(0, {oben})")
            return seite.screenshot(
                type="jpeg", quality=88, full_page=True,
                clip={"x": 0, "y": oben, "width": BREITE, "height": hoehe},
            )
        finally:
            browser.close()


def fundstelle_pdf(pdf: bytes, zitat: str) -> bytes | None:
    """Seite mit dem Zitat rendern, Trefferzeichen gelb hinterlegen, Ausschnitt als JPEG; ``None``, wenn die Stelle
    nicht oder nicht eindeutig gefunden wird."""
    if not _suchplaene(zitat):
        return None
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw

    dokument = pdfium.PdfDocument(pdf)
    try:
        fund = _fund_im_dokument(dokument, zitat)
        if not fund:
            return None
        nummer, start, anzahl = fund
        seite = dokument[nummer]
        text = seite.get_textpage()
        skala = 2.0
        try:
            bild = seite.render(scale=skala).to_pil().convert("RGB")
            hoehe_pt = seite.get_height()
            ueberlagerung = Image.new("RGBA", bild.size, (0, 0, 0, 0))
            zeichnen = ImageDraw.Draw(ueberlagerung)
            ys = []
            for i in range(start, start + anzahl):
                try:
                    links, unten, rechts, oben = text.get_charbox(i)
                except pdfium.PdfiumError:  # erzeugte Zeichen (Umbruch) haben teils keine Box
                    continue
                if rechts <= links:
                    continue
                x0, x1 = links * skala - 1, rechts * skala + 1
                y0, y1 = (hoehe_pt - oben) * skala - 2, (hoehe_pt - unten) * skala + 2
                zeichnen.rectangle([x0, y0, x1, y1], fill=(*GELB, 140))
                ys += [y0, y1]
        finally:
            text.close()
            seite.close()
        bild = Image.alpha_composite(bild.convert("RGBA"), ueberlagerung).convert("RGB")
        if ys:
            oben_px = max(0, int(min(ys)) - RAND)
            unten_px = min(bild.height, int(max(ys)) + RAND)
            bild = bild.crop((0, oben_px, bild.width, unten_px))
        ausgabe = io.BytesIO()
        bild.save(ausgabe, "JPEG", quality=88)
        return ausgabe.getvalue()
    finally:
        dokument.close()
