"""Zitat prüfen: Steht der Wortlaut eines Belegs in seiner Quelle? Synchron, höchstens 30 Sekunden.

1. **Kopie:** die jüngste gesicherte eigene Kopie (Original oder Anhang). Gibt es keine lesbare, lädt die Akte NUR
   das Original von der gespeicherten Adresse der Quelle – über den sicheren Abruf (``abruf.py``: nur öffentliche
   Adressen, jede Weiterleitung geprüft, Größe und Zeit begrenzt, DNS mit Frist), nie von archive.org und nie von
   einer Adresse aus der Anfrage. Abgelegt (als Original-Sicherung) wird es nur, wenn die Quelle noch GAR KEINE
   eigene Kopie hat; eine vorhandene wird nie durch eine Prüfung ergänzt oder ersetzt.
2. **Text:** PDFs über pdfium, Webseiten als Text aus dem HTML. Beides ohne Browser; das Seitenbild mit gelber
   Markierung bleibt Sache der Beweissicherung (Chromium) und ist für „gefunden“ nicht nötig.
3. **Suche** mit demselben Kern wie die Fundstellen (``rendern._flach``, ``rendern._zitat_stuecke``): gleiche
   Schreibweise für Anführungszeichen, Striche und Leerraum, jede Lesart eines Bindestrichs am Zeilenende
   („EU-⏎Verordnung“ bleibt „EU-Verordnung“, „Bundes-⏎regierung“ wird „Bundesregierung“), Auslassungen „[…]“
   trennen Teile, die in dieser Reihenfolge und höchstens zwei Seiten auseinander stehen müssen.

Ergebnis: ``gefunden`` (jeder Teil steht wörtlich da), ``nicht_gefunden`` oder ``nicht_pruefbar`` (kein Zitat, keine
Kopie, kein lesbarer Text, Zeit um) – immer mit einem Grund, den ein Mensch versteht. Nie „läuft“. „Gefunden“ heißt
nur: Der Wortlaut steht in der Quelle. Ob er die Behauptung trägt, entscheidet ein Mensch mit der Freigabe.
Die Prüfung ändert weder Status noch Beleg (höchstens legt sie, wie oben, die erste Kopie einer Quelle ab); deshalb
darf sie auch ein Werkzeug (Token) anstoßen.

Die 30 s hält jeder Schritt selbst ein: Abruf und DNS mit Frist, HTML in Stücken, pdfium seitenweise, die Suche prüft
die Frist in ihren Schleifen und merkt sich gescheiterte Stellen, höchstens ``TEILE_MAX`` Teile je Zitat.
"""

from __future__ import annotations

import bisect
import hashlib
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser

from django.conf import settings

from . import speicher
from .abruf import BILDER, AbrufFehler, abrufen, erkenne
from .models import SicherungArt
from .models import SicherungStatus
from .rendern import (
    _EXAKT_MIN,
    _MAX_LUECKE,
    _UNSCHARF_MIN,
    PDF_MAX_SEITEN,
    PDFIUM_SPERRE,
    _flach,
    _zitat_stuecke,
    modi_fuer,
)
from .sicherung import _ablegen, eigene_kopie

logger = logging.getLogger(__name__)

GEFUNDEN, NICHT_GEFUNDEN, NICHT_PRUEFBAR = "gefunden", "nicht_gefunden", "nicht_pruefbar"

#: Die ganze Prüfung, vom Eingang bis zur Antwort.
FRIST_SEKUNDEN = 30.0
#: Höchstens so lange darf der Abruf eines Originals dauern; der Rest bleibt fürs Lesen und Suchen.
ABRUF_SEKUNDEN = 20.0
#: Größte Textmenge, die durchsucht wird (≈ 1000 Seiten Drucksache).
TEXT_MAX = 3_000_000
#: Größtes HTML, das in Text verwandelt wird; gefüttert wird in Stücken, zwischen denen die Frist zählt.
HTML_MAX = 4 * 1024 * 1024
HTML_STUECK = 256 * 1024
#: Höchstens so viele Teile (durch Auslassungen „[…]“ getrennt) je Zitat.
TEILE_MAX = 20
#: Geschätzte Zeit je Zeichen und Lesart für ``_flach`` (gemessen ≈ 1,6 µs, mit Reserve).
_SEKUNDEN_JE_ZEICHEN = 2.5e-6
#: Weniger Text liefert eine Seite ohne Browser kaum, wenn sie ihren Inhalt per JavaScript nachlädt.
WENIG_TEXT = 300

