"""Regel „quelle_ohne_archiv“ folgt der Einstellung archive.org (Entscheidung 14.10.2026).

archive.org an: wie bisher, nur die Archivkopie zählt. archive.org aus (Standard): Eine gesicherte eigene Kopie mit
Prüfsumme genügt; ohne sie bleibt der Hinweis mit Klartext-Grund.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from akte.einstellungen import archiv_org_setzen
from akte.models import Beleg, Board, BoardKarte, Entitaet, Quelle, Sicherung, SicherungStatus, Verbindung
from akte.permissions import REDAKTION_GRUPPE
from akte.pruefung import faeden_qs, pruefe_verbindung

User = get_user_model()
KEINE_KOPIE = "Keine gesicherte Kopie der Quelle – Sicherung erneut anstoßen"


@override_settings(AKTE_ARCHIV_AKTIV=False)
class RegelArchivTest(TestCase):
    def setUp(self):
        self.a = Entitaet.objects.create(name="Senat", slug="senat", typ="behoerde")
        self.b = Entitaet.objects.create(name="Nordlicht", slug="nordlicht", typ="firma")

    def faden(self, *, kopie=False, archiv_url="", fehler=False, ohne_pruefsumme=False):
        q = Quelle.objects.create(titel="Drucksache", url="https://x.example/d.pdf", archiv_url=archiv_url,
                                  abgerufen_am="2026-10-14")
        if kopie:
            Sicherung.objects.create(quelle=q, art="original", status=SicherungStatus.FERTIG,
                                     sha256="" if ohne_pruefsumme else "a" * 64)
        if fehler:
            Sicherung.objects.create(quelle=q, art="original", status=SicherungStatus.FEHLER, fehler="404")
        v = Verbindung.objects.create(von=self.a, nach=self.b, typ="auftrag")
        Beleg.objects.create(verbindung=v, quelle=q, zitat_woertlich="x")
        return faeden_qs().get(pk=v.pk)

    def archiv_befunde(self, v):
        return [b for b in pruefe_verbindung(v) if b.code == "quelle_ohne_archiv"]

    def test_aus_mit_eigener_kopie_kein_hinweis(self):
        self.assertEqual(self.archiv_befunde(self.faden(kopie=True)), [])

    def test_aus_ohne_eigene_kopie_hinweis_mit_grund(self):
        for v in (self.faden(), self.faden(fehler=True), self.faden(kopie=True, ohne_pruefsumme=True)):
            befunde = self.archiv_befunde(v)
            self.assertEqual(len(befunde), 1)
            self.assertIn(KEINE_KOPIE, befunde[0].text)
            self.assertEqual(befunde[0].schwere, "hinweis")

    def test_an_zaehlt_nur_die_archivkopie(self):
        archiv_org_setzen(True)
        befunde = self.archiv_befunde(self.faden(kopie=True))
        self.assertEqual([b.text for b in befunde], ["Quelle „Drucksache“ ohne Archivkopie."])
        self.assertEqual(len(self.archiv_befunde(self.faden())), 1)
        self.assertEqual(self.archiv_befunde(self.faden(kopie=True, archiv_url="https://web.archive.org/web/1/x")), [])

    @override_settings(AKTE_ARCHIV_AKTIV=True)
    def test_an_ueber_env_ohne_gespeicherte_entscheidung(self):
        self.assertEqual(len(self.archiv_befunde(self.faden(kopie=True))), 1)

    def test_entscheidung_schlaegt_env(self):
        with override_settings(AKTE_ARCHIV_AKTIV=True):
            archiv_org_setzen(False)
            self.assertEqual(self.archiv_befunde(self.faden(kopie=True)), [])

    def test_sperrende_stufe_folgt_derselben_regel(self):
        board = Board.objects.create(titel="W", slug="w", regeln={"quelle_ohne_archiv": "sperrt"})
        mit = self.faden(kopie=True)
        ohne = self.faden()
        self.assertEqual([b for b in pruefe_verbindung(mit, board) if b.code == "quelle_ohne_archiv"], [])
        self.assertEqual([b.schwere for b in pruefe_verbindung(ohne, board) if b.code == "quelle_ohne_archiv"],
                         ["sperrt"])


@override_settings(AKTE_ARCHIV_AKTIV=False)
class RegelArchivApiTest(TestCase):
    def setUp(self):
        konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.c = APIClient()
        self.c.force_authenticate(konto)
        self.board = Board.objects.create(titel="Wand", slug="wand")
        ents = [Entitaet.objects.create(name=f"E{i}", slug=f"e{i}", typ="firma") for i in range(21)]
        for e in ents:
            BoardKarte.objects.create(board=self.board, entitaet=e)
        for i in range(20):
            q = Quelle.objects.create(titel=f"Q{i}", url=f"https://x.example/{i}", abgerufen_am="2026-10-14")
            if i % 2:
                Sicherung.objects.create(quelle=q, art="original", status=SicherungStatus.FERTIG, sha256="b" * 64)
            v = Verbindung.objects.create(von=ents[i], nach=ents[i + 1], typ="auftrag")
            Beleg.objects.create(verbindung=v, quelle=q, zitat_woertlich="x")

    def test_pruefung_der_wand_und_einstellung_einmal_je_anfrage(self):
        with CaptureQueriesContext(connection) as abfragen:
            antwort = self.c.get("/api/v1/akte/boards/wand/pruefung/")
        self.assertEqual(antwort.status_code, 200)
        texte = [b["text"] for f in antwort.json()["faeden"] for b in f["befunde"] if b["code"] == "quelle_ohne_archiv"]
        self.assertEqual(len(texte), 10)  # nur die zehn Quellen ohne eigene Kopie
        self.assertTrue(all(KEINE_KOPIE in t for t in texte))
        einstellungen = [q for q in abfragen.captured_queries if "akte_einstellungen" in q["sql"]]
        self.assertEqual(len(einstellungen), 1)

    def test_umschalten_wirkt_sofort(self):
        self.assertEqual(self.c.patch("/api/v1/akte/einstellungen/", {"archiv_org": True}, format="json").status_code,
                         200)
        faeden = self.c.get("/api/v1/akte/boards/wand/pruefung/").json()["faeden"]
        self.assertEqual(sum(1 for f in faeden for b in f["befunde"] if b["code"] == "quelle_ohne_archiv"), 20)
