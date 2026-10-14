"""Der MCP-Server gegen ein echtes Backend: Lesemodus, Entwürfe, Probelauf, und was Werkzeuge nicht dürfen."""

from __future__ import annotations

import asyncio
import json
import subprocess

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from akte_client import Akte, AkteFehler
from akte_mcp.server import bauen

pytestmark = pytest.mark.integration

LESEWERKZEUGE = {"boards_liste", "wand_lesen", "suche", "weg"}


def _rufe(server, name: str, argumente: dict | None = None) -> dict:
    async def lauf():
        async with create_connected_server_and_client_session(server._mcp_server) as sitzung:
            if name == "__werkzeuge__":
                return {"namen": sorted(t.name for t in (await sitzung.list_tools()).tools)}
            ergebnis = await sitzung.call_tool(name, argumente or {})
            if ergebnis.structuredContent is not None:
                return ergebnis.structuredContent
            return json.loads(ergebnis.content[0].text)
    return asyncio.run(lauf())


def test_lesemodus_hat_nur_lesewerkzeuge(backend):
    server = bauen(Akte(backend["basis"]))
    assert set(_rufe(server, "__werkzeuge__")["namen"]) == LESEWERKZEUGE


def test_bearbeiten_hat_keine_freigabe_und_kein_loeschen(backend):
    namen = set(_rufe(bauen(Akte(backend["basis"], backend["token"])), "__werkzeuge__")["namen"])
    assert LESEWERKZEUGE <= namen
    assert {"faden_ziehen", "quelle_anlegen", "import_paket", "zitat_pruefen"} <= namen
    assert not any(w in n for n in namen for w in ("freigeb", "loesch", "delete", "status", "oeffentlich"))


def test_ablauf_entwurf_mit_beleg(backend):
    akte = Akte(backend["basis"], backend["token"])
    akte.post("/boards/", {"titel": "Musterhafen", "slug": "musterhafen"})
    server = bauen(akte)

    a = _rufe(server, "karte_anlegen", {"name": "Senat Musterhafen", "typ": "behoerde",
                                        "oeffentliche_person": False, "board": "musterhafen"})
    b = _rufe(server, "karte_anlegen", {"name": "Nordlicht Analytik GmbH", "typ": "firma",
                                        "oeffentliche_person": False, "board": "musterhafen"})
    assert a["neu"] and b["neu"] and a["karte"]["status"] == "entwurf"

    q = _rufe(server, "quelle_anlegen", {"titel": "Drucksache 9/1234", "abgerufen_am": "2026-10-01",
                                         "url": "https://buergerschaft.beispiel.test/drs-9-1234.pdf",
                                         "herausgeber": "Bürgerschaft", "guete": "primaer"})
    quelle = q["quelle"]["id"]

    f = _rufe(server, "faden_ziehen", {"von": "Senat Musterhafen", "nach": "Nordlicht Analytik GmbH",
                                       "typ": "auftrag", "beschreibung": "beauftragt Analyse", "start": "2024-01-01",
                                       "belege": [{"quelle": quelle, "zitat_woertlich": "Der Senat beauftragt",
                                                   "fundstelle": "S. 3"}]})
    assert f["status"] == "entwurf" and len(f["belege"]) == 1 and "warnung" not in f

    ohne = _rufe(server, "faden_ziehen", {"von": "Nordlicht Analytik GmbH", "nach": "Senat Musterhafen",
                                          "typ": "lobby", "beschreibung": "wirbt", "start": "2024-02-01"})
    assert "warnung" in ohne and ohne["befunde"]

    wand = _rufe(server, "wand_lesen", {"board": "musterhafen"})
    assert {k["name"] for k in wand["karten"]} == {"Senat Musterhafen", "Nordlicht Analytik GmbH"}
    assert any(b["zitat"] == "Der Senat beauftragt" for faden in wand["faeden"] for b in faden["belege"])

    pruefung = _rufe(server, "pruefung", {"board": "musterhafen"})
    assert pruefung["gesamt"] == 2

    # Werkzeuge geben nicht frei: auch nicht am MCP vorbei über die API.
    with pytest.raises(AkteFehler) as fehler:
        akte.patch(f"/verbindungen/{f['faden']}/", {"status": "freigegeben"})
    assert fehler.value.status == 403


