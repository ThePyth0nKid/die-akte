"""Mappen — Boards in Boards.

Wichtigste Tests: ``MitgliederMappenTest`` (eine Mappe verrät nichts über nicht freigeschaltete Boards,
keine interne ID verlässt die Antwort) und ``BuendelRegelTest`` (jeder Faden landet in höchstens
einem Bündel, interne Fäden bleiben in ihrer Mappe).
"""

import io
import json
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from akte.export import vault_zip
from akte.layout import MAPPE_B, MAPPE_H, RahmenBox, Teil, aufraeumen, ueberlappungen
from akte.mappen import buendel_rechnen, lage_rechnen, teilbaum, vorschau, wuerde_zyklus, zaehler
from akte.models import Beleg, Board, BoardKarte, Entitaet, Mappe, Quelle, Status, Verbindung, VerbindungTyp
from akte.permissions import REDAKTION_GRUPPE

User = get_user_model()
F = Status.FREIGEGEBEN


def entitaet(name, typ="person", oeffentlich=True, bild=""):
    return Entitaet.objects.create(name=name, slug=name.lower().replace(" ", "-"), typ=typ,
                                   oeffentliche_person=oeffentlich, status=F, bild_url=bild)


def quelle(n=1):
    return Quelle.objects.create(titel=f"Bericht {n}", herausgeber="Tagesschau", url=f"https://www.tagesschau.de/{n}",
                                 archiv_url="https://web.archive.org/x", abgerufen_am=date(2026, 9, 29))


def faden(von, nach, q=None, **felder):
    werte = {"typ": VerbindungTyp.AMT, "start": date(2020, 1, 1), "aktuell": True, "status": F}
    werte.update(felder)
    v = Verbindung.objects.create(von=von, nach=nach, **werte)
    if q is not None:
        Beleg.objects.create(verbindung=v, quelle=q)
    return v


def legen(board, *entitaeten):
    for e in entitaeten:
        BoardKarte.objects.create(board=board, entitaet=e)


# ─── Reine Rechnung ─────────────────────────────────────────────────────────


class TeilbaumTest(SimpleTestCase):
    def test_zyklus_haengt_nicht(self):
        kinder = {1: [2], 2: [3], 3: [1]}
        self.assertEqual(teilbaum(1, kinder), {1, 2, 3})

    def test_kreis_auch_ueber_lange_ketten(self):
        # 20 Ebenen: über MAX_TIEFE hinaus, trotzdem erkannt.
        kinder = {i: [i + 1] for i in range(20)}
        self.assertTrue(wuerde_zyklus(20, 0, kinder))

    def test_wuerde_zyklus(self):
        kinder = {1: [2], 2: [3]}
        self.assertTrue(wuerde_zyklus(3, 1, kinder))   # 1 enthält 3 schon → 3 darf 1 nicht enthalten
        self.assertTrue(wuerde_zyklus(2, 2, kinder))   # Selbstbezug
        self.assertFalse(wuerde_zyklus(1, 4, kinder))

    def test_geteiltes_unterboard_und_tiefengrenze(self):
        kinder = {1: [2, 3], 2: [4], 3: [4], 4: [5]}
        self.assertEqual(teilbaum(1, kinder), {1, 2, 3, 4, 5})
        self.assertEqual(teilbaum(1, kinder, max_tiefe=1), {1, 2, 3})

    def test_nur_erlaubte_boards(self):
        kinder = {1: [2], 2: [3]}
        self.assertEqual(teilbaum(1, kinder, erlaubt={1, 3}), {1})
        self.assertEqual(teilbaum(2, kinder, erlaubt={1, 3}), set())


