"""Die Akte — die Belegregeln, der Weg durch den Graphen und wer was sehen darf.

Der wichtigste Test ist ``test_oeffentliche_wand_zeigt_nur_gepruefte_faeden``: die
öffentliche Ansicht darf nie einen Faden ohne Beleg, einen Verdacht ohne Anhörung
oder den Namen einer Privatperson zeigen.
"""

import io
import zipfile
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from akte.export import vault_zip
from akte.graph import finde_weg
from akte.models import (
    Aussageart,
    Beleg,
    Board,
    BoardKarte,
    Entitaet,
    Quelle,
    Status,
    Verbindung,
    VerbindungTyp,
    Verlauf,
    Zettel,
)
from akte.permissions import REDAKTION_GRUPPE
from akte.pruefung import pruefe_verbindung

User = get_user_model()
F = Status.FREIGEGEBEN


def entitaet(name, typ="person", oeffentlich=True, status=F):
    return Entitaet.objects.create(
        name=name, slug=name.lower().replace(" ", "-"), typ=typ,
        oeffentliche_person=oeffentlich, status=status,
    )


def quelle(titel="Bericht", herausgeber="Tagesschau", url="https://www.tagesschau.de/a"):
    return Quelle.objects.create(
        titel=titel, herausgeber=herausgeber, url=url,
        archiv_url="https://web.archive.org/x", abgerufen_am=date(2026, 9, 20),
    )


def faden(von, nach, quellen=(), **felder):
    werte = {"typ": VerbindungTyp.AMT, "start": date(2003, 5, 1), "aktuell": True, "status": F}
    werte.update(felder)
    v = Verbindung.objects.create(von=von, nach=nach, **werte)
    for q in quellen:
        Beleg.objects.create(verbindung=v, quelle=q)
    return v


def codes(v):
    return {b.code for b in pruefe_verbindung(v)}


class PruefungTest(TestCase):
    def setUp(self):
        self.mustermann = entitaet("Max Mustermann")
        self.nordlicht = entitaet("Nordlicht", typ="firma")

    def test_sauberer_faden_ist_ok(self):
        self.assertEqual(codes(faden(self.mustermann, self.nordlicht, [quelle()])), set())

    def test_ohne_quelle_sperrt(self):
        self.assertIn("ohne_quelle", codes(faden(self.mustermann, self.nordlicht)))

    def test_quelle_ohne_archiv_und_abruf_sperrt(self):
        q = Quelle.objects.create(titel="Blog", url="https://example.org/b")
        c = codes(faden(self.mustermann, self.nordlicht, [q]))
        self.assertTrue({"quelle_ohne_archiv", "quelle_ohne_abruf"} <= c)

    def test_verdacht_braucht_anhoerung_und_zwei_unabhaengige_quellen(self):
        q1 = quelle(url="https://www.spiegel.de/1", herausgeber="Spiegel")
        q2 = quelle(url="https://www.spiegel.de/2", herausgeber="Spiegel")
        v = faden(self.mustermann, self.nordlicht, [q1, q2], aussageart=Aussageart.VERDACHT)
        self.assertTrue({"verdacht_ohne_anhoerung", "verdacht_zu_duenn"} <= codes(v))

        Beleg.objects.create(verbindung=v, quelle=quelle(herausgeber="Zeit", url="https://zeit.de/x"))
        v.anhoerung_angefragt_am = date(2026, 9, 1)
        v.save()
        self.assertEqual(codes(v), set())

    def test_verdacht_gegen_privatperson_geht_nie_raus(self):
        privat = entitaet("Tom Klein", oeffentlich=False)
        v = faden(privat, self.nordlicht, [quelle(), quelle(herausgeber="Zeit", url="https://zeit.de/y")],
                  aussageart=Aussageart.VERDACHT, anhoerung_angefragt_am=date(2026, 9, 1))
        self.assertIn("verdacht_privatperson", codes(v))

    def test_zeitraum_regeln(self):
        self.assertIn("ohne_start", codes(faden(self.mustermann, self.nordlicht, [quelle()], start=None)))
        self.assertIn("zeitraum_offen", codes(faden(self.mustermann, self.nordlicht, [quelle()], aktuell=False)))
        self.assertIn(
            "zeitraum_widerspruch",
            codes(faden(self.mustermann, self.nordlicht, [quelle()], ende=date(2010, 1, 1))),
        )

    def test_nicht_freigegebene_karte_sperrt(self):
        entwurf = entitaet("Erika Kranich", status=Status.ENTWURF)
        self.assertIn("karte_nicht_freigegeben", codes(faden(entwurf, self.nordlicht, [quelle()])))