def test_import_erst_probelauf(backend):
    akte = Akte(backend["basis"], backend["token"])
    server = bauen(akte)
    paket = {"quellen": [{"schluessel": "q1", "titel": "Bericht Rechnungshof",
                          "url": "https://rechnungshof.beispiel.test/bericht-2025.pdf", "guete": "primaer"}],
             "entitaeten": [{"schluessel": "rh", "name": "Rechnungshof Musterhafen", "typ": "behoerde"},
                            {"schluessel": "kh", "name": "Kranich Holding AG", "typ": "firma"}],
             "verbindungen": [{"von": "rh", "nach": "kh", "typ": "aussage", "beschreibung": "rügt Vergabe",
                               "start": "2025-03-01",
                               "belege": [{"quelle": "q1", "zitat_woertlich": "Die Vergabe war fehlerhaft."}]}]}
    vorher = len(akte.get("/verbindungen/"))
    probe = _rufe(server, "import_paket", {"paket": paket})
    assert probe["trocken"] and probe["faeden_neu"] == 1 and len(probe["karten_neu"]) == 2
    assert len(akte.get("/verbindungen/")) == vorher

    ohne_ja = _rufe(server, "import_paket", {"paket": paket, "dry_run": False})
    assert ohne_ja["fehler"]
    echt = _rufe(server, "import_paket", {"paket": paket, "dry_run": False, "bestaetigt": True})
    assert not echt["trocken"] and echt["faeden_neu"] == 1
    assert len(akte.get("/verbindungen/")) == vorher + 1

    kaputt = {"quellen": [], "entitaeten": [], "verbindungen": [{"von": "x", "nach": "y", "typ": "sonstiges"}]}
    assert _rufe(server, "import_paket", {"paket": kaputt})["fehler"]


def _pdf(*zeilen: str) -> bytes:
    """Kleinstes PDF mit einer Seite Text (pdfium repariert die fehlenden Querverweise selbst)."""
    weitere = "".join(f" 0 -14 Td ({z}) Tj" for z in zeilen[1:])
    inhalt = f"BT /F1 12 Tf 60 700 Td ({zeilen[0]}) Tj{weitere} ET".encode("latin-1")
    return b"".join([
        b"%PDF-1.4\n", b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        b"2 0 obj<</Type/Pages/Kids[4 0 R]/Count 1>>endobj\n",
        b"3 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n",
        b"4 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 5 0 R/Resources<</Font<</F1 3 0 R>>>>>>endobj\n",
        f"5 0 obj<</Length {len(inhalt)}>>stream\n".encode() + inhalt + b"\nendstream endobj\n",
        b"trailer<</Root 1 0 R>>\n%%EOF"])


def test_zitat_pruefen_antwortet_sofort(backend):
    import time

    akte = Akte(backend["basis"], backend["token"])
    server = bauen(akte)
    pdf = _pdf("Der Senat beauftragt die Nordlicht Analytik GmbH mit der Auswertung der", "Verkehrsdaten der EU-",
               "Verordnung entsprechend.")
    quelle = akte.anfrage("POST", "/quellen/aus-datei/", files={"datei": ("drs.pdf", pdf)},
                          data={"titel": "Drucksache 9/77"})
    for name, typ in (("Senat Pruefhafen", "behoerde"), ("Pruef Analytik GmbH", "firma")):
        _rufe(server, "karte_anlegen", {"name": name, "typ": typ, "oeffentliche_person": False})
    f = _rufe(server, "faden_ziehen", {
        "von": "Senat Pruefhafen", "nach": "Pruef Analytik GmbH", "typ": "auftrag", "beschreibung": "beauftragt",
        "start": "2024-01-01", "aktuell": True,
        "belege": [{"quelle": quelle["id"], "zitat_woertlich": "mit der Auswertung der Verkehrsdaten der "
                                                            "EU-Verordnung entsprechend", "fundstelle": "S. 1"}]})
    beleg = f["belege"][0]["beleg"]
    anfang = time.monotonic()
    gut = _rufe(server, "zitat_pruefen", {"beleg": beleg})
    assert time.monotonic() - anfang < 30
    assert gut["ergebnis"] == "gefunden", gut
    assert gut["fundstelle"]["seite"] == 1 and gut["grund"]

    # Eine Quelle ohne Link und ohne Datei: klare Antwort „nicht prüfbar“, kein Warten, kein „läuft“.
    leer = _rufe(server, "quelle_anlegen", {"titel": "Nur ein Titel", "abgerufen_am": "2026-10-14"})["quelle"]["id"]
    zwei = _rufe(server, "beleg_hinzufuegen", {"faden": f["faden"], "quelle": leer,
                                               "zitat_woertlich": "Irgendein Satz, der nirgends steht."})
    assert zwei["belege"] == 2
    ohne_kopie = next(b["id"] for b in akte.get(f"/verbindungen/{f['faden']}/")["belege"] if b["quelle"] == leer)
    ohne = _rufe(server, "zitat_pruefen", {"beleg": ohne_kopie, "quelle": 999})  # „quelle“ wird nicht mehr gebraucht
    assert ohne["ergebnis"] == "nicht_pruefbar" and ohne["naechster_schritt"]

    gesichert = _rufe(server, "sichern", {"quelle": quelle["id"]})
    assert gesichert.get("fehler") or gesichert["angestossen"]  # ohne Link: 400 als Daten, nie ein Hänger