class BuendelRegelTest(SimpleTestCase):
    """Wand W mit direkter Karte Mustermann (Karte 100). Mappe 1 → Board 10 (Kranich, Nordlicht, Mustermann),
    Mappe 2 → Board 20 (Sommer, BfM, Mustermann, Nordlicht)."""

    def setUp(self):
        self.karten = {10: {"kranich", "nordlicht", "mustermann"}, 20: {"sommer", "bfm", "mustermann", "nordlicht"}}
        self.lage = lage_rechnen({"mustermann": 100}, [(1, 10), (2, 20)], {}, self.karten)

    def test_direkte_karte_gewinnt_und_gelenke(self):
        self.assertEqual(self.lage.direkt, {"mustermann": 100})
        self.assertEqual(self.lage.in_mappen["nordlicht"], {1, 2})
        # Nordlicht steckt in zwei Boards und liegt nicht direkt → Gelenk; Mustermann liegt direkt → keins.
        self.assertEqual(self.lage.gelenke, ["nordlicht"])

    def test_regeln(self):
        faeden = [
            (1, "mustermann", "kranich", "amt", "belegt", False),        # direkt → Mappe 1 (liegt dort)
            (2, "mustermann", "sommer", "aussage", "belegt", False),  # direkt → Mappe 2
            (3, "kranich", "nordlicht", "amt", "belegt", False),     # beide in Mappe 1 → intern
            (4, "kranich", "sommer", "sonstiges", "belegt", True),  # Mappe 1 ↔ Mappe 2
            (5, "mustermann", "nordlicht", "eigentum", "verdacht", True),  # direkt → gemeinsame Mappe (spezifischste: 1)
            (6, "mustermann", "fremd", "amt", "belegt", False),       # anderes Ende nicht auf der Wand
        ]
        buendel = {(b.a, b.b): b for b in buendel_rechnen(self.lage, faeden)}
        self.assertEqual(set(buendel), {(("k", 100), ("m", 1)), (("k", 100), ("m", 2)), (("m", 1), ("m", 2))})
        self.assertEqual(buendel[(("k", 100), ("m", 1))].faeden, [1, 5])
        self.assertEqual(buendel[(("k", 100), ("m", 2))].faeden, [2])
        self.assertEqual(buendel[(("m", 1), ("m", 2))].faeden, [4])
        self.assertEqual(buendel[(("m", 1), ("m", 2))].mit_betrag, 1)
        self.assertEqual(dict(buendel[(("k", 100), ("m", 1))].je_art), {"belegt": 1, "verdacht": 1})
        # Jeder Faden höchstens einmal.
        alle = [f for b in buendel.values() for f in b.faeden]
        self.assertEqual(len(alle), len(set(alle)))

    def test_zaehler(self):
        faeden = [(1, "mustermann", "kranich", "amt", "belegt", False), (3, "kranich", "nordlicht", "amt", "belegt", False)]
        z = zaehler(self.lage, faeden, {1: {7}, 3: {7, 8}})
        self.assertEqual(z[1], {"karten": 3, "faeden": 2, "quellen": 2})
        self.assertEqual(z[2], {"karten": 4, "faeden": 0, "quellen": 0})

    def test_vorschau_normiert(self):
        v = vorschau([(0, 0), (1000, 500)], [(-100, -100, 1500, 1100, "#C8102E")])
        self.assertEqual(v["rahmen"][0][:2], [0.0, 0.0])
        self.assertTrue(all(0 <= x <= 1 and 0 <= y <= 1 for x, y in v["karten"]))
        self.assertEqual(vorschau([], [])["karten"], [])


class LayoutMappeTest(SimpleTestCase):
    def test_mappe_zwei_zellen_ohne_ueberlappung(self):
        teile = [Teil("mappe", 1, 0, 0)] + [Teil("karte", i, i * 10, 0, i) for i in range(2, 9)]
        teile.append(Teil("mappe", 9, 5, 5))
        pos, rahmen = aufraeumen(teile, [RahmenBox(1, -50, -50, 5000, 3000)], [])
        rechtecke = [(pos[(t.art, t.id)][0], pos[(t.art, t.id)][1], t.breite, t.hoehe) for t in teile]
        self.assertEqual(ueberlappungen(rechtecke), [])
        self.assertEqual((teile[0].breite, teile[0].hoehe), (MAPPE_B, MAPPE_H))
        # Der Rahmen umschließt alles.
        rx, ry, rb, rh = rahmen[1]
        for x, y, b, h in rechtecke:
            self.assertTrue(rx <= x and x + b <= rx + rb and ry <= y and y + h <= ry + rh)

    def test_nur_mappen_stehen_als_regal_in_einer_reihe(self):
        teile = [Teil("mappe", i, i * 3, 0) for i in range(1, 6)]
        pos, _ = aufraeumen(teile, [RahmenBox(1, -50, -50, 9000, 2000)], [])
        self.assertEqual(len({pos[("mappe", i)][1] for i in range(1, 6)}), 1)
        rechtecke = [(pos[("mappe", i)][0], pos[("mappe", i)][1], MAPPE_B, MAPPE_H) for i in range(1, 6)]
        self.assertEqual(ueberlappungen(rechtecke), [])