#: Höchstens zwei Abrufe für Prüfungen gleichzeitig je Prozess: sechs parallele Prüfungen stauen sonst den Server.
_abrufe = threading.BoundedSemaphore(2)


class _NichtPruefbar(Exception):
    """Prüfen geht nicht; die Nachricht ist der Grund für Menschen."""


@dataclass
class _Kopie:
    daten: bytes
    sha256: str
    beschreibung: str  # „gesicherte Kopie vom …“ / „eben geladenes Original“


@dataclass
class _Text:
    inhalt: str
    art: str  # "pdf" | "html" | "text"
    seiten: tuple[int, ...] = ()  # Anfang jeder PDF-Seite in ``inhalt``
    vollstaendig: bool = True
    luecke: str = ""  # warum nicht alles gelesen wurde


def _antwort(ergebnis: str, grund: str, fundstelle: dict | None = None) -> dict:
    return {"ergebnis": ergebnis, "grund": grund, "fundstelle": fundstelle}


# ─── Kopie holen ─────────────────────────────────────────────────────────────

def _datum(wert) -> str:
    return wert.strftime("%d.%m.%Y") if wert else "unbekanntem Datum"


def _kopie_holen(quelle, frist: float) -> _Kopie:
    kopie = eigene_kopie(quelle)
    if kopie is not None and kopie.schluessel:
        try:
            return _Kopie(speicher.lesen(kopie.schluessel), kopie.sha256,
                          f"gesicherte Kopie vom {_datum(kopie.gesichert_am)}")
        except speicher.KopieBeschaedigt:
            raise _NichtPruefbar("Die gesicherte Kopie passt nicht mehr zu ihrer Prüfsumme (beschädigt oder verändert). "
                                 "Bitte die Quelle neu sichern und dann erneut prüfen.") from None
        except Exception:  # noqa: BLE001 — Speicher nicht erreichbar: dann das Original laden
            logger.warning("Akte: gesicherte Kopie %s nicht lesbar, lade das Original", kopie.pk, exc_info=True)
    if not quelle.url:
        raise _NichtPruefbar("Die Quelle hat weder einen Link noch eine gesicherte Datei. Hänge das Dokument als Datei "
                             "an die Quelle an, dann lässt sich das Zitat prüfen.")
    warten = min(10.0, frist - time.monotonic() - 8.0)
    if warten <= 0 or not _abrufe.acquire(timeout=warten):
        raise _NichtPruefbar("Die Ultra-Akte lädt gerade andere Quellen. Bitte in einer Minute noch einmal prüfen.")
    try:
        # Die Frist gilt für alles: DNS, Verbindung, jede Weiterleitung, das Lesen (abruf.abrufen).
        abruf = abrufen(quelle.url, frist=min(frist - 6.0, time.monotonic() + ABRUF_SEKUNDEN))
    except AbrufFehler as fehler:
        raise _NichtPruefbar(f"Die Quelle ist gerade nicht abrufbar ({fehler}). Später erneut prüfen oder das "
                             "Dokument als Datei anhängen.") from None
    finally:
        _abrufe.release()
    sha = hashlib.sha256(abruf.daten).hexdigest()
    beschreibung = "eben geladenes Original (nicht gesichert)"
    # Ablegen nur als ERSTE Kopie: Eine Prüfung ergänzt oder ersetzt nie, was schon gesichert ist (auch keine Kopie,
    # die gerade nur nicht lesbar war); sonst änderte sie, auf welche Kopie sich ein Beleg stützt.
    hat_kopie = quelle.sicherungen.filter(art__in=[SicherungArt.ORIGINAL, SicherungArt.ANHANG],
                                          status=SicherungStatus.FERTIG).exists()
    if not hat_kopie and getattr(settings, "AKTE_SICHERUNG_AKTIV", True) and speicher.eingerichtet():
        try:
            _ablegen(quelle, SicherungArt.ORIGINAL, abruf.daten, abgerufen_von=abruf.url)
            beschreibung = "eben geladenes und jetzt als erste Kopie gesichertes Original"
        except Exception:  # noqa: BLE001 — Prüfen geht auch ohne Ablage
            logger.warning("Akte: Original für Quelle %s nicht gesichert", quelle.pk, exc_info=True)
    return _Kopie(abruf.daten, sha, beschreibung)