class WegTest(TestCase):
    def test_findet_kuerzesten_weg_in_beide_richtungen(self):
        a, b, c, d = (entitaet(n) for n in ("A", "B", "C", "D"))
        ab = faden(a, b)
        cb = faden(c, b)
        faden(c, d)
        knoten, faeden = finde_weg(a.id, c.id)
        self.assertEqual(knoten, [a.id, b.id, c.id])
        self.assertEqual(faeden, [ab.id, cb.id])

    def test_tiefe_und_filter(self):
        a, b, c = (entitaet(n) for n in ("A", "B", "C"))
        faden(a, b)
        faden(b, c, aussageart=Aussageart.VERDACHT)
        self.assertIsNone(finde_weg(a.id, c.id, max_tiefe=1))
        self.assertIsNone(finde_weg(a.id, c.id, aussagearten=[Aussageart.BELEGT]))
        self.assertIsNotNone(finde_weg(a.id, c.id))


class ExportTest(TestCase):
    def test_vault_hat_notiz_mit_links_und_quellen(self):
        mustermann = entitaet("Max Mustermann")
        nordlicht = entitaet("Nordlicht", typ="firma")
        faden(mustermann, nordlicht, [quelle(titel="SEC S-1")], beschreibung="Mitgründer")
        dateien = zipfile.ZipFile(io.BytesIO(vault_zip()))
        text = dateien.read("Akte/Person/Max Mustermann.md").decode()
        self.assertIn("[[Nordlicht]]", text)
        self.assertIn("Mitgründer", text)
        self.assertIn("SEC S-1", text)


class ApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.redakteur = User.objects.create_user(username="redaktion", email="redaktion@example.org", password="pw")
        self.redakteur.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.fremd = User.objects.create_user(username="fremd", email="fremd@example.org", password="pw")

    def test_nur_redaktion_kommt_rein(self):
        Board.objects.create(titel="Nordlicht", slug="nordlicht")
        self.assertEqual(self.client.get("/api/v1/akte/boards/").status_code, 401)
        self.client.force_authenticate(self.fremd)
        # Ohne AKTE_MITGLIEDER_BOARDS sieht ein Mitglied kein Board und darf nichts anlegen.
        self.assertEqual(self.client.get("/api/v1/akte/boards/").json(), [])
        self.assertEqual(self.client.get("/api/v1/akte/boards/nordlicht/").status_code, 404)
        self.assertEqual(self.client.post("/api/v1/akte/boards/", {"titel": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/akte/entitaeten/").status_code, 403)
        self.client.force_authenticate(self.redakteur)
        self.assertEqual(self.client.get("/api/v1/akte/boards/").status_code, 200)

    def test_faden_mit_belegen_anlegen_schreibt_verlauf(self):
        self.client.force_authenticate(self.redakteur)
        a = self.client.post("/api/v1/akte/entitaeten/", {"typ": "person", "name": "Max Mustermann"}, format="json").json()
        b = self.client.post("/api/v1/akte/entitaeten/", {"typ": "firma", "name": "Nordlicht"}, format="json").json()
        self.assertEqual(a["slug"], "max-mustermann")
        q = quelle()
        antwort = self.client.post("/api/v1/akte/verbindungen/", {
            "von": a["id"], "nach": b["id"], "typ": "amt", "start": "2003-05-01", "aktuell": True,
            "belege": [{"quelle": q.id, "zitat_woertlich": "co-founded"}],
        }, format="json")
        self.assertEqual(antwort.status_code, 201, antwort.content)
        daten = antwort.json()
        self.assertEqual(len(daten["belege"]), 1)
        # Entwurf: die Prüfung meldet, was vor der Veröffentlichung fehlt.
        self.assertIn("faden_nicht_freigegeben", {b["code"] for b in daten["befunde"]})
        self.assertTrue(Verlauf.objects.filter(objekt_art="verbindung", aktion="angelegt").exists())

    def test_doppelte_quelle_und_vergebener_slug_sind_400(self):
        self.client.force_authenticate(self.redakteur)
        a, b, q = entitaet("A"), entitaet("B"), quelle()
        antwort = self.client.post("/api/v1/akte/verbindungen/", {
            "von": a.id, "nach": b.id, "typ": "amt",
            "belege": [{"quelle": q.id}, {"quelle": q.id}],
        }, format="json")
        self.assertEqual(antwort.status_code, 400)
        antwort = self.client.post(
            "/api/v1/akte/entitaeten/", {"typ": "person", "name": "Z", "slug": a.slug}, format="json"
        )
        self.assertEqual(antwort.status_code, 400)

    def test_suche_exakter_name_zuerst(self):
        self.client.force_authenticate(self.redakteur)
        Entitaet.objects.create(name="Möwe Verlag SE", slug="as", typ="firma", kurzbeschreibung="ehrt Max Mustermann")
        Entitaet.objects.create(name="Max Mustermann", slug="pt", typ="person")
        treffer = self.client.get("/api/v1/akte/entitaeten/?q=Max Mustermann").json()
        self.assertEqual(treffer[0]["name"], "Max Mustermann")

    def test_rueckverweise_ohne_gross_klein(self):
        self.client.force_authenticate(self.redakteur)
        nordlicht = entitaet("Nordlicht", typ="firma")
        mustermann = entitaet("Max Mustermann")
        mustermann.notiz_md = "Gründete [[nordlicht]] 2003."
        mustermann.save()
        daten = self.client.get(f"/api/v1/akte/entitaeten/{nordlicht.id}/").json()
        self.assertEqual([r["id"] for r in daten["rueckverweise"]], [mustermann.id])

    def test_wand_liefert_karten_und_faeden_dazwischen(self):
        self.client.force_authenticate(self.redakteur)
        board = Board.objects.create(titel="Nordlicht", slug="nordlicht")
        a, b, c = entitaet("A"), entitaet("B"), entitaet("C")
        ab = faden(a, b)
        faden(a, c)  # C liegt nicht auf der Wand
        for e in (a, b):
            self.client.post(f"/api/v1/akte/boards/{board.slug}/karten/", {"entitaet": e.id, "x": 1, "y": 2}, format="json")
        daten = self.client.get(f"/api/v1/akte/boards/{board.slug}/").json()
        self.assertEqual(len(daten["karten"]), 2)
        self.assertEqual([f["id"] for f in daten["faeden"]], [ab.id])

    def test_positionen_bleiben_im_eigenen_board(self):
        self.client.force_authenticate(self.redakteur)
        eigenes = Board.objects.create(titel="A", slug="a")
        fremdes = Board.objects.create(titel="B", slug="b")
        z = Zettel.objects.create(board=fremdes, text="x")
        self.client.post("/api/v1/akte/boards/a/positionen/", [{"art": "zettel", "id": z.id, "x": 99, "y": 99}], format="json")
        z.refresh_from_db()
        self.assertEqual(z.x, 0)
        self.assertEqual(self.client.get(f"/api/v1/akte/boards/{eigenes.slug}/zettel/{z.id}/").status_code, 404)

    def test_faden_ausblenden_nur_fuer_faeden_auf_dem_board(self):
        self.client.force_authenticate(self.redakteur)
        Board.objects.create(titel="Leer", slug="leer")
        v = faden(entitaet("X"), entitaet("Y"))
        self.assertEqual(self.client.post(f"/api/v1/akte/boards/leer/faeden/{v.id}/ausblenden/").status_code, 404)


class OeffentlichTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.board = Board.objects.create(titel="Nordlicht", slug="nordlicht", oeffentlich=True)
        self.mustermann = entitaet("Max Mustermann")
        self.nordlicht = entitaet("Nordlicht", typ="firma")
        self.privat = entitaet("Tom Klein", oeffentlich=False)
        for e in (self.mustermann, self.nordlicht, self.privat):
            BoardKarte.objects.create(board=self.board, entitaet=e)
        Zettel.objects.create(board=self.board, text="interne Vermutung")
        self.gut = faden(self.mustermann, self.nordlicht, [quelle()])
        self.ohne_beleg = faden(self.nordlicht, self.privat)
        self.verdacht = faden(self.mustermann, self.privat, [quelle()], aussageart=Aussageart.VERDACHT)

    def test_aus_solange_schalter_aus(self):
        self.assertEqual(self.client.get("/api/v1/akte/oeffentlich/nordlicht/").status_code, 404)

    @override_settings(AKTE_OEFFENTLICH_AKTIV=True)
    def test_oeffentliche_wand_folgt_den_regelstufen(self):
        # Standard: „ohne Beleg“ ist ein Hinweis (ein Mensch hat freigegeben), Verdacht gegen eine Privatperson sperrt.
        daten = self.client.get("/api/v1/akte/oeffentlich/nordlicht/").json()
        self.assertEqual(len(daten["faeden"]), 2)
        self.assertNotIn("verdacht", {f.get("aussageart") for f in daten["faeden"]})

    @override_settings(AKTE_OEFFENTLICH_AKTIV=True)
    def test_oeffentliche_wand_zeigt_nur_gepruefte_faeden(self):
        # Dieses Board stellt „ohne Beleg“ auf Sperre: nur der belegte Faden Mustermann → Nordlicht geht raus.
        self.board.regeln = {"ohne_quelle": "sperrt"}
        self.board.save()
        daten = self.client.get("/api/v1/akte/oeffentlich/nordlicht/").json()
        self.assertEqual(len(daten["faeden"]), 1)
        namen_je_kennung = {k["id"]: k["name"] for k in daten["karten"]}
        f = daten["faeden"][0]
        self.assertEqual((namen_je_kennung[f["von"]], namen_je_kennung[f["nach"]]), ("Max Mustermann", "Nordlicht"))
        namen = {k["name"] for k in daten["karten"]}
        self.assertIn("T. K.", namen)
        self.assertNotIn("Tom Klein", str(daten))
        self.assertNotIn("interne Vermutung", str(daten))
        # Keine internen IDs: sonst wäre „T. K.“ über Boards hinweg wiedererkennbar.
        self.assertNotIn(self.privat.id, [k["id"] for k in daten["karten"]])
        self.assertTrue(all(str(k["id"]).startswith("k") for k in daten["karten"]))

    @override_settings(AKTE_OEFFENTLICH_AKTIV=True)
    def test_nicht_oeffentliches_board_bleibt_zu(self):
        self.board.oeffentlich = False
        self.board.save()
        self.assertEqual(self.client.get("/api/v1/akte/oeffentlich/nordlicht/").status_code, 404)


@override_settings(AKTE_MITGLIEDER_BOARDS="nordlicht")
class MitgliederTest(TestCase):
    """Jedes eingeloggte Konto liest die freigeschalteten Boards — nur Karten, Rahmen und belegte
    Fäden mit Quelle. Kein anderes Board, keine Notiz, kein Zettel, kein Schreiben."""

    def setUp(self):
        self.client = APIClient()
        self.mitglied = User.objects.create_user(username="mitglied", email="mitglied@example.org", password="pw")
        self.client.force_authenticate(self.mitglied)
        self.board = Board.objects.create(titel="Nordlicht", slug="nordlicht")
        self.intern = Board.objects.create(titel="Werkbank", slug="werkbank")
        self.mustermann = entitaet("Max Mustermann", status=Status.ENTWURF)
        self.mustermann.notiz_md = "interne Notiz zu Mustermann"
        self.mustermann.save()
        self.nordlicht = entitaet("Nordlicht", typ="firma")
        self.privat = entitaet("Tom Klein", oeffentlich=False)
        self.creator = entitaet("Kleiner Creator", typ="organisation")
        for e in (self.mustermann, self.nordlicht, self.privat):
            BoardKarte.objects.create(board=self.board, entitaet=e)
        BoardKarte.objects.create(board=self.intern, entitaet=self.mustermann)
        BoardKarte.objects.create(board=self.intern, entitaet=self.creator)
        Zettel.objects.create(board=self.board, text="interne Vermutung")
        self.gut = faden(self.mustermann, self.nordlicht, [quelle()], status=Status.ENTWURF)
        self.ohne_beleg = faden(self.nordlicht, self.privat)
        self.verdacht = faden(self.mustermann, self.privat, [quelle()], aussageart=Aussageart.VERDACHT)
        self.zum_intern = faden(self.creator, self.mustermann, [quelle(titel="Reel", url="https://instagram.com/x")])

    def test_liest_freigeschaltetes_board(self):
        antwort = self.client.get("/api/v1/akte/boards/nordlicht/")
        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        self.assertFalse(daten["darf_bearbeiten"])
        namen = {k["entitaet"]: k["entitaet_detail"]["name"] for k in daten["karten"]}
        self.assertEqual(set(namen.values()), {"Max Mustermann", "Nordlicht", "T. K."})
        # Nur der belegte Faden, auch als Entwurf; kein Verdacht, kein Faden ohne Beleg, keiner zum anderen Board.
        self.assertEqual(len(daten["faeden"]), 1)
        f = daten["faeden"][0]
        self.assertEqual((namen[f["von"]], namen[f["nach"]]), ("Max Mustermann", "Nordlicht"))
        # Kennungen nur für diese Antwort (1..n), nicht die internen IDs.
        self.assertEqual(sorted(namen), [1, 2, 3])
        self.assertEqual(f["id"], 1)
        self.assertEqual(daten["faeden"][0]["belege"][0]["quelle_detail"]["titel"], "Bericht")
        self.assertEqual(daten["faeden"][0]["befunde"], [])
        self.assertEqual((daten["zettel"], daten["fahrten"], daten["beweise"]), ([], [], []))
        text = str(daten)
        for geheim in ("interne Notiz", "interne Vermutung", "Tom Klein", "Kleiner Creator", "instagram", "notiz_md",
                       "erstellt_von", "stand': {"):
            self.assertNotIn(geheim, text)
        self.assertIn("T. K.", text)

    def test_liste_zeigt_nur_freigeschaltete(self):
        daten = self.client.get("/api/v1/akte/boards/").json()
        self.assertEqual([b["slug"] for b in daten], ["nordlicht"])
        self.assertFalse(daten[0]["darf_bearbeiten"])
        self.assertNotIn("erstellt_von", daten[0])

    def test_anderes_board_und_werkstatt_bleiben_zu(self):
        self.assertEqual(self.client.get("/api/v1/akte/boards/werkbank/").status_code, 404)
        for pfad in (f"/api/v1/akte/entitaeten/{self.mustermann.id}/", "/api/v1/akte/entitaeten/?q=Mustermann",
                     "/api/v1/akte/quellen/", f"/api/v1/akte/verbindungen/{self.gut.id}/",
                     "/api/v1/akte/boards/nordlicht/pruefung/", "/api/v1/akte/export/obsidian/"):
            self.assertEqual(self.client.get(pfad).status_code, 403, pfad)

    def test_schreiben_bleibt_redaktion(self):
        b = "/api/v1/akte/boards/nordlicht/"
        self.assertEqual(self.client.patch(b, {"titel": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(b).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/akte/boards/", {"titel": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client.post(f"{b}zettel/", {"text": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client.post(f"{b}aufraeumen/").status_code, 403)
        self.assertEqual(self.client.post(f"{b}positionen/", [], format="json").status_code, 403)

    @override_settings(AKTE_MITGLIEDER_BOARDS="")
    def test_schalter_aus_schliesst_alles(self):
        self.assertEqual(self.client.get("/api/v1/akte/boards/nordlicht/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/akte/boards/").json(), [])

    def test_redaktion_sieht_alles_und_darf_bearbeiten(self):
        redaktion = User.objects.create_user(username="redaktion", email="redaktion@example.org", password="pw", is_superuser=True)
        self.client.force_authenticate(redaktion)
        daten = self.client.get("/api/v1/akte/boards/nordlicht/").json()
        self.assertTrue(daten["darf_bearbeiten"])
        self.assertEqual(len(daten["zettel"]), 1)
        self.assertEqual({b["slug"] for b in self.client.get("/api/v1/akte/boards/").json()}, {"nordlicht", "werkbank"})


class OrdnungUndKameraTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.redakteur = User.objects.create_user(username="redaktion", email="redaktion@example.org", password="pw")
        self.redakteur.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.client.force_authenticate(self.redakteur)
        self.board = Board.objects.create(titel="P", slug="p")
        # Absichtlich übereinander gestapelt.
        self.e = [entitaet(f"E{i}") for i in range(12)]
        for i, e in enumerate(self.e):
            BoardKarte.objects.create(board=self.board, entitaet=e, x=i * 5, y=i * 5)
        for i in range(1, 12):
            faden(self.e[0], self.e[i])
        Zettel.objects.create(board=self.board, text="z", x=3, y=3)
        from akte.models import Rahmen
        Rahmen.objects.create(board=self.board, titel="Kern", x=-10, y=-10, breite=400, hoehe=400)

    def test_aufraeumen_ohne_ueberlappung(self):
        from akte.layout import KARTE_B, KARTE_H, ZETTEL_B, ZETTEL_H, ueberlappungen

        daten = self.client.post("/api/v1/akte/boards/p/aufraeumen/").json()
        rechtecke = [(k["x"], k["y"], KARTE_B, KARTE_H) for k in daten["karten"]]
        rechtecke += [(z["x"], z["y"], ZETTEL_B, ZETTEL_H) for z in daten["zettel"]]
        self.assertEqual(ueberlappungen(rechtecke), [])
        r = daten["rahmen"][0]
        for x, y, b, h in rechtecke:
            self.assertTrue(r["x"] <= x and x + b <= r["x"] + r["breite"])
            self.assertTrue(r["y"] <= y and y + h <= r["y"] + r["hoehe"])

    def test_grosse_wand_wird_quer_statt_saeule(self):
        # 21 Rahmen à 12 Karten: früher 5200 breit und fast viermal so hoch, jetzt eher Querformat.
        from akte.layout import KARTE_B, KARTE_H, RahmenBox, Teil, aufraeumen, ueberlappungen

        rahmen = [RahmenBox(i, 0, i * 3000, 2000, 2800) for i in range(21)]
        teile = [Teil("karte", i * 12 + j, 10 + j * 5, i * 3000 + 200, i * 12 + j) for i in range(21) for j in range(12)]
        positionen, neue = aufraeumen(teile, rahmen, [])
        breite = max(x + b for x, _, b, _ in neue.values())
        hoehe = max(y + h for _, y, _, h in neue.values())
        self.assertGreater(breite / hoehe, 1.0)
        self.assertEqual(ueberlappungen(list(neue.values())), [])
        self.assertEqual(ueberlappungen([(x, y, KARTE_B, KARTE_H) for x, y in positionen.values()]), [])

    def test_rahmen_farbe_nur_als_hex(self):
        # Mit Farbe wird ein Rahmen auf der Wand zum Schild („DER KREIS“); CSS aus der Datenbank bleibt draußen.
        gut = self.client.post("/api/v1/akte/boards/p/rahmen/", {"titel": "DER KREIS", "farbe": "#C8102E"}, format="json")
        self.assertEqual(gut.status_code, 201, gut.content)
        self.assertEqual(gut.json()["farbe"], "#C8102E")
        for boese in ("red", "#C8102E;x", "url(x)"):
            antwort = self.client.post("/api/v1/akte/boards/p/rahmen/", {"titel": "X", "farbe": boese}, format="json")
            self.assertEqual(antwort.status_code, 400, boese)

    def test_fahrt_aus_beschreibung_rechnet_bild(self):
        self.client.post("/api/v1/akte/boards/p/aufraeumen/")
        antwort = self.client.post("/api/v1/akte/boards/p/fahrten/aus-beschreibung/", {
            "titel": "K3", "format": "16:9",
            "stationen": [{"fokus": [], "stichwort": "Überblick"}, {"fokus": ["e1"], "stichwort": "Nah"}],
        }, format="json")
        self.assertEqual(antwort.status_code, 201, antwort.content)
        ueberblick, kern = antwort.json()["stationen"]
        self.assertLess(ueberblick["zoom"], kern["zoom"])
        self.assertEqual(kern["fokus"], [self.e[1].id])
        # Gleicher Titel ersetzt, statt zu verdoppeln.
        self.client.post("/api/v1/akte/boards/p/fahrten/aus-beschreibung/", {
            "titel": "K3", "stationen": [{"fokus": ["E2"]}]}, format="json")
        self.assertEqual(self.board.fahrten.count(), 1)

    def test_fahrt_mit_sprechtext_und_einblendung(self):
        antwort = self.client.post("/api/v1/akte/boards/p/fahrten/aus-beschreibung/", {
            "titel": "Gesichtslos", "stationen": [{
                "fokus": ["e1"], "text": "Allein in Nordmark geht es um rund neununddreißig Millionen Datensätze.",
                "einblendung": {"gross": "39 Mio.", "klein": "Personendatensätze", "quelle": "DSK 17.09.2025", "voll": 1},
            }]}, format="json")
        self.assertEqual(antwort.status_code, 201, antwort.content)
        station = antwort.json()["stationen"][0]
        self.assertTrue(station["text"].startswith("Allein in Nordmark"))
        self.assertEqual(station["einblendung"], {"gross": "39 Mio.", "klein": "Personendatensätze", "quelle": "DSK 17.09.2025", "voll": True})
        # Fremde Felder in der Einblendung werden abgelehnt, nicht still übernommen.
        falsch = self.client.post("/api/v1/akte/boards/p/fahrten/aus-beschreibung/", {
            "titel": "X", "stationen": [{"fokus": ["e1"], "einblendung": {"skript": "<b>"}}]}, format="json")
        self.assertEqual(falsch.status_code, 400)

    @override_settings(AKTE_EINSPIELER_WURZELN=[r"X:\archiv", "/srv/archiv"])  # scrub:erlaubt
    def test_einspieler_braucht_quelle_und_lokalen_ausschnitt(self):
        url = "/api/v1/akte/boards/p/fahrten/aus-beschreibung/"
        gut = {"datei": r"X:\archiv\akte\ausschnitte\F2.mp4", "ab": 0, "bis": 6.3,  # scrub:erlaubt
               "quelle": "Sender, Sendung, 26.06.2025"}
        antwort = self.client.post(url, {"titel": "O-Ton", "stationen": [{"fokus": ["e1"], "einspieler": gut}]}, format="json")
        self.assertEqual(antwort.status_code, 201, antwort.content)
        self.assertEqual(antwort.json()["stationen"][0]["einspieler"]["freeze_ms"], 700)
        posix = {**gut, "datei": "/srv/archiv/akte/F2.mp4"}
        antwort = self.client.post(url, {"titel": "O-Ton 2", "stationen": [{"fokus": ["e1"], "einspieler": posix}]},
                                   format="json")
        self.assertEqual(antwort.status_code, 201, antwort.content)
        for kaputt in (
            {**gut, "quelle": ""},                       # ohne Urheberangabe kein Einspieler
            {**gut, "datei": "../geheim.mp4"},           # nur absolute lokale Pfade
            {**gut, "datei": r"X:\archiv\bild.exe"},     # nur Videodateien  # scrub:erlaubt
            {**gut, "ab": 3, "bis": 40},                 # höchstens 30 s
            {**gut, "datei": r"C:\Windows\x.mp4"},       # nur aus den Archiv-Ordnern
            {**gut, "datei": r"X:\archivX\a.mp4"},       # Präfix muss am Ordnertrenner enden  # scrub:erlaubt
            {**gut, "datei": "/srv/archivX/a.mp4"},      # dasselbe für POSIX-Pfade
            {**gut, "datei": "/etc/x.mp4"},              # POSIX außerhalb der Wurzeln
        ):
            r = self.client.post(url, {"titel": "X", "stationen": [{"fokus": ["e1"], "einspieler": kaputt}]}, format="json")
            self.assertEqual(r.status_code, 400, kaputt)

    def test_unbekannte_karte_wird_genannt(self):
        antwort = self.client.post("/api/v1/akte/boards/p/fahrten/aus-beschreibung/", {
            "titel": "X", "stationen": [{"fokus": ["Gibt es nicht"]}]}, format="json")
        self.assertEqual(antwort.status_code, 400)
        self.assertEqual(antwort.json()["unbekannt"], ["Gibt es nicht"])

    def test_token_zugang_nur_fuer_redaktion(self):
        from rest_framework.authtoken.models import Token

        c = APIClient()
        token = Token.objects.create(user=self.redakteur)
        c.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(c.get("/api/v1/akte/boards/").status_code, 200)
        fremd = User.objects.create_user(username="fremd2", email="fremd2@example.org", password="pw")
        c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=fremd).key}")
        self.assertEqual(c.get("/api/v1/akte/entitaeten/").status_code, 403)
        # Board-Liste ist Lesen: ohne freigeschaltete Boards leer, Anlegen bleibt verboten.
        self.assertEqual(c.get("/api/v1/akte/boards/").json(), [])
        self.assertEqual(c.post("/api/v1/akte/boards/", {"titel": "X"}, format="json").status_code, 403)