# ─── API der Werkstatt ──────────────────────────────────────────────────────


class MappeApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.redakteur = User.objects.create_user(username="redaktion", email="redaktion@example.org", password="pw")
        self.redakteur.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.client.force_authenticate(self.redakteur)
        self.haupt = Board.objects.create(titel="Die Hauptwand", slug="hauptwand")
        self.nordlicht_b = Board.objects.create(titel="Nordlicht", slug="nordlicht")
        self.bfm_b = Board.objects.create(titel="Die BfM", slug="bfm")
        self.mustermann = entitaet("Max Mustermann", bild="https://upload.wikimedia.org/t.jpg")
        self.kranich = entitaet("Erika Kranich", bild="https://upload.wikimedia.org/k.jpg")
        self.nordlicht = entitaet("Nordlicht", typ="firma")
        self.sommer = entitaet("Lena Sommer")
        self.bfm = entitaet("BfM", typ="partei")
        legen(self.haupt, self.mustermann)
        legen(self.nordlicht_b, self.kranich, self.nordlicht, self.mustermann)
        legen(self.bfm_b, self.sommer, self.bfm, self.mustermann)
        q = quelle()
        self.f_kranich = faden(self.kranich, self.nordlicht, q)
        self.f_mustermann_kranich = faden(self.mustermann, self.kranich, q)
        self.f_mustermann_bfm = faden(self.mustermann, self.bfm, q, typ=VerbindungTyp.AUSSAGE)
        self.f_sommer_bfm = faden(self.sommer, self.bfm, q)
        self.url = "/api/v1/akte/boards/hauptwand/"

    def mappe(self, ziel, board="hauptwand", **daten):
        return self.client.post(f"/api/v1/akte/boards/{board}/mappen/", {"ziel": ziel, **daten}, format="json")

    def test_anlegen_und_regeln(self):
        self.assertEqual(self.mappe("nordlicht", x=10, y=20).status_code, 201)
        self.assertEqual(self.mappe("nordlicht").status_code, 400)             # doppelt
        self.assertEqual(self.mappe("hauptwand").status_code, 400)         # in sich selbst
        self.assertEqual(self.mappe("hauptwand", board="nordlicht").status_code, 400)  # Kreis
        self.assertEqual(self.mappe("bfm", farbe="rot").status_code, 400)     # Farbe nur #RRGGBB
        self.assertEqual(self.mappe("gibtsnicht").status_code, 404)
        self.assertEqual(Mappe.objects.count(), 1)

    def test_nur_redaktion_legt_mappen(self):
        fremd = User.objects.create_user(username="fremd", email="fremd@example.org", password="pw")
        self.client.force_authenticate(fremd)
        self.assertEqual(self.mappe("nordlicht").status_code, 403)

    def test_wand_mit_mappen_und_buendeln(self):
        self.mappe("nordlicht")
        self.mappe("bfm")
        w = self.client.get(self.url).json()
        self.assertEqual([m["ziel"] for m in w["mappen"]], ["nordlicht", "bfm"])
        pal = w["mappen"][0]
        self.assertEqual(pal["zaehler"], {"karten": 3, "faeden": 2, "quellen": 1})
        self.assertEqual([g["name"] for g in pal["gesichter"]], ["Erika Kranich", "Max Mustermann"])
        karte_mustermann = next(k["id"] for k in w["karten"])
        von = {(b["von"], b["nach"]): b for b in w["buendel"]}
        m_pal, m_bfm = (f"m-{m['id']}" for m in w["mappen"])
        self.assertEqual(von[(f"k-{karte_mustermann}", m_pal)]["faeden"], [self.f_mustermann_kranich.id])
        self.assertEqual(von[(f"k-{karte_mustermann}", m_bfm)]["faeden"], [self.f_mustermann_bfm.id])
        # Interne Fäden (Kranich → Nordlicht, Sommer → BfM) bleiben in ihrer Mappe.
        alle = {f for b in w["buendel"] for f in b["faeden"]}
        self.assertNotIn(self.f_kranich.id, alle)
        self.assertNotIn(self.f_sommer_bfm.id, alle)
        self.assertEqual({f["id"] for f in w["buendel_faeden"]}, alle)
        self.assertEqual({e["name"] for e in w["ausser_haus"]}, {"Erika Kranich", "BfM"})
        self.assertEqual(w["gelenke"], [])
        self.assertEqual({b["slug"] for b in w["auch_in"][str(self.mustermann.id)]}, {"nordlicht", "bfm"})
        # Das Unter-Board kennt seine Eltern.
        self.assertEqual(self.client.get("/api/v1/akte/boards/nordlicht/").json()["eltern"],
                         [{"slug": "hauptwand", "titel": "Die Hauptwand"}])

    def test_gelenk_und_verschachtelung(self):
        BoardKarte.objects.filter(board=self.haupt).delete()
        self.mappe("nordlicht")
        self.mappe("bfm")
        w = self.client.get(self.url).json()
        self.assertEqual([g["name"] for g in w["gelenke"]], ["Max Mustermann"])
        # Mappe in Mappe: Nordlicht liegt in BfM; die Hauptwand rechnet rekursiv.
        self.mappe("nordlicht", board="bfm")
        w = self.client.get(self.url).json()
        bfm = next(m for m in w["mappen"] if m["ziel"] == "bfm")
        self.assertEqual(bfm["zaehler"]["karten"], 5)

    def test_positionen_ausblenden_aufraeumen_loeschen(self):
        mid = self.mappe("nordlicht").json()["id"]
        self.client.post(f"{self.url}positionen/", [{"art": "mappe", "id": mid, "x": 777, "y": 55}], format="json")
        self.assertEqual((Mappe.objects.get(pk=mid).x, Mappe.objects.get(pk=mid).y), (777, 55))
        # Ein Faden im Bündel lässt sich auf der Hauptwand ausblenden.
        r = self.client.post(f"{self.url}faeden/{self.f_mustermann_kranich.id}/ausblenden/")
        self.assertEqual(r.json(), {"ausgeblendet": True})
        # Das Bündel zählt den Faden nicht mehr, hält ihn aber zum Wiedereinblenden bereit.
        w = self.client.get(self.url).json()
        self.assertEqual([(b["faeden"], b["ausgeblendet"]) for b in w["buendel"]], [([], [self.f_mustermann_kranich.id])])
        self.assertTrue(next(f for f in w["buendel_faeden"] if f["id"] == self.f_mustermann_kranich.id)["ausgeblendet"])
        self.assertEqual(self.client.post(f"{self.url}faeden/{self.f_mustermann_kranich.id}/ausblenden/").json(), {"ausgeblendet": False})
        self.client.post(f"{self.url}faeden/{self.f_mustermann_kranich.id}/ausblenden/")
        # Unendliche Koordinaten werden nie gespeichert (sonst ungültiges JSON).
        self.client.post(f"{self.url}positionen/", [{"art": "mappe", "id": mid, "x": "inf", "y": "nan"}], format="json")
        self.assertEqual((Mappe.objects.get(pk=mid).x, Mappe.objects.get(pk=mid).y), (777, 55))
        w = self.client.post(f"{self.url}aufraeumen/").json()
        self.assertEqual(len(w["mappen"]), 1)
        self.assertEqual(self.client.delete(f"{self.url}mappen/{mid}/").status_code, 204)
        self.assertFalse(Mappe.objects.exists())
        self.assertTrue(Board.objects.filter(slug="nordlicht").exists())

    def test_nordlicht_wand_bleibt_gleich(self):
        vorher = self.client.get("/api/v1/akte/boards/nordlicht/").json()["faeden"]
        self.mappe("nordlicht")
        nachher = self.client.get("/api/v1/akte/boards/nordlicht/").json()["faeden"]
        self.assertEqual([f["id"] for f in vorher], [f["id"] for f in nachher])

    def test_entitaet_kommt_vor_in_und_board_baum(self):
        self.mappe("nordlicht")
        e = self.client.get(f"/api/v1/akte/entitaeten/{self.mustermann.id}/").json()
        self.assertEqual({b["slug"] for b in e["boards"]}, {"hauptwand", "nordlicht", "bfm"})
        boards = {b["slug"]: b for b in self.client.get("/api/v1/akte/boards/").json()}
        self.assertEqual(boards["nordlicht"]["eltern"], ["hauptwand"])
        self.assertEqual(boards["hauptwand"]["eltern"], [])

    def test_last_bleibt_bei_wenigen_abfragen(self):
        gross = Board.objects.create(titel="Groß", slug="gross")
        ents = Entitaet.objects.bulk_create(
            Entitaet(name=f"E{i}", slug=f"e{i}", typ="person", oeffentliche_person=True) for i in range(300)
        )
        BoardKarte.objects.bulk_create(BoardKarte(board=gross, entitaet=e) for e in ents)
        Verbindung.objects.bulk_create(
            Verbindung(von=ents[i % 300], nach=ents[(i * 7 + 1) % 300], typ="amt") for i in range(1000)
            if i % 300 != (i * 7 + 1) % 300
        )
        legen(self.haupt, ents[0], ents[1])
        self.mappe("gross")
        with CaptureQueriesContext(connection) as abfragen:
            w = self.client.get(self.url).json()
        self.assertEqual(w["mappen"][0]["zaehler"]["karten"], 300)
        # Serialisierte Bündel-Fäden kosten Prefetch-Abfragen, aber nie eine je Faden.
        self.assertLessEqual(len(abfragen), 40)