# ─── Text lesen ──────────────────────────────────────────────────────────────

def _nfkc(text: str) -> str:
    """Ligaturen („ﬁ“), geschützte und schmale Leerzeichen, Vollbreite: auf die gewöhnliche Schreibweise."""
    return unicodedata.normalize("NFKC", text)


def _pdf_text(daten: bytes, frist: float) -> _Text:
    """Text aller Seiten (bis ``PDF_MAX_SEITEN``) unter der gemeinsamen pdfium-Sperre; wer sie zu lange nicht
    bekommt, ist nicht prüfbar (statt die 30 s zu reißen)."""
    warten = frist - time.monotonic() - 5.0
    if warten <= 0 or not PDFIUM_SPERRE.acquire(timeout=warten):
        raise _NichtPruefbar("Die Ultra-Akte liest gerade andere PDFs. Bitte in einer Minute noch einmal prüfen.")
    try:
        return _pdf_text_gesperrt(daten, frist)
    finally:
        PDFIUM_SPERRE.release()


def _pdf_text_gesperrt(daten: bytes, frist: float) -> _Text:
    import pypdfium2 as pdfium

    if time.monotonic() > frist - 3:
        raise _ZeitUm
    try:
        dokument = pdfium.PdfDocument(daten)
    except pdfium.PdfiumError:
        raise _NichtPruefbar("Das PDF lässt sich nicht öffnen (beschädigt oder mit Passwort geschützt).") from None
    teile: list[str] = []
    anfaenge: list[int] = []
    laenge = 0
    luecke = ""
    try:
        anzahl = len(dokument)
        if anzahl > PDF_MAX_SEITEN:
            luecke = f"Das PDF hat {anzahl} Seiten; gelesen wurden die ersten {PDF_MAX_SEITEN}."
        for nummer in range(min(anzahl, PDF_MAX_SEITEN)):
            if time.monotonic() > frist - 3:
                luecke = f"Die Zeit reichte nur für die ersten {nummer} von {anzahl} Seiten."
                break
            seite = dokument[nummer]
            try:
                textseite = seite.get_textpage()
                try:
                    zeichen = textseite.count_chars()
                    roh = textseite.get_text_range(0, zeichen, force_this=True) if zeichen > 0 else ""
                finally:
                    textseite.close()
            finally:
                seite.close()
            roh = _nfkc(roh)
            anfaenge.append(laenge)
            teile.append(roh)
            laenge += len(roh) + 1
            if laenge > TEXT_MAX:
                luecke = f"Das PDF ist sehr lang; gelesen wurden die ersten {nummer + 1} Seiten."
                break
    finally:
        dokument.close()
    inhalt = "\n".join(teile)
    if len(inhalt.strip()) < 20:
        raise _NichtPruefbar("Das PDF enthält keinen lesbaren Text (vermutlich ein eingescanntes Dokument). Bitte das "
                             "Zitat von Hand an der Quelle prüfen.")
    return _Text(inhalt, "pdf", tuple(anfaenge), not luecke, luecke)


