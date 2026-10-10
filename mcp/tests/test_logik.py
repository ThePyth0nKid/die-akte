"""Reine Logik ohne Netz: Fotos nur in leere Felder, Rahmen mit Farbe als Schild, Baum, Datenschutz, Weg."""

from akte_client import aktionen
from akte_client.cli import boards_baum
from akte_mcp.server import _weg_oeffentlich

FOTO = {"bild_url": "https://commons.wikimedia.org/wiki/Special:FilePath/X.jpg?width=800",
        "bild_nachweis": "Foto: A, CC BY 4.0, Wikimedia Commons", "wikidata_qid": "Q1"}


def test_bild_fuellt_leere_felder():
    assert aktionen.bild_aenderung({"id": 1, "status": "entwurf", "bild_url": "", "wikidata_qid": ""}, FOTO) == FOTO


def test_bild_ueberschreibt_kein_vorhandenes_foto():
    vorhanden = {"id": 1, "status": "entwurf", "bild_url": "https://alt", "wikidata_qid": ""}
    assert aktionen.bild_aenderung(vorhanden, FOTO) == {"wikidata_qid": "Q1"}


def test_bild_freigegebene_karte_bleibt_unberuehrt():
    assert aktionen.bild_aenderung({"id": 1, "status": "freigegeben", "bild_url": ""}, FOTO) == {}


def test_bild_ohne_nachweis_wird_nicht_gesetzt():
    ohne = {"bild_url": FOTO["bild_url"], "bild_nachweis": ""}
    assert aktionen.bild_aenderung({"id": 1, "status": "entwurf", "bild_url": ""}, ohne) == {}


def test_gruppen_liste_und_schild():
    gelesen = aktionen.gruppen_lesen({
        "Nordlicht": ["Erika Kranich", "Max Mustermann"],
        "DER KREIS": {"farbe": "#C8102E", "karten": ["Paul Winter"]},
    })
    assert gelesen["Nordlicht"] == ("", ["Erika Kranich", "Max Mustermann"])
    assert gelesen["DER KREIS"] == ("#C8102E", ["Paul Winter"])


def test_boards_baum_rueckt_mappen_ein():
    zeilen = boards_baum([
        {"slug": "haupt", "titel": "Hauptwand", "eltern": []},
        {"slug": "nordlicht", "titel": "Nordlicht", "eltern": ["haupt"]},
    ])
    assert zeilen[0].startswith("haupt")
    assert zeilen[1].strip().startswith("└ nordlicht")


def test_datenschutz_findet_namen_und_url_form():
    dateien = {"a.json": "Ein Beleg nennt Thea Beispiel.".encode(), "b.csv": b"https://x.test/thea-beispiel/",
               "c.csv": b"nichts"}
    assert aktionen.datenschutz_treffer(dateien, ["Thea Beispiel"]) == ["a.json", "b.csv"]
    assert aktionen.datenschutz_treffer(dateien, []) == []


def test_weg_oeffentlich_nur_belegt():
    wand = {"karten": [{"entitaet": 1, "entitaet_detail": {"name": "Senat"}},
                       {"entitaet": 2, "entitaet_detail": {"name": "Nordlicht"}},
                       {"entitaet": 3, "entitaet_detail": {"name": "Kranich"}}],
            "faeden": [{"von": 1, "nach": 2, "aussageart": "belegt"},
                       {"von": 2, "nach": 3, "aussageart": "meinung"}]}
    assert _weg_oeffentlich([wand], "Senat", "Nordlicht", True, 4) == {"gefunden": True, "weg": ["senat", "nordlicht"]}
    assert _weg_oeffentlich([wand], "Senat", "Kranich", True, 4)["gefunden"] is False
    assert _weg_oeffentlich([wand], "Senat", "Kranich", False, 4)["weg"] == ["senat", "nordlicht", "kranich"]