# ─── Mitglieder ─────────────────────────────────────────────────────────────


@override_settings(AKTE_MITGLIEDER_BOARDS="hauptwand,nordlicht")
class MitgliederMappenTest(TestCase):
    """Eine Mappe gibt kein Leserecht weiter und verrät nichts über nicht freigeschaltete Boards."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user(username="m", email="mitglied@example.org", password="pw"))
        self.haupt = Board.objects.create(titel="Die Hauptwand", slug="hauptwand")
        self.pal = Board.objects.create(titel="Nordlicht", slug="nordlicht")
        self.intern = Board.objects.create(titel="Werkbank intern", slug="werkbank")
        self.mustermann = entitaet("Max Mustermann", bild="https://upload.wikimedia.org/t.jpg")
        self.kranich = entitaet("Erika Kranich", bild="https://upload.wikimedia.org/k.jpg")
        self.privat = entitaet("Tom Klein", oeffentlich=False)
        self.geheim = entitaet("Geheimer Kanal", typ="organisation")
        legen(self.haupt, self.mustermann)
        legen(self.pal, self.kranich, self.privat, self.mustermann)
        legen(self.intern, self.geheim, self.mustermann)
        q = quelle()
        self.gut = faden(self.mustermann, self.kranich, q)
        self.privat_faden = faden(self.mustermann, self.privat, q, typ=VerbindungTyp.SONSTIGES)
        self.ohne_beleg = faden(self.mustermann, self.kranich, None, typ=VerbindungTyp.AUSSAGE)
        self.verdacht = faden(self.kranich, self.mustermann, q, aussageart="verdacht")
        self.intern_faden = faden(self.mustermann, self.geheim, q)
        Mappe.objects.create(board=self.haupt, ziel=self.pal)
        Mappe.objects.create(board=self.haupt, ziel=self.intern)
        # Nordlicht enthält die interne Mappe: die Rekursion darf dort nicht hinein.
        Mappe.objects.create(board=self.pal, ziel=self.intern)

    def test_nur_freigeschaltete_mappen_ohne_spuren(self):
        r = self.client.get("/api/v1/akte/boards/hauptwand/")
        self.assertEqual(r.status_code, 200)
        text = r.content.decode()
        self.assertNotIn("werkbank", text.lower())
        self.assertNotIn("Geheimer Kanal", text)
        w = r.json()
        self.assertEqual([m["ziel"] for m in w["mappen"]], ["nordlicht"])
        self.assertEqual(w["mappen"][0]["zaehler"]["karten"], 3)   # ohne die interne Mappe darin
        self.assertEqual(w["gelenke"], [])

    def test_nur_belegte_faeden_und_eigene_kennungen(self):
        w = self.client.get("/api/v1/akte/boards/hauptwand/").json()
        faeden = w["buendel_faeden"]
        self.assertEqual(len(faeden), 2)                          # gut + privat_faden; ohne Beleg und Verdacht fehlen
        self.assertTrue(all(f["aussageart"] == "belegt" and f["belege"] for f in faeden))
        interne = {self.gut.id, self.privat_faden.id, self.mustermann.id, self.kranich.id, self.privat.id}
        kennungen = {f["id"] for f in faeden} | {f["von"] for f in faeden} | {f["nach"] for f in faeden}
        kennungen |= {e["id"] for e in w["ausser_haus"]}
        self.assertTrue(all(isinstance(k, int) and k <= 10 for k in kennungen))
        self.assertTrue(interne.isdisjoint(kennungen) or max(kennungen) <= 10)
        self.assertEqual(w["buendel"][0]["von"], "k-1")
        self.assertEqual(w["buendel"][0]["nach"], "m-1")

    def test_verdeckte_person_nur_mit_initialen_ohne_portal(self):
        w = self.client.get("/api/v1/akte/boards/hauptwand/").json()
        privat = next(e for e in w["ausser_haus"] if e["name"] == "T. K.")
        self.assertEqual(privat["slug"], "")
        self.assertNotIn("Tom Klein", json.dumps(w))
        # Die Karte der Nordlicht-Wand: verdeckte Person bekommt kein „auch in“.
        pw = self.client.get("/api/v1/akte/boards/nordlicht/").json()
        nr_privat = next(k["id"] for k in pw["karten"] if k["entitaet_detail"]["name"] == "T. K.")
        self.assertNotIn(str(nr_privat), pw["auch_in"])
        nr_mustermann = next(k["id"] for k in pw["karten"] if k["entitaet_detail"]["name"] == "Max Mustermann")
        self.assertEqual([b["slug"] for b in pw["auch_in"][str(nr_mustermann)]], ["hauptwand"])
        self.assertEqual(pw["eltern"], [{"slug": "hauptwand", "titel": "Die Hauptwand"}])

    def test_quellen_tragen_eigene_kennungen(self):
        for n in range(2, 7):
            quelle(n)
        spaet = quelle(99)  # interne ID ≥ 7
        Beleg.objects.create(verbindung=self.gut, quelle=spaet)
        w = self.client.get("/api/v1/akte/boards/hauptwand/").json()
        kennungen = {b["quelle"] for f in w["buendel_faeden"] for b in f["belege"]}
        kennungen |= {b["quelle_detail"]["id"] for f in w["buendel_faeden"] for b in f["belege"]}
        self.assertEqual(kennungen, {1, 2})  # je Antwort 1..n, egal welche interne ID
        self.assertGreaterEqual(spaet.id, 7)

    def test_mappe_gibt_kein_leserecht(self):
        self.assertEqual(self.client.get("/api/v1/akte/boards/werkbank/").status_code, 404)
        slugs = {b["slug"] for b in self.client.get("/api/v1/akte/boards/").json()}
        self.assertEqual(slugs, {"hauptwand", "nordlicht"})

    @override_settings(AKTE_OEFFENTLICH_AKTIV=True)
    def test_oeffentliche_wand_kennt_keine_mappen(self):
        self.haupt.oeffentlich = True
        self.haupt.save()
        self.client.force_authenticate(None)
        w = self.client.get("/api/v1/akte/oeffentlich/hauptwand/").json()
        self.assertNotIn("mappen", w)
        self.assertNotIn("buendel", w)


# ─── Import und Export ──────────────────────────────────────────────────────


class ImportMappeTest(TestCase):
    def laden(self, daten):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "i.json"
            pfad.write_text(json.dumps(daten), encoding="utf-8")
            call_command("akte_import", str(pfad), stdout=io.StringIO())

    def test_eltern_auf_board_und_betrag(self):
        Board.objects.create(titel="Die Hauptwand", slug="hauptwand")
        self.laden({
            "board": {"titel": "Die BfM", "slug": "bfm", "eltern": "hauptwand"},
            "quellen": [{"schluessel": "q", "titel": "Liste", "url": "https://buergerschaft.beispiel.test/l", "guete": "primaer"}],
            "entitaeten": [
                {"schluessel": "spender", "typ": "person", "name": "Max Spender"},
                {"schluessel": "bfm", "typ": "partei", "name": "BfM"},
                {"schluessel": "nur-faden", "typ": "behoerde", "name": "Bürgerschaft", "auf_board": False},
            ],
            "verbindungen": [{"von": "spender", "nach": "bfm", "typ": "finanzierung", "beschreibung": "Großspende",
                              "betrag": "1500000.00", "waehrung": "EUR",
                              "belege": [{"quelle": "q", "zitat_woertlich": "", "fundstelle": "Listeneintrag"}]}],
        })
        bfm = Board.objects.get(slug="bfm")
        self.assertTrue(Mappe.objects.filter(board__slug="hauptwand", ziel=bfm).exists())
        self.assertEqual(set(bfm.karten.values_list("entitaet__name", flat=True)), {"Max Spender", "BfM"})
        v = Verbindung.objects.get()
        self.assertEqual((str(v.betrag), v.waehrung), ("1500000.00", "EUR"))

    def test_kreis_bricht_ab(self):
        a = Board.objects.create(titel="A", slug="a")
        b = Board.objects.create(titel="B", slug="b")
        Mappe.objects.create(board=b, ziel=a)
        with self.assertRaises(CommandError):
            self.laden({"board": {"titel": "B", "slug": "b", "eltern": "a"}, "entitaeten": []})


class AdminKreisTest(TestCase):
    def test_clean_verhindert_kreis(self):
        from django.core.exceptions import ValidationError

        a = Board.objects.create(titel="A", slug="a")
        b = Board.objects.create(titel="B", slug="b")
        Mappe.objects.create(board=a, ziel=b)
        with self.assertRaises(ValidationError):
            Mappe(board=b, ziel=a).full_clean()
        with self.assertRaises(ValidationError):
            Mappe(board=a, ziel=Board.objects.create(titel="C", slug="c"), farbe="url(x)").full_clean()


class ExportMappeTest(TestCase):
    def test_uebersichtsseiten(self):
        haupt = Board.objects.create(titel="Die Hauptwand", slug="hauptwand")
        pal = Board.objects.create(titel="Nordlicht: Auge", slug="nordlicht")
        legen(pal, entitaet("Erika Kranich"))
        Mappe.objects.create(board=haupt, ziel=pal)
        z = zipfile.ZipFile(io.BytesIO(vault_zip()))
        haupt_md = z.read("Akte/Boards/Die Hauptwand.md").decode()
        pal_md = z.read("Akte/Boards/Nordlicht Auge.md").decode()
        self.assertIn("[[Boards/Nordlicht Auge|Nordlicht: Auge]]", haupt_md)
        self.assertIn("## Liegt in", pal_md)
        self.assertIn("[[Erika Kranich]]", pal_md)

    def test_gleiche_titel_zwei_dateien(self):
        Board.objects.create(titel="Gleich", slug="gleich-a")
        Board.objects.create(titel="Gleich", slug="gleich-b")
        namen = [n for n in zipfile.ZipFile(io.BytesIO(vault_zip())).namelist() if n.startswith("Akte/Boards/Gleich")]
        self.assertEqual(len(namen), 2)
