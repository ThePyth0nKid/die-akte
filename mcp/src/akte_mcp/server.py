# SPDX-License-Identifier: MIT
"""MCP-Server für Die Akte.

Start (stdio):  AKTE_BASIS=http://localhost:8080 [AKTE_TOKEN=…] akte-mcp

Ohne Token sind nur Lesewerkzeuge da (was Besucher ohne Konto sehen dürfen). Mit Token kommen die Werkzeuge der
Redaktion dazu; alles, was sie anlegen, ist ein Entwurf. Freigeben, Löschen und Öffentlich-Schalten gibt es hier
absichtlich nicht: Das entscheidet ein Mensch in der Oberfläche, und der Server der Akte lehnt es für Tokens ab.
"""

from __future__ import annotations

import os
import sys
import time
from collections import deque
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from akte_client import Akte, AkteFehler
from akte_client import aktionen

REGELN = """Belegregeln der Akte (Kurzfassung; die Wand prüft sie je Board, ein Mensch entscheidet):
1. Kein Faden ohne Quelle. Ein belegter Faden trägt mindestens einen Beleg: Quelle + wörtliches Zitat + Fundstelle.
2. zitat_woertlich ist nur der Originalwortlaut der Quelle – nie eine Zusammenfassung, nie ein Skriptsatz.
   Fehlt der Wortlaut: Zitat leer lassen und in der Fundstelle sagen, warum.
3. Aussageart ehrlich setzen: belegt nur mit Beleg; verdacht gegen Personen braucht Anhörung und zwei unabhängige
   Quellen; meinung nur, wenn die Redaktion es als ihre Einschätzung markiert.
4. Verfahrensstand statt Absicht: beantragt ≠ genehmigt, Entwurf ≠ Gesetz, Festnahme ≠ Anklage, erwähnt ≠ Kontakt.
5. Privatpersonen (oeffentliche_person = false) nie mit Verdacht oder Familie verbinden; öffentlich nur Initialen.
6. Alles, was du anlegst, ist ein Entwurf. Freigeben tut ein Mensch. Melde offene Befunde, statt sie wegzureden.
"""

ANWEISUNG = ("Du arbeitest an einer Ermittler-Wand („Die Akte“). " + REGELN +
             "Arbeitsweise: erst lesen (boards_liste, wand_lesen, suche), dann Quellen anlegen, dann Fäden mit Belegen, "
             "dann pruefung. Größere Mengen als import_paket, immer zuerst mit dry_run=true.")

LESEN = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
SCHREIBEN = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
SCHREIBEN_NETZ = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


def _kurz_wand(w: dict, voll: bool, max_karten: int) -> dict:
    """Die Wand kompakt: was ein Modell zum Arbeiten braucht, ohne Koordinaten-Ballast."""
    karten = []
    for k in w.get("karten", [])[: max(1, max_karten)]:
        e = k.get("entitaet_detail", {})
        karte = {"id": k.get("entitaet"), "name": e.get("name"), "typ": e.get("typ"),
                 "kurz": e.get("kurzbeschreibung", ""), "oeffentliche_person": e.get("oeffentliche_person"),
                 "status": e.get("status")}
        if voll:
            karte.update({"x": k.get("x"), "y": k.get("y"), "bild_nachweis": e.get("bild_nachweis", "")})
        karten.append(karte)
    faeden = []
    for f in w.get("faeden", []):
        faden = {"id": f.get("id"), "von": f.get("von"), "nach": f.get("nach"), "typ": f.get("typ"),
                 "beschreibung": f.get("beschreibung"), "aussageart": f.get("aussageart"), "status": f.get("status"),
                 "start": f.get("start"), "ende": f.get("ende"), "aktuell": f.get("aktuell"),
                 "belege": [{"beleg": b.get("id"), "quelle": b.get("quelle"),
                             "titel": (b.get("quelle_detail") or {}).get("titel"),
                             "url": (b.get("quelle_detail") or {}).get("url"),
                             "zitat": b.get("zitat_woertlich", ""), "fundstelle": b.get("fundstelle", "")}
                            for b in f.get("belege", [])]}
        if f.get("befunde"):
            faden["befunde"] = [b.get("text") for b in f["befunde"]]
        faeden.append(faden)
    return {
        "board": {k: w.get("board", {}).get(k) for k in ("titel", "slug", "beschreibung")},
        "karten": karten, "karten_gesamt": len(w.get("karten", [])),
        "faeden": faeden,
        "rahmen": [{"titel": r.get("titel"), "farbe": r.get("farbe", "")} for r in w.get("rahmen", [])],
        "mappen": [{"ziel": m.get("ziel"), "titel": m.get("titel")} for m in w.get("mappen", [])],
        "zettel": [{"art": z.get("art"), "text": z.get("text")} for z in w.get("zettel", [])],
        "fahrten": [{"id": f.get("id"), "titel": f.get("titel")} for f in w.get("fahrten", [])],
    }


