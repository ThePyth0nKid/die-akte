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


def test_csv_ohne_formeln_aber_mit_negativen_zahlen():
    tabelle = aktionen._csv([{"a": "=HYPERLINK(\"x\")", "b": "-12.5", "c": "@SUMME", "d": "+49 30", "e": "-Rest"}],
                            ["a", "b", "c", "d", "e"]).decode()
    zeile = tabelle.splitlines()[1]
    assert zeile.startswith("\"'=HYPERLINK")  # CSV setzt die Zelle in Anführungszeichen
    assert ",-12.5," in zeile and ",'@SUMME," in zeile and ",'+49 30," in zeile and zeile.endswith(",'-Rest")


def test_datenschutz_unicode_und_bom():
    zerlegt = "Thea Mu\u0308ller"  # ü als u + Trema (NFD)
    dateien = {"a.json": "Beleg nennt THEA  MÜLLER.".encode()}
    assert aktionen.datenschutz_treffer(dateien, ["\ufeff" + zerlegt]) == ["a.json"]


def test_ersetzen_nur_leeres_ziel_oder_frueheren_export(tmp_path):
    fremd = tmp_path / "fremd"
    fremd.mkdir()
    (fremd / "wichtig.txt").write_text("nicht löschen", encoding="utf-8")
    import pytest

    with pytest.raises(ValueError):
        aktionen._ersetzen(fremd, {"index.json": b"{}"}, b"")
    assert (fremd / "wichtig.txt").exists()

    ziel = tmp_path / "export"
    aktionen._ersetzen(ziel, {"index.json": aktionen.EXPORT_SCHEMA.encode(), "boards/a.json": b"1"}, b"x")
    aktionen._ersetzen(ziel, {"index.json": aktionen.EXPORT_SCHEMA.encode(), "boards/b.json": b"2"}, b"y")
    assert sorted(p.name for p in (ziel / "boards").iterdir()) == ["b.json"]
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


def test_unvollstaendiges_paket_ist_ein_valueerror():
    import pytest

    for paket in ({"quellen": [{"titel": "ohne Schlüssel"}]}, {"entitaeten": [{"schluessel": "a", "name": "A"}]},
                  {"verbindungen": [{"von": "a", "nach": "b", "typ": "x", "belege": [{}]}]}, {"board": {"titel": "T"}},
                  [], {"entitaeten": [{"schluessel": "a", "name": "A", "typ": "firma"}],
                       "verbindungen": [{"von": "a", "nach": "tippfehler", "typ": "x"}]},
                  {"quellen": [{"schluessel": "q", "titel": "Q"}],
                   "entitaeten": [{"schluessel": "a", "name": "A", "typ": "firma"},
                                  {"schluessel": "b", "name": "B", "typ": "firma"}],
                   "verbindungen": [{"von": "a", "nach": "b", "typ": "x", "belege": [{"quelle": "q2"}]}]}):
        with pytest.raises(ValueError):
            aktionen._paket_pruefen(paket)


class _AkteAttrappe:
    """Nur was ``importieren`` im Probelauf liest."""

    def get(self, pfad, params=None):
        return []

    def entitaet_finden(self, name):
        return None


def test_import_erkennt_dubletten_im_paket():
    paket = {"quellen": [{"schluessel": "q1", "titel": "Bericht", "url": "https://x.test/a"},
                         {"schluessel": "q2", "titel": "Bericht (Kopie)", "url": "https://x.test/a"},
                         {"schluessel": "q3", "titel": "Aushang", "herausgeber": "Amt"},
                         {"schluessel": "q4", "titel": "Aushang", "herausgeber": "Amt"}],
             "entitaeten": [{"schluessel": "a", "name": "Senat", "typ": "behoerde"},
                            {"schluessel": "a2", "name": "senat", "typ": "behoerde"},
                            {"schluessel": "b", "name": "Nordlicht", "typ": "firma"}],
             "verbindungen": [{"von": "a", "nach": "b", "typ": "auftrag", "belege": [{"quelle": "q1"}]},
                              {"von": "a", "nach": "b", "typ": "auftrag", "belege": [{"quelle": "q2"}]}]}
    bericht = aktionen.importieren(_AkteAttrappe(), paket, trocken=True)
    assert bericht["quellen_neu"] == ["Bericht", "Aushang"]
    assert bericht["karten_neu"] == ["Senat", "Nordlicht"]
    assert (bericht["faeden_neu"], bericht["faeden_vorhanden"]) == (1, 1)