def test_import_mit_zeitraum(backend):
    akte = Akte(backend["basis"], backend["token"])
    server = bauen(akte)
    paket = {"quellen": [], "entitaeten": [{"schluessel": "a", "name": "Zeitraum Amt", "typ": "behoerde"},
                                           {"schluessel": "b", "name": "Zeitraum GmbH", "typ": "firma"}],
             "verbindungen": [{"von": "a", "nach": "b", "typ": "auftrag", "beschreibung": "bis 2020",
                               "start": "2017-01-01", "bis": "2020-12-31"},
                              {"von": "b", "nach": "a", "typ": "lobby", "beschreibung": "seit 2021",
                               "start": "2021-03-01", "aktuell": True}]}
    assert _rufe(server, "import_paket", {"paket": {**paket, "verbindungen": [
        {**paket["verbindungen"][0], "aktuell": True}]}})["fehler"]
    echt = _rufe(server, "import_paket", {"paket": paket, "dry_run": False, "bestaetigt": True})
    assert echt["faeden_neu"] == 2 and echt["hinweise"] == []
    faeden = {f["beschreibung"]: f for f in akte.get("/verbindungen/")}
    assert (faeden["bis 2020"]["start"], faeden["bis 2020"]["ende"], faeden["bis 2020"]["aktuell"]) == (
        "2017-01-01", "2020-12-31", False)
    assert (faeden["seit 2021"]["ende"], faeden["seit 2021"]["aktuell"]) == (None, True)


def test_nicht_erreichbare_akte_meldet_sich_auf_deutsch():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    antwort = _rufe(bauen(Akte(f"http://127.0.0.1:{port}", "token")), "boards_liste")
    assert antwort["fehler"] and "nicht erreichbar" in antwort["text"]


def test_lesemodus_sieht_oeffentliche_wand(backend):
    akte = Akte(backend["basis"], backend["token"])
    akte.post("/boards/", {"titel": "Offen", "slug": "offen"})
    e, _ = akte.entitaet("Max Mustermann", "person", "Vorstand", True)
    akte.auf_board("offen", e["id"])
    # Öffentlich schalten ist Menschensache; hier tut es der Test direkt in der Datenbank.
    skript = "from akte.models import Board; Board.objects.filter(slug='offen').update(oeffentlich=True)"
    subprocess.run([backend["python"], "manage.py", "shell", "-c", skript], cwd=str(__import__("conftest").BACKEND),
                   env=backend["env"], check=True, capture_output=True)
    leser = bauen(Akte(backend["basis"]))
    assert "offen" in {b["slug"] for b in _rufe(leser, "boards_liste")["boards"]}
    # Der Entwurf des Werkzeugs ist für Leser unsichtbar, bis ein Mensch ihn freigibt.
    assert _rufe(leser, "wand_lesen", {"board": "offen"})["karten"] == []
    # .update() löst kein Signal aus: den Lese-Cache selbst ungültig machen (wie es die Freigabe-API tut).
    skript = ("from akte.models import Entitaet; from akte import lesecache; "
              "Entitaet.objects.filter(name='Max Mustermann').update(status='freigegeben'); lesecache.veraltet()")
    subprocess.run([backend["python"], "manage.py", "shell", "-c", skript], cwd=str(__import__("conftest").BACKEND),
                   env=backend["env"], check=True, capture_output=True)
    wand = _rufe(leser, "wand_lesen", {"board": "offen"})
    assert [k["name"] for k in wand["karten"]] == ["Max Mustermann"]
    assert _rufe(leser, "suche", {"q": "muster"})["treffer"][0]["name"] == "Max Mustermann"