class _Lesespeicher:
    """Öffentliche Wände für Suche und Weg im Lesemodus, 60 s zwischengespeichert."""

    def __init__(self, akte: Akte, sekunden: float = 60):
        self.akte, self.sekunden, self._stand, self._waende = akte, sekunden, 0.0, []

    def waende(self) -> list[dict]:
        if time.monotonic() - self._stand > self.sekunden:
            self._waende = [self.akte.wand(b["slug"]) for b in self.akte.boards()]
            self._stand = time.monotonic()
        return self._waende


def _fehler(e: Exception) -> dict:
    if isinstance(e, AkteFehler):
        return {"fehler": True, "status": e.status, "antwort": e.daten}
    return {"fehler": True, "text": str(e)}


def bauen(akte: Akte) -> FastMCP:
    """Server bauen. Ob die Schreibwerkzeuge da sind, entscheidet allein, ob ``akte`` ein Token hat."""
    mcp = FastMCP("die-akte", instructions=ANWEISUNG)
    lesespeicher = _Lesespeicher(akte)

    # ─── Lesen (beide Modi) ────────────────────────────────────────────────
    @mcp.tool(annotations=LESEN)
    def boards_liste() -> dict:
        """Alle Boards, die du lesen darfst, mit Eltern-Boards (Mappen-Baum)."""
        try:
            return {"boards": [{k: b.get(k) for k in ("titel", "slug", "beschreibung", "eltern", "oeffentlich")}
                               for b in akte.boards()]}
        except Exception as e:  # noqa: BLE001 — Fehler gehen als Daten an das Modell, nicht als Absturz
            return _fehler(e)

    @mcp.tool(annotations=LESEN)
    def wand_lesen(board: str, voll: bool = False, max_karten: int = 200) -> dict:
        """Eine Wand: Karten (id, name, typ), Fäden mit Belegen (Quelle, Zitat, Fundstelle) und offenen Befunden,
        Rahmen, Mappen, Zettel, Fahrten. ``voll`` liefert zusätzlich Positionen."""
        try:
            return _kurz_wand(akte.wand(board), voll, max_karten)
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=LESEN)
    def suche(q: str, typ: str = "") -> dict:
        """Karten nach Namen oder Beschreibung suchen. ``typ``: person, organisation, firma, behoerde, partei,
        ereignis, gesetz, system, ort, dokument."""
        try:
            if akte.mit_token:
                treffer = akte.entitaeten(q=q, typ=typ)
                return {"treffer": [{k: e.get(k) for k in ("id", "name", "typ", "slug", "status")} for e in treffer[:50]]}
            q_klein = q.lower()
            gesehen, treffer = set(), []
            for w in lesespeicher.waende():
                for k in w.get("karten", []):
                    e = k.get("entitaet_detail", {})
                    if (q_klein in (e.get("name") or "").lower() or q_klein in (e.get("kurzbeschreibung") or "").lower()) \
                            and (not typ or e.get("typ") == typ) and k.get("entitaet") not in gesehen:
                        gesehen.add(k.get("entitaet"))
                        treffer.append({"id": k.get("entitaet"), "name": e.get("name"), "typ": e.get("typ"),
                                        "board": w.get("board", {}).get("slug")})
            return {"treffer": treffer[:50]}
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=LESEN)
    def weg(von: str, nach: str, nur_belegt: bool = True, max_tiefe: int = 4) -> dict:
        """Kürzester Weg über Fäden zwischen zwei Karten (Namen). Zeigt, wie zwei Akteure verbunden sind."""
        try:
            max_tiefe = max(1, min(max_tiefe, 6))
            if akte.mit_token:
                a, b = akte.entitaet_finden(von), akte.entitaet_finden(nach)
                if not a or not b:
                    return {"fehler": True, "text": f"Unbekannt: {von if not a else nach}"}
                return akte.weg(a["id"], b["id"], nur_belegt, max_tiefe)
            return _weg_oeffentlich(lesespeicher.waende(), von, nach, nur_belegt, max_tiefe)
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.resource("akte://regeln", name="Belegregeln", mime_type="text/plain")
    def regeln() -> str:
        return REGELN

    if not akte.mit_token:
        return mcp

    # ─── Zuarbeiten (nur mit Token, alles als Entwurf) ─────────────────────
    @mcp.tool(annotations=LESEN)
    def pruefung(board: str) -> dict:
        """Offene Befunde je Faden eines Boards (fehlende Belege, Archivkopien, Verdachtsregeln, Privatpersonen …).
        Befunde beraten; ein Mensch entscheidet."""
        try:
            p = akte.pruefung(board)
            return {"ohne_befund": sum(1 for f in p["faeden"] if f["ok"]), "gesamt": len(p["faeden"]),
                    "offen": [{"faden": f.get("id"), "titel": f.get("titel"),
                               "befunde": [b.get("text") for b in f.get("befunde", [])]}
                              for f in p["faeden"] if not f["ok"]]}
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN_NETZ)
    def quelle_anlegen(titel: str, abgerufen_am: str, url: str = "", herausgeber: str = "",
                       guete: Literal["primaer", "sekundaer"] = "sekundaer", veroeffentlicht_am: str = "") -> dict:
        """Quelle anlegen (oder die vorhandene mit derselben URL holen). Danach sichert die Akte das Original mit
        Prüfsumme und eine Archivkopie. Datumsangaben als JJJJ-MM-TT; ``abgerufen_am`` ist Pflicht."""
        if url and not url.startswith(("http://", "https://")):
            return {"fehler": True, "text": "Nur http(s)-Adressen."}
        try:
            q, neu = akte.quelle(titel, url, herausgeber, guete, abgerufen_am, veroeffentlicht_am or None)
            return {"quelle": {k: q.get(k) for k in ("id", "titel", "url", "herausgeber", "guete")}, "neu": neu}
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN)
    def karte_anlegen(name: str, typ: Literal["person", "organisation", "firma", "behoerde", "partei", "ereignis",
                                              "gesetz", "system", "ort", "dokument"],
                      oeffentliche_person: bool, kurz: str = "", board: str = "") -> dict:
        """Karte als Entwurf anlegen (oder vorhandene holen) und optional auf ein Board legen.
        ``oeffentliche_person``: nur true für Menschen mit öffentlicher Rolle; Privatpersonen erscheinen öffentlich
        nur mit Initialen und dürfen nie mit Verdacht oder Familie verbunden werden."""
        try:
            e, neu = akte.entitaet(name, typ, kurz, oeffentliche_person)
            if board:
                akte.auf_board(board, e["id"])
            return {"karte": {k: e.get(k) for k in ("id", "name", "typ", "status")}, "neu": neu,
                    "auf_board": board or None}
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN)
    def faden_ziehen(von: str, nach: str,
                     typ: Literal["amt", "eigentum", "finanzierung", "mitgliedschaft", "auftrag", "lobby",
                                  "gesetz_betrifft", "aussage", "familie", "sonstiges"],
                     beschreibung: str, start: str,
                     aussageart: Literal["belegt", "verdacht", "meinung"] = "belegt",
                     belege: list[dict[str, Any]] | None = None, ende: str = "", aktuell: bool = False) -> dict:
        """Faden (Verbindung) zwischen zwei Karten als Entwurf. ``beschreibung`` kurz (2–6 Wörter).
        ``belege``: Liste von {quelle: <Quellen-ID>, zitat_woertlich: "<Originalwortlaut>", fundstelle: "S. 3"}.
        Gibt die offenen Befunde der Prüfung zurück; danach zitat_pruefen für jeden Beleg mit Zitat."""
        belege = belege or []
        warnung = ""
        if aussageart == "belegt" and not belege:
            warnung = "Belegt ohne Beleg: Die Prüfung meldet das als offenen Befund. Quelle ergänzen."
        if any(not isinstance(b, dict) or "quelle" not in b for b in belege):
            return {"fehler": True, "text": "Jeder Beleg braucht 'quelle' (ID der Quelle)."}
        try:
            v = aktionen.faden_ziehen(akte, von, nach, typ=typ, beschreibung=beschreibung, aussageart=aussageart,
                                      start=start or None, ende=ende or None, aktuell=aktuell, belege=belege)
            antwort = {"faden": v.get("id"), "status": v.get("status"),
                       "belege": [{"beleg": b.get("id"), "quelle": b.get("quelle")} for b in v.get("belege", [])],
                       "befunde": [b.get("text") for b in v.get("befunde", [])]}
            if warnung:
                antwort["warnung"] = warnung
            return antwort
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN)
    def beleg_hinzufuegen(faden: int, quelle: int, zitat_woertlich: str = "", fundstelle: str = "") -> dict:
        """Weiteren Beleg an einen Faden hängen (je Faden und Quelle ein Beleg); die übrigen Belege bleiben."""
        try:
            v = aktionen.beleg_hinzufuegen(akte, faden, quelle, zitat_woertlich, fundstelle)
            return {"faden": v.get("id"), "belege": len(v.get("belege", [])),
                    "befunde": [b.get("text") for b in v.get("befunde", [])]}
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN_NETZ)
    async def zitat_pruefen(beleg: int, quelle: int, warten_s: int = 60) -> dict:
        """Prüfen lassen, ob das Zitat eines Belegs wörtlich an der Quelle steht (Fundstelle mit Markierung).
        Ergebnis: gefunden, nicht_gefunden_oder_fehler oder laeuft. Wartet in einem eigenen Thread, damit der
        Server währenddessen andere Aufrufe beantwortet."""
        import anyio

        try:
            return await anyio.to_thread.run_sync(
                lambda: aktionen.zitat_pruefen(akte, beleg, quelle, max(0, min(warten_s, 180))))
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN)
    def gruppen_setzen(board: str, gruppen: dict[str, Any]) -> dict:
        """Karten in Themen-Rahmen ordnen und aufräumen: {Titel: [Kartennamen]} oder
        {Titel: {farbe: "#RRGGBB", karten: [...]}}. ``"@slug"`` legt die Mappe eines Boards in den Rahmen."""
        try:
            return aktionen.gruppen_setzen(akte, board, gruppen)
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN)
    def aufraeumen(board: str) -> dict:
        """Wand ohne Überlappung neu ordnen (Rahmen bleiben Gruppen)."""
        try:
            w = akte.post(f"/boards/{board}/aufraeumen/")
            return {"karten": len(w["karten"]), "rahmen": len(w["rahmen"]), "zettel": len(w["zettel"])}
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN)
    def fahrt_anlegen(board: str, titel: str, stationen: list[dict[str, Any]],
                      format: Literal["16:9", "9:16", "1:1", "oben"] = "16:9") -> dict:
        """Kamerafahrt für ein Video: Stationen [{fokus: [Kartennamen], stichwort, dauer_ms?, zoom?, text?,
        beweis?: "<Quellentitel oder ID>", zitat?: "<Originalwortlaut>"}]. Leerer Fokus = ganze Wand.
        Gleicher Titel ersetzt die alte Fahrt."""
        if any("einspieler" in s for s in stationen if isinstance(s, dict)):
            return {"fehler": True, "text": "Einspieler (lokale Videodateien) legt nur ein Mensch fest."}
        try:
            f = akte.post(f"/boards/{board}/fahrten/aus-beschreibung/",
                          {"titel": titel, "format": format, "stationen": stationen})
            return {"fahrt": f.get("id"), "titel": f.get("titel"), "stationen": len(f.get("stationen", []))}
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN)
    def zettel_anlegen(board: str, art: Literal["notiz", "frage"], text: str) -> dict:
        """Zettel auf ein Arbeits-Board: notiz und frage bleiben intern. Meinungs-Zettel (für Leser sichtbar)
        schreibt nur ein Mensch in der Oberfläche; veröffentlichte Boards ändern Werkzeuge nicht."""
        if art not in ("notiz", "frage"):
            return {"fehler": True, "text": "Werkzeuge legen nur Notizen oder Fragen an."}
        try:
            return aktionen.zettel_anlegen(akte, [{"board": board, "art": art, "text": text}])
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN_NETZ)
    def import_paket(paket: dict[str, Any], dry_run: bool = True, bestaetigt: bool = False) -> dict:
        """Größere Mengen auf einmal: {board?: {titel, slug, eltern?}, quellen: [{schluessel, titel, url, …}],
        entitaeten: [{schluessel, name, typ, oeffentliche_person, …}], verbindungen: [{von, nach, typ,
        beschreibung, belege: [{quelle: <schluessel>, zitat_woertlich, fundstelle}]}]}.
        Erst mit dry_run=true prüfen; geschrieben wird nur mit dry_run=false UND bestaetigt=true."""
        if not dry_run and not bestaetigt:
            return {"fehler": True, "text": "Echter Import nur mit bestaetigt=true (nach einem Probelauf)."}
        try:
            return aktionen.importieren(akte, paket, trocken=dry_run)
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    @mcp.tool(annotations=SCHREIBEN_NETZ)
    def sichern(quelle: int) -> dict:
        """Beweissicherung einer Quelle neu anstoßen (Original mit Prüfsumme, Archivkopie, Fundstellen)."""
        try:
            akte.post(f"/quellen/{quelle}/sichern/")
            return {"angestossen": True, "quelle": quelle}
        except Exception as e:  # noqa: BLE001
            return _fehler(e)

    return mcp


