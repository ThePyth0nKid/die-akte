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
    wand = _rufe(leser, "wand_lesen", {"board": "offen"})
    assert [k["name"] for k in wand["karten"]] == ["Max Mustermann"]
    assert _rufe(leser, "suche", {"q": "muster"})["treffer"][0]["name"] == "Max Mustermann"