class _HtmlText(HTMLParser):
    """Sichtbarer Text einer Seite, ohne Skripte und Stile. Blöcke werden Zeilen, Inline-Elemente kleben zusammen
    („EU-<b>Verordnung</b>“ bleibt ein Wort)."""

    UNSICHTBAR = {"script", "style", "noscript", "template"}
    BLOCK = {"address", "article", "aside", "blockquote", "br", "caption", "dd", "details", "div", "dl", "dt",
             "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li",
             "main", "nav", "ol", "option", "p", "pre", "section", "summary", "table", "tbody", "td", "tfoot", "th",
             "thead", "title", "tr", "ul"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile: list[str] = []
        self.versteckt = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.UNSICHTBAR:
            self.versteckt += 1
        elif tag == "body":
            self.versteckt = 0  # ein nicht geschlossenes <noscript> im Kopf verschluckt nicht die ganze Seite
        elif tag in self.BLOCK and not self.versteckt:
            self.teile.append("\n")

    def handle_endtag(self, tag):
        if tag in self.UNSICHTBAR:
            self.versteckt = max(0, self.versteckt - 1)
        elif tag in self.BLOCK and not self.versteckt:
            self.teile.append("\n")

    def handle_data(self, data):
        if not self.versteckt:
            self.teile.append(data)


def _dekodieren(daten: bytes) -> str:
    angabe = re.search(rb"""charset\s*=\s*["']?([A-Za-z0-9_\-]{2,40})""", daten[:4096])
    for kodierung in ([angabe.group(1).decode("ascii")] if angabe else []) + ["utf-8"]:
        try:
            return daten.decode(kodierung)
        except (LookupError, UnicodeDecodeError):
            continue
    return daten.decode("cp1252", errors="replace")


class _ZeitUm(Exception):
    pass


def html_zu_text(html: str, frist: float | None = None) -> str:
    """Sichtbarer Text; in Stücken gefüttert, damit eine riesige Seite die Frist nicht reißt (``_ZeitUm``)."""
    leser = _HtmlText()
    for anfang in range(0, len(html), HTML_STUECK):
        if frist is not None and time.monotonic() > frist:
            raise _ZeitUm
        leser.feed(html[anfang:anfang + HTML_STUECK])
    leser.close()
    return "".join(leser.teile)


def _html_text(daten: bytes, frist: float | None = None) -> _Text:
    luecke = ""
    if len(daten) > HTML_MAX:
        daten, luecke = daten[:HTML_MAX], "Die Seite ist sehr groß; gelesen wurde der Anfang."
    try:
        inhalt = _nfkc(html_zu_text(_dekodieren(daten), frist))
    except _ZeitUm:
        raise
    except Exception:  # noqa: BLE001 — kaputtes HTML: lieber ehrlich „nicht prüfbar“ als ein Serverfehler
        logger.warning("Akte: HTML nicht lesbar", exc_info=True)
        raise _NichtPruefbar("Der Text der Seite lässt sich nicht lesen. Bitte von Hand prüfen.") from None
    return _Text(inhalt[:TEXT_MAX], "html", vollstaendig=not luecke and len(inhalt) <= TEXT_MAX, luecke=luecke)


def _text_lesen(daten: bytes, frist: float) -> _Text:
    art = erkenne(daten)
    if art == "pdf":
        return _pdf_text(daten, frist)
    if art == "html":
        return _html_text(daten, frist)
    if art in BILDER:
        raise _NichtPruefbar("Die Quelle ist ein Bild; Text in Bildern liest die Akte nicht. Bitte das Zitat von Hand "
                             "prüfen.")
    if b"\x00" not in daten[:4096]:
        roh = _dekodieren(daten)
        if roh.lstrip()[:1] == "<" and "<html" in roh[:20000].lower():
            return _html_text(daten, frist)
        return _Text(_nfkc(roh)[:TEXT_MAX], "text", vollstaendig=len(roh) <= TEXT_MAX,
                     luecke="" if len(roh) <= TEXT_MAX else "Der Text ist sehr lang; gelesen wurde der Anfang.")
    raise _NichtPruefbar("Unbekanntes Dateiformat (weder PDF noch Webseite noch Text). Bitte von Hand prüfen.")


# ─── Suchen ──────────────────────────────────────────────────────────────────

#: „EU- Verordnung“ im Zitat: meist ein Zeilenumbruch, der beim Kopieren aus einem PDF zum Leerzeichen wurde.
_STRICH_LEER = re.compile(r"(?<=\w)([-–—]) (?=\w)")


def _teile(zitat: str) -> list[list[str]]:
    """Das Zitat in Teilen (an Auslassungen getrennt), jeder Teil in jeder Lesart, angeglichen wie der Text.

    Ein Strich vor einem Leerzeichen im Zitat wird wie ein Bindestrich am Zeilenende gelesen (so wird aus einem aus
    dem PDF kopierten „EU-⏎Verordnung“ auch „EU-Verordnung“); „Gesundheits- und“ bleibt dabei eine der Lesarten."""
    stuecke, _ = _zitat_stuecke(_nfkc(zitat))
    teile = []
    for stueck in stuecke:
        stueck = _STRICH_LEER.sub("\\1\n", stueck)
        lesarten = list(dict.fromkeys(_flach(stueck, m)[0].strip() for m in modi_fuer(stueck)))
        lesarten = [x for x in lesarten if x]
        if lesarten:
            teile.append(lesarten)
    return teile


class _Reihenfolge:
    """Stehen alle Teile in Reihenfolge, jeder höchstens ``_MAX_LUECKE`` hinter dem Ende des vorigen?

    Teil für Teil statt Versuch und Irrtum: Für jeden Teil entsteht die Liste der Stellen, an denen er nach einem
    erreichbaren Ende des vorigen Teils stehen darf (nach Ende sortiert, Suche per ``bisect``). Jede Stelle wird
    also höchstens einmal betrachtet, auch bei häufigen kurzen Teilen – keine exponentielle Suche, und die Frist
    wird in den Schleifen geprüft."""

    def __init__(self, flach: str, teile: list[list[str]], frist: float | None):
        self.flach, self.teile, self.frist = flach, teile, frist
        self.schritte = 0

    def _zeit(self) -> None:
        self.schritte += 1
        if self.frist is not None and self.schritte % 64 == 0 and time.monotonic() > self.frist:
            raise _ZeitUm

    def _stellen(self, lesart: str, von: int = 0, bis: int | None = None):
        bis = len(self.flach) if bis is None else bis
        pos = self.flach.find(lesart, von, bis)
        while pos >= 0:
            self._zeit()
            yield pos
            pos = self.flach.find(lesart, pos + 1, bis)

    def finden(self) -> tuple[int, int] | None:
        # Erreichbare Enden des bisherigen Zitats: nach Ende sortiert, je mit dem Anfang des ersten Teils.
        enden: list[int] = []
        anfaenge: list[int] = []
        paare = sorted({(pos + len(lesart), pos) for lesart in self.teile[0] for pos in self._stellen(lesart)})
        for teil in self.teile[1:]:
            if not paare:
                return None
            enden = [e for e, _ in paare]
            anfaenge = [a for _, a in paare]
            neu: dict[int, int] = {}
            for lesart in teil:
                # Nur dort suchen, wo der Teil überhaupt hinter einem erreichbaren Ende stehen kann.
                for pos in self._stellen(lesart, enden[0], enden[-1] + _MAX_LUECKE + len(lesart)):
                    i = bisect.bisect_left(enden, pos - _MAX_LUECKE)
                    if i < len(enden) and enden[i] <= pos:
                        ende = pos + len(lesart)
                        neu[ende] = min(neu.get(ende, anfaenge[i]), anfaenge[i])
            paare = sorted(neu.items())
        if not paare:
            return None
        ende, anfang = min(paare, key=lambda p: (p[1], p[0]))
        return anfang, ende


def _in_reihenfolge(flach: str, teile: list[list[str]], frist: float | None = None) -> tuple[int, int] | None:
    return _Reihenfolge(flach, teile, frist).finden()


class _Suche:
    """Ein Text in jeder Lesart, angeglichen nur bei Bedarf (die gewöhnliche zuerst) und dann gemerkt."""

    def __init__(self, inhalt: str, frist: float | None = None):
        self.inhalt, self.frist = inhalt, frist
        self.modi = modi_fuer(inhalt)
        self._flach: dict[str, tuple[str, list[int]]] = {}

    def _lesart(self, modus: str) -> tuple[str, list[int]]:
        if modus not in self._flach:
            # Früh aufgeben, wenn die Zeit sichtbar nicht reicht; sonst prüft ``_flach`` selbst alle 64 KB Text.
            if self.frist is not None and time.monotonic() + len(self.inhalt) * _SEKUNDEN_JE_ZEICHEN > self.frist:
                raise _ZeitUm
            try:
                self._flach[modus] = _flach(self.inhalt, modus, frist=self.frist)
            except TimeoutError:
                raise _ZeitUm from None
        return self._flach[modus]

    def finden(self, teile: list[list[str]]) -> tuple[int, int] | None:
        """(Anfang, Ende) in ``inhalt``: alle Teile in Reihenfolge, in irgendeiner Lesart."""
        if not teile:
            return None
        for modus in self.modi:
            flach, index = self._lesart(modus)
            treffer = _in_reihenfolge(flach, teile, self.frist)
            if treffer:
                anfang, ende = treffer
                return index[anfang], index[ende - 1] + 1
        return None


def zitat_finden(inhalt: str, zitat: str, frist: float | None = None) -> tuple[int, int] | None:
    """(Anfang, Ende) des Zitats in ``inhalt`` oder ``None``."""
    return _Suche(inhalt, frist).finden(_teile(zitat))


def _anfang_finden(suche: _Suche, zitat: str) -> int | None:
    """Steht wenigstens der Anfang des Zitats (die ersten gut 30 Zeichen) in der Quelle? Für einen hilfreichen Grund."""
    stuecke, _ = _zitat_stuecke(_nfkc(zitat))
    if not stuecke or len(stuecke[0]) < _UNSCHARF_MIN:
        return None
    kopf = stuecke[0][:40].rsplit(" ", 1)[0] if len(stuecke[0]) > 40 else stuecke[0]
    if len(kopf) < 20:
        return None
    try:
        treffer = suche.finden(_teile(kopf))
    except _ZeitUm:
        return None
    return treffer[0] if treffer else None


def _seite(text: _Text, stelle: int) -> int | None:
    return bisect.bisect_right(text.seiten, stelle) if text.seiten else None


_ANZEIGE = str.maketrans({0xFFFE: "-", 0x02: "-", 0xAD: None})


def _auszug(inhalt: str, anfang: int, ende: int) -> str:
    links, rechts = max(0, anfang - 80), min(len(inhalt), ende + 80)
    mitte = inhalt[anfang:ende]
    if len(mitte) > 600:
        mitte = mitte[:300] + " […] " + mitte[-300:]
    text = " ".join((inhalt[links:anfang] + mitte + inhalt[ende:rechts]).translate(_ANZEIGE).split())
    return ("…" if links > 0 else "") + text + ("…" if rechts < len(inhalt) else "")


# ─── Prüfen ──────────────────────────────────────────────────────────────────

def pruefen(beleg) -> dict:
    """Steht das Zitat des Belegs in seiner Quelle? Antwort ``{ergebnis, grund, fundstelle}`` (siehe Moduldoku)."""
    frist = time.monotonic() + FRIST_SEKUNDEN
    zitat = (beleg.zitat_woertlich or "").strip()
    if not zitat:
        return _antwort(NICHT_PRUEFBAR, "Der Beleg hat kein wörtliches Zitat. Trage den Originalwortlaut der Quelle "
                                        "ein (keine Zusammenfassung), dann lässt er sich prüfen.")
    teile = _teile(zitat)
    if not teile:
        return _antwort(NICHT_PRUEFBAR, "Das Zitat besteht nur aus Auslassungszeichen und Anführungszeichen.")
    if len(" ".join(t[0] for t in teile)) < _EXAKT_MIN:
        return _antwort(NICHT_PRUEFBAR, f"Das Zitat ist zu kurz, um es sicher zu prüfen (mindestens {_EXAKT_MIN} "
                                        "Zeichen). Zitiere einen ganzen Satz oder Satzteil.")
    if len(teile) > TEILE_MAX:
        return _antwort(NICHT_PRUEFBAR, f"Das Zitat hat zu viele Auslassungen ({len(teile)} Teile, höchstens "
                                        f"{TEILE_MAX}). Zitiere die tragende Stelle zusammenhängend.")
    try:
        kopie = _kopie_holen(beleg.quelle, frist)
        text = _text_lesen(kopie.daten, frist)
        suche = _Suche(text.inhalt, frist)
        treffer = suche.finden(teile)
    except _NichtPruefbar as grund:
        return _antwort(NICHT_PRUEFBAR, str(grund))
    except _ZeitUm:
        return _antwort(NICHT_PRUEFBAR, "Das Dokument ist zu groß, um es in 30 Sekunden ganz zu prüfen. Bitte von Hand "
                                        "prüfen oder die betreffenden Seiten als eigene Datei anhängen.")
    geprueft = f"Geprüft an: {kopie.beschreibung}."
    wo = {"pdf": "im PDF", "html": "im Text der Webseite (ohne Browser gelesen)", "text": "im Text der Quelle"}[text.art]
    if treffer:
        anfang, ende = treffer
        seite = _seite(text, anfang)
        stelle = f"{wo}, Seite {seite}" if seite else wo
        satz = ("Alle Teile des Zitats stehen in dieser Reihenfolge" if len(teile) > 1
                else "Das Zitat steht wörtlich")
        return _antwort(GEFUNDEN, f"{satz} {stelle}. {geprueft} Ob der Wortlaut die Behauptung trägt, entscheidet "
                                  "ein Mensch mit der Freigabe.",
                        {"seite": seite, "auszug": _auszug(text.inhalt, anfang, ende), "sha256": kopie.sha256})
    if not text.vollstaendig:
        return _antwort(NICHT_PRUEFBAR, f"Im gelesenen Teil nicht gefunden. {text.luecke} Bitte den Rest von Hand "
                                        f"prüfen. {geprueft}")
    sichtbar = len(" ".join(text.inhalt.split()))
    if text.art == "html" and sichtbar < WENIG_TEXT:
        return _antwort(NICHT_PRUEFBAR, f"Die Seite liefert ohne Browser kaum Text ({sichtbar} Zeichen; vermutlich "
                                        "lädt sie ihn per JavaScript nach oder zeigt erst einen Cookie-Hinweis). Bitte "
                                        f"von Hand prüfen oder die Seite als PDF anhängen. {geprueft}")
    anfang = _anfang_finden(suche, zitat)
    if anfang is not None:
        seite = _seite(text, anfang)
        grund = (f"Der Anfang des Zitats steht {wo}{f' (Seite {seite})' if seite else ''}, danach weicht der Wortlaut "
                 "ab. Vergleiche Wort für Wort mit der Quelle und kennzeichne Ausgelassenes mit […].")
    else:
        grund = ("Das Zitat steht so nicht in der Quelle. Zitiert wird nur der Originalwortlaut, keine "
                 "Zusammenfassung; Ausgelassenes mit […] kennzeichnen.")
    if text.art == "html":
        grund += (" Geprüft wurde der Text der Seite ohne Browser: Was die Seite erst per JavaScript nachlädt, fehlt "
                  "hier.")
    return _antwort(NICHT_GEFUNDEN, f"{grund} {geprueft}")