def _weg_oeffentlich(waende: list[dict], von: str, nach: str, nur_belegt: bool, max_tiefe: int) -> dict:
    """Breitensuche über die öffentlichen Wände (Kennungen gelten je Wand, darum über Namen verbunden)."""
    kanten: dict[str, set[str]] = {}
    for w in waende:
        namen = {k.get("entitaet"): (k.get("entitaet_detail") or {}).get("name", "") for k in w.get("karten", [])}
        for f in w.get("faeden", []):
            if nur_belegt and f.get("aussageart") != "belegt":
                continue
            a, b = namen.get(f.get("von")), namen.get(f.get("nach"))
            if a and b:
                kanten.setdefault(a.lower(), set()).add(b.lower())
                kanten.setdefault(b.lower(), set()).add(a.lower())
    start, ziel = von.lower(), nach.lower()
    if start not in kanten or ziel not in kanten:
        return {"gefunden": False, "weg": []}
    vorher: dict[str, str | None] = {start: None}
    schlange = deque([(start, 0)])
    while schlange:
        knoten, tiefe = schlange.popleft()
        if knoten == ziel:
            weg = []
            while knoten is not None:
                weg.append(knoten)
                knoten = vorher[knoten]
            return {"gefunden": True, "weg": list(reversed(weg))}
        if tiefe >= max_tiefe:
            continue
        for n in sorted(kanten.get(knoten, ())):
            if n not in vorher:
                vorher[n] = knoten
                schlange.append((n, tiefe + 1))
    return {"gefunden": False, "weg": []}


def main() -> None:
    basis = os.environ.get("AKTE_BASIS", "").strip()
    if not basis:
        print("AKTE_BASIS fehlt (Adresse deiner Akte, z. B. http://localhost:8080).", file=sys.stderr)
        raise SystemExit(2)
    akte = Akte(basis, os.environ.get("AKTE_TOKEN") or None, kennung="akte-mcp/0.1")
    bauen(akte).run("stdio")


if __name__ == "__main__":
    main()
