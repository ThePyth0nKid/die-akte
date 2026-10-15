"""Startdaten in die Akte laden — alles als Entwurf, freigeben muss die Redaktion.

    python manage.py akte_import akte/fixtures/nordlicht_start.json

Wiederholbar: vorhandene Entitäten (Slug), Quellen (Link + Titel) und Fäden
(von, nach, Typ, Beschriftung) werden wiederverwendet statt doppelt angelegt.
Bereits Freigegebenes wird nie überschrieben.

Zusätzlich: ``board.eltern`` (Slug oder Liste) legt das Board als Mappe auf diese Wände;
``"auf_board": false`` an einer Entität lässt sie im Faden, aber nicht als Karte auf dem Board;
``betrag``/``waehrung`` an einem Faden; Zeitraum je Faden mit ``start`` und ``bis`` (JJJJ-MM-TT, ``ende`` als
alter Name) und ``aktuell`` (true/false). Ein ungültiger Zeitraum bricht ab, bevor etwas geschrieben wird.
"""

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import URLValidator
from django.db import transaction

from akte.mappen import kinder_aus, wuerde_zyklus
from akte.models import (
    Beleg,
    Board,
    BoardKarte,
    Entitaet,
    Mappe,
    Quelle,
    Status,
    Verbindung,
    slug_reserviert,
)

_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: Längstes wörtliches Zitat je Beleg (wie die API, ``serializers.ZITAT_MAX``).
ZITAT_MAX = 5000


def _datum(wert, feld: str, wo: str) -> date | None:
    if wert in (None, ""):
        return None
    if not isinstance(wert, str) or not _DATUM.match(wert):
        raise CommandError(f"{wo}: {feld} als Datum JJJJ-MM-TT angeben, nicht {wert!r}.")
    try:
        return date.fromisoformat(wert)
    except ValueError:
        raise CommandError(f"{wo}: {feld} {wert!r} gibt es nicht im Kalender.") from None


def zeitraum(v: dict, wo: str) -> dict:
    """``start``, ``bis`` (oder ``ende``) und ``aktuell`` eines Fadens prüfen → Felder für das Modell."""
    # Leeres „bis“ zählt wie keines (wie im MCP-Client): dann gilt „ende“, falls angegeben.
    bis, alt = v.get("bis"), v.get("ende")
    if bis not in (None, "") and alt not in (None, "") and bis != alt:
        raise CommandError(f"{wo}: „bis“ und „ende“ widersprechen sich; nur „bis“ angeben.")
    start = _datum(v.get("start"), "start", wo)
    ende = _datum(bis if bis not in (None, "") else alt, "bis", wo)
    aktuell = v.get("aktuell", False)
    if not isinstance(aktuell, bool):
        raise CommandError(f"{wo}: aktuell ist true oder false, nicht {aktuell!r}.")
    if aktuell and ende:
        raise CommandError(f"{wo}: „aktuell“ und „bis“ zugleich. Besteht die Verbindung noch, „bis“ weglassen.")
    if start and ende and ende < start:
        raise CommandError(f"{wo}: „bis“ ({ende}) liegt vor „start“ ({start}).")
    return {"start": start, "ende": ende, "aktuell": aktuell}


