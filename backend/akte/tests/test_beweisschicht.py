"""Beweisschicht: Freigabe mit Unterschrift, Überstimmung, Rückfall auf Entwurf, Sicherungen, Export.

Der Browser wird hier durch einen echten Ed25519-Schlüssel im Test ersetzt: Er unterschreibt genau die Bytes,
die der Server zum Unterschreiben schickt. Den Export prüft dieselbe Bibliothek, die auch Dritte benutzen.
"""

from datetime import date

from akte_beweis import b64url, b64url_lesen, oeffentlicher_schluessel, pruefen, trace_pruefen
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from akte.models import (
    Beleg,
    Board,
    BoardKarte,
    Entitaet,
    Ereignis,
    Quelle,
    Sicherung,
    Status,
    Ueberstimmung,
    Verbindung,
)
from akte.permissions import REDAKTION_GRUPPE

User = get_user_model()
B = "/api/v1/akte/beweis"


class BeweisschichtTest(TestCase):
    def setUp(self):
        self.konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        self.konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.mensch = APIClient()
        self.mensch.force_authenticate(self.konto)
        self.werkzeug = APIClient()
        self.werkzeug.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.konto).key}")
        self.privat = Ed25519PrivateKey.generate()
        r = self.mensch.post(f"{B}/schluessel/", {"oeffentlich": b64url(oeffentlicher_schluessel(self.privat))},
                             format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.kid = r.json()["kid"]
        self.senat = Entitaet.objects.create(name="Senat Musterhafen", slug="senat", typ="behoerde")
        self.firma = Entitaet.objects.create(name="Nordlicht Analytik GmbH", slug="nordlicht", typ="firma")
        self.quelle = Quelle.objects.create(titel="Drucksache 9/1234", url="https://buergerschaft.beispiel.test/d.pdf",
                                            herausgeber="Bürgerschaft", abgerufen_am=date(2026, 10, 1))
        self.faden = Verbindung.objects.create(von=self.senat, nach=self.firma, typ="auftrag", beschreibung="beauftragt",
                                               start=date(2024, 1, 1), aktuell=True)
        Beleg.objects.create(verbindung=self.faden, quelle=self.quelle, zitat_woertlich="Der Senat beauftragt")

    def _freigeben(self, art, objekt_id, ueberstimmungen=None, privat=None):
        vor = self.mensch.post(f"{B}/freigabe/vorbereiten/", {"objekt": art, "id": objekt_id, "kid": self.kid,
                                                               "ueberstimmungen": ueberstimmungen or {}}, format="json")
        if vor.status_code != 200:
            return vor
        signatur = (privat or self.privat).sign(b64url_lesen(vor.json()["signing_input"]))
        return self.mensch.post(f"{B}/freigabe/abschliessen/", {"event_id": vor.json()["event_id"],
                                                               "signatur": b64url(signatur)}, format="json")

    def test_freigabe_mit_unterschrift_und_export_prueft_gueltig(self):
        for art, obj in (("karte", self.senat), ("karte", self.firma), ("faden", self.faden)):
            r = self._freigeben(art, obj.pk)
            self.assertEqual(r.status_code, 201, r.content)
        self.faden.refresh_from_db()
        self.assertEqual(self.faden.status, Status.FREIGEGEBEN)
        self.assertEqual(Ereignis.objects.filter(typ="akte.freigabe").count(), 3)

        export = self.mensch.get(f"{B}/export/").json()
        erg = trace_pruefen(export["trace"], export["buendel"], strikte_kette=True)
        self.assertTrue(erg.gueltig, erg.fehler)
        regel = pruefen(export["trace"], export["offenlegung"])
        self.assertTrue(regel.gueltig, regel.fehler)
        self.assertEqual(len(export["offenlegung"]), 3)

    def test_falsche_unterschrift_wird_abgelehnt(self):
        r = self._freigeben("faden", self.faden.pk, privat=Ed25519PrivateKey.generate())
        self.assertEqual(r.status_code, 400)
        self.faden.refresh_from_db()
        self.assertEqual(self.faden.status, Status.ENTWURF)
        self.assertFalse(Ereignis.objects.exists())

    def test_werkzeug_kann_weder_schluessel_anmelden_noch_unterschreiben(self):
        roh = b64url(oeffentlicher_schluessel(Ed25519PrivateKey.generate()))
        self.assertEqual(self.werkzeug.post(f"{B}/schluessel/", {"oeffentlich": roh}, format="json").status_code, 403)
        r = self.werkzeug.post(f"{B}/freigabe/vorbereiten/", {"objekt": "faden", "id": self.faden.pk, "kid": self.kid},
                               format="json")
        self.assertEqual(r.status_code, 403)

    def test_sperrender_befund_braucht_begruendung(self):
        privatperson = Entitaet.objects.create(name="Thea Beispiel", slug="thea", typ="person",
                                               oeffentliche_person=False)
        verdacht = Verbindung.objects.create(von=self.firma, nach=privatperson, typ="sonstiges", aussageart="verdacht",
                                             start=date(2024, 1, 1), aktuell=True)
        Beleg.objects.create(verbindung=verdacht, quelle=self.quelle)
        ohne = self._freigeben("faden", verdacht.pk)
        self.assertEqual(ohne.status_code, 400)
        self.assertIn("Begründung", ohne.json()["detail"])
        self.assertEqual([b["code"] for b in ohne.json()["fehlende_begruendung"]], ["verdacht_privatperson"])
        mit = self._freigeben("faden", verdacht.pk, {"verdacht_privatperson": "Gerichtlich festgestellt, Az. 1/2."})
        self.assertEqual(mit.status_code, 201, mit.content)
        self.assertTrue(Ueberstimmung.objects.filter(verbindung=verdacht, code="verdacht_privatperson").exists())

    def test_aenderung_nach_freigabe_setzt_auf_entwurf(self):
        self.assertEqual(self._freigeben("karte", self.firma.pk).status_code, 201)
        r = self.mensch.patch(f"/api/v1/akte/entitaeten/{self.firma.pk}/", {"kurzbeschreibung": "geändert"},
                              format="json")
        self.assertEqual(r.status_code, 200)
        self.firma.refresh_from_db()
        self.assertEqual(self.firma.status, Status.ENTWURF)
        # Neu unterschreiben geht.
        self.assertEqual(self._freigeben("karte", self.firma.pk).status_code, 201)

    def test_beleg_aenderung_meldet_veraendert_seit_freigabe(self):
        for art, obj in (("karte", self.senat), ("karte", self.firma), ("faden", self.faden)):
            self.assertEqual(self._freigeben(art, obj.pk).status_code, 201)
        # Die Quelle ändert sich hinter dem Rücken des Fadens: Der Faden ist nicht mehr, was unterschrieben wurde.
        Quelle.objects.filter(pk=self.quelle.pk).update(titel="Drucksache 9/9999")
        board = Board.objects.create(titel="Musterhafen", slug="musterhafen")
        for e in (self.senat, self.firma):
            BoardKarte.objects.create(board=board, entitaet=e)
        p = self.mensch.get("/api/v1/akte/boards/musterhafen/pruefung/").json()
        codes = {b["code"] for f in p["faeden"] for b in f["befunde"]}
        self.assertIn("veraendert_seit_freigabe", codes)
        self.assertFalse(p["alle_ok"])

    def test_sicherung_wird_vom_geraet_signiert(self):
        with self.captureOnCommitCallbacks(execute=True):
            Sicherung.objects.create(quelle=self.quelle, art="original", status="fertig", sha256="ab" * 32, bytes=10)
        e = Ereignis.objects.get(typ="akte.sicherung")
        self.assertTrue(e.kid.startswith("akte-geraet:"))
        export = self.mensch.get(f"{B}/export/").json()
        self.assertTrue(trace_pruefen(export["trace"], export["buendel"], strikte_kette=True).gueltig)
        self.assertTrue(pruefen(export["trace"]).gueltig)

    @override_settings(AKTE_OEFFENTLICH_AKTIV=True)
    def test_besucher_bekommen_nur_oeffentliche_offenlegung(self):
        for art, obj in (("karte", self.senat), ("karte", self.firma), ("faden", self.faden)):
            self.assertEqual(self._freigeben(art, obj.pk).status_code, 201)
        geheim = Entitaet.objects.create(name="Kranich Holding AG", slug="kranich", typ="firma")
        self.assertEqual(self._freigeben("karte", geheim.pk).status_code, 201)
        board = Board.objects.create(titel="Musterhafen", slug="musterhafen", oeffentlich=True)
        for e in (self.senat, self.firma):
            BoardKarte.objects.create(board=board, entitaet=e)
        export = APIClient().get(f"{B}/export/").json()
        self.assertEqual(len(export["trace"]["events"]), 4)
        offen = {e["inhalt"]["inhalt"].get("name") or e["inhalt"]["inhalt"].get("beschreibung")
                 for e in export["offenlegung"].values()}
        self.assertEqual(offen, {"Senat Musterhafen", "Nordlicht Analytik GmbH", "beauftragt"})
        self.assertTrue(pruefen(export["trace"], export["offenlegung"]).gueltig)

    def test_besucher_ohne_oeffentliche_akte_bekommen_nichts(self):
        self.assertEqual(APIClient().get(f"{B}/export/").status_code, 403)
