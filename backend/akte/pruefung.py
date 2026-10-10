"""Die Veröffentlichungs-Prüfung — was von der Akte öffentlich werden darf.

**Alle** Entscheidungen „darf das raus?“ laufen durch dieses Modul. Die Werkstatt
zeigt die Befunde als Warnung an der Karte; die öffentliche Ansicht lässt jeden
Faden weg, der einen sperrenden Befund hat. Grundlage sind die Belegregeln der Akte
(Aussagen über Macht, Kontrolle und Überwachung nur mit Belegen) und das deutsche
Presserecht zur Verdachtsberichterstattung (Mindestbestand an Beweistatsachen,
Anhörung, § 186 StGB). Das ersetzt keine anwaltliche Prüfung.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from .models import Aussageart, Status, Verbindung, VerbindungTyp
from .regeln import AUS, SPERRT, ZUSTAND, einstellung

#: Wie viele voneinander unabhängige Quellen ein Verdacht gegen eine Person braucht.
VERDACHT_MIN_QUELLEN = 2


@dataclass(frozen=True)
class Befund:
    code: str
    text: str
    #: Stufe der Regel (akte/regeln.py): "hinweis" oder "sperrt". Regeln auf "aus" erscheinen nicht.
    schwere: str = SPERRT
    #: Ein Mensch hat diesen Befund mit Begründung überstimmt (nur Belegregeln, nie Zustandsregeln).
    ueberstimmt: bool = False


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def unabhaengige_quellen(verbindung: Verbindung) -> int:
    """Zählt Quellen nach Herkunft: zwei Artikel derselben Zeitung sind eine Quelle."""
    herkuenfte = set()
    for beleg in verbindung.belege.all():
        q = beleg.quelle
        herkuenfte.add((q.herausgeber or "").strip().lower() or _domain(q.url) or f"id:{q.pk}")
    return len(herkuenfte)


def faeden_qs():
    """Fäden mit allem, was die Prüfung braucht, in einer festen Zahl von Abfragen (auch Freigaben beider Enden)."""
    from .beweisschicht import freigaben_prefetch

    return Verbindung.objects.select_related("von", "nach").prefetch_related(
        "belege__quelle__sicherungen__beleg", "ueberstimmungen", freigaben_prefetch(),
        freigaben_prefetch("von__ereignisse"), freigaben_prefetch("nach__ereignisse"),
    )


def pruefe_verbindung(v: Verbindung, board=None, *, ohne_zustand: bool = False) -> list[Befund]:
    """Alle Befunde eines Fadens mit ihrer Stufe (Standard, ``AKTE_REGELN``, ``Board.regeln``).

    Öffentlich darf ein Faden, wenn kein Befund sperrt (``darf_oeffentlich``). ``ohne_zustand`` lässt die
    Zustandsregeln weg (für die Freigabe selbst, die genau diesen Zustand herstellt).

    Erwartet die Vorabfragen aus ``faeden_qs``, sonst kostet jeder Faden mehrere Abfragen.
    Regel 2 (Aussageart) und 5 (Güte ★/☆) erzwingt das Modell selbst: beide Felder
    sind Pflicht mit festen Werten.
    """
    roh = _roh_befunde(v, ohne_zustand)
    stufen = einstellung(board)
    ueberstimmt = {u.code for u in v.ueberstimmungen.all()} if v.pk else set()
    befunde = []
    for b in roh:
        stufe = stufen.stufe(b.code)
        if stufe == AUS:
            continue
        befunde.append(Befund(b.code, b.text, stufe, b.code in ueberstimmt and b.code not in ZUSTAND))
    return befunde


def sperrende(befunde: list[Befund]) -> list[Befund]:
    return [b for b in befunde if b.schwere == SPERRT and not b.ueberstimmt]


def _roh_befunde(v: Verbindung, ohne_zustand: bool) -> list[Befund]:
    befunde: list[Befund] = []
    belege = list(v.belege.all())
    personen = [e for e in (v.von, v.nach) if e.typ == "person"]
    privat = [e for e in personen if e.ist_privatperson]

    # Regel 1: keine Verbindung ohne Quelle, jede Quelle nachprüfbar und archiviert.
    if not belege:
        befunde.append(Befund("ohne_quelle", "Kein Beleg. Ohne Quelle geht kein Faden raus."))
    for beleg in belege:
        q = beleg.quelle
        kopie = any(
            s.status == "fertig" and s.art in ("original", "anhang") for s in q.sicherungen.all()
        )
        if not (q.url or q.datei_url or kopie):
            befunde.append(Befund("quelle_ohne_adresse", f"Quelle „{q.titel}“ hat weder Link noch Datei."))
        if not q.abgerufen_am:
            befunde.append(Befund("quelle_ohne_abruf", f"Quelle „{q.titel}“ ohne Abrufdatum."))
        if q.url and not q.archiv_url:
            befunde.append(Befund("quelle_ohne_archiv", f"Quelle „{q.titel}“ ohne Archivkopie."))

    # Regel 3: Verdacht gegen eine Person nur mit Anhörung und zwei unabhängigen Quellen.
    if v.aussageart == Aussageart.VERDACHT and personen:
        if not v.anhoerung_angefragt_am:
            befunde.append(Befund("verdacht_ohne_anhoerung", "Verdacht gegen eine Person ohne Anhörung."))
        if unabhaengige_quellen(v) < VERDACHT_MIN_QUELLEN:
            befunde.append(
                Befund(
                    "verdacht_zu_duenn",
                    f"Verdacht braucht mindestens {VERDACHT_MIN_QUELLEN} unabhängige Quellen.",
                )
            )

    # Regel 4: Zeitraum. Ein früheres Amt darf nie wie ein heutiges aussehen.
    if not v.start:
        befunde.append(Befund("ohne_start", "Kein Startdatum."))
    if v.aktuell and v.ende:
        befunde.append(Befund("zeitraum_widerspruch", "„Aktuell“ und Enddatum zugleich."))
    if not v.aktuell and not v.ende and v.typ not in (VerbindungTyp.AUSSAGE, VerbindungTyp.GESETZ_BETRIFFT):
        befunde.append(Befund("zeitraum_offen", "Weder „aktuell“ noch Enddatum gesetzt."))
    if v.start and v.ende and v.ende < v.start:
        befunde.append(Befund("zeitraum_verkehrt", "Ende liegt vor dem Start."))

    # Regel 6: Privatpersonen. Verdacht und Familie über sie gehen nie raus.
    if privat and v.aussageart == Aussageart.VERDACHT:
        befunde.append(Befund("verdacht_privatperson", "Kein Verdacht gegen Privatpersonen."))
    if privat and v.typ == VerbindungTyp.FAMILIE:
        befunde.append(Befund("familie_privatperson", "Familienbande von Privatpersonen bleiben intern."))

    if ohne_zustand:
        return befunde
    # Regel 7: Freigabe. Faden und beide Enden müssen von einem Menschen freigegeben sein.
    from .beweisschicht import veraendert_seit_freigabe

    if v.status == Status.FREIGEGEBEN and veraendert_seit_freigabe(v, "faden"):
        befunde.append(Befund("veraendert_seit_freigabe", "Seit der Freigabe verändert: neu unterschreiben."))
    if v.status != Status.FREIGEGEBEN:
        befunde.append(Befund("faden_nicht_freigegeben", "Faden ist nicht freigegeben."))
    for e in (v.von, v.nach):
        if e.status != Status.FREIGEGEBEN:
            befunde.append(Befund("karte_nicht_freigegeben", f"„{e.name}“ ist nicht freigegeben."))
        elif veraendert_seit_freigabe(e, "karte"):
            befunde.append(Befund("veraendert_seit_freigabe", f"„{e.name}“ seit der Freigabe verändert."))

    return befunde


def darf_oeffentlich(v: Verbindung, board=None) -> bool:
    return not sperrende(pruefe_verbindung(v, board))