class Command(BaseCommand):
    help = "Lädt eine Startdatei (Board, Quellen, Entitäten, Fäden) als Entwurf in die Akte."

    def add_arguments(self, parser):
        parser.add_argument("datei")

    @transaction.atomic
    def handle(self, datei, **_):
        pfad = Path(datei)
        if not pfad.exists():
            raise CommandError(f"Datei fehlt: {pfad}")
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        zaehler = {"quellen": 0, "entitaeten": 0, "verbindungen": 0, "belege": 0}
        # Zeiträume vorab prüfen: lieber gar nichts schreiben als die Hälfte.
        zeitraeume = [zeitraum(v, f"Faden {v.get('von')} → {v.get('nach')}") for v in daten.get("verbindungen", [])]
        for v in daten.get("verbindungen", []):
            for b in v.get("belege", []):
                if len(str(b.get("zitat_woertlich") or "")) > ZITAT_MAX:
                    raise CommandError(f"Faden {v.get('von')} → {v.get('nach')}: Zitat länger als {ZITAT_MAX} Zeichen. "
                                       "Nur die tragende Stelle zitieren, Ausgelassenes mit […].")

        # Dieselbe Link-Prüfung wie in der API: nur http(s)/ftp, nie javascript: oder data:.
        link_pruefen = URLValidator()
        quellen = {}
        for q in daten.get("quellen", []):
            if q.get("url"):
                try:
                    link_pruefen(q["url"])
                except ValidationError:
                    raise CommandError(f"Ungültiger Link in Quelle {q.get('schluessel')!r}: {q['url']!r}") from None
            felder = {k: q.get(k) for k in ("herausgeber", "veroeffentlicht_am", "abgerufen_am", "guete")}
            felder = {k: v for k, v in felder.items() if v is not None}
            obj, neu = Quelle.objects.get_or_create(url=q.get("url", ""), titel=q["titel"], defaults=felder)
            quellen[q["schluessel"]] = obj
            zaehler["quellen"] += neu

        entitaeten = {}
        for e in daten.get("entitaeten", []):
            obj, neu = Entitaet.objects.get_or_create(
                slug=e["schluessel"],
                defaults={
                    "typ": e["typ"],
                    "name": e["name"],
                    "kurzbeschreibung": e.get("kurzbeschreibung", "")[:300],
                    "notiz_md": e.get("notiz_md", ""),
                    "oeffentliche_person": bool(e.get("oeffentliche_person", False)),
                    "status": Status.ENTWURF,
                },
            )
            entitaeten[e["schluessel"]] = obj
            zaehler["entitaeten"] += neu

        for v, zeit in zip(daten.get("verbindungen", []), zeitraeume):
            try:
                von, nach = entitaeten[v["von"]], entitaeten[v["nach"]]
            except KeyError as fehlt:
                raise CommandError(f"Unbekannte Entität {fehlt} in Faden {v}") from None
            if v.get("betrag") not in (None, ""):
                try:
                    Decimal(str(v["betrag"]))
                except InvalidOperation:
                    raise CommandError(f"Betrag {v['betrag']!r} ist keine Zahl (Punkt als Dezimalzeichen) in Faden {v['von']} → {v['nach']}") from None
            obj, neu = Verbindung.objects.get_or_create(
                von=von, nach=nach, typ=v["typ"], beschreibung=v.get("beschreibung", "")[:300],
                defaults={
                    **zeit,
                    "betrag": v.get("betrag"),
                    "waehrung": (v.get("waehrung") or "")[:3],
                    "aussageart": v.get("aussageart", "belegt"),
                    "status": Status.ENTWURF,
                },
            )
            zaehler["verbindungen"] += neu
            if obj.status == Status.FREIGEGEBEN:
                continue
            for b in v.get("belege", []):
                try:
                    quelle = quellen[b["quelle"]]
                except KeyError:
                    raise CommandError(f"Unbekannte Quelle {b['quelle']!r}") from None
                _, neu_beleg = Beleg.objects.get_or_create(
                    verbindung=obj, quelle=quelle,
                    defaults={"zitat_woertlich": b.get("zitat_woertlich", ""), "fundstelle": b.get("fundstelle", "")[:120]},
                )
                zaehler["belege"] += neu_beleg

        if "board" in daten:
            b = daten["board"]
            if slug_reserviert(b["slug"]):
                raise CommandError(f"Board-Kennung {b['slug']!r} braucht die Oberfläche selbst.")
            board, _ = Board.objects.get_or_create(
                slug=b["slug"], defaults={"titel": b["titel"], "beschreibung": b.get("beschreibung", "")}
            )
            for e in daten.get("entitaeten", []):
                if not e.get("auf_board", True):
                    continue
                BoardKarte.objects.get_or_create(
                    board=board, entitaet=entitaeten[e["schluessel"]],
                    defaults={"x": e.get("x", 0), "y": e.get("y", 0)},
                )
            eltern = b.get("eltern") or []
            kinder = kinder_aus(Mappe.objects.values_list("board_id", "ziel_id"))
            for slug in [eltern] if isinstance(eltern, str) else eltern:
                oben = Board.objects.filter(slug=slug).first()
                if oben is None:
                    raise CommandError(f"Eltern-Board {slug!r} gibt es nicht.")
                if Mappe.objects.filter(board=oben, ziel=board).exists():
                    continue
                if wuerde_zyklus(oben.id, board.id, kinder):
                    raise CommandError(f"{board.slug!r} als Mappe auf {slug!r} ergäbe einen Kreis.")
                Mappe.objects.create(board=oben, ziel=board)
                kinder.setdefault(oben.id, []).append(board.id)

        self.stdout.write(self.style.SUCCESS(
            "Neu: " + ", ".join(f"{n} {k}" for k, n in zaehler.items()) + ". Alles als Entwurf."
        ))
