"""Security-Review, Paket 2: Was Leser sehen, was Werkzeuge dürfen, was die Kette offenlegt.

Ausgangspunkt war eine Probe des Reviews: Ein Werkzeug-Token legte Entwurfskarten, einen belegten Faden und einen
Meinungs-Zettel auf ein öffentliches Board, und Besucher ohne Konto sahen alles. Diese Tests halten fest, dass das
nicht mehr geht, und prüfen die übrigen Funde gleich mit.
"""

import io
from datetime import date
from pathlib import Path
from unittest import mock

from akte_beweis import b64url, b64url_lesen, oeffentlicher_schluessel, pruefen, trace_pruefen
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from akte import beweisschicht, speicher
from akte.models import (
    Board,
    BoardKarte,
    Entitaet,
    Ereignis,
    Quelle,
    Schluessel,
    Sicherung,
    Status,
    Verbindung,
    Verlauf,
    Zettel,
)
from akte.permissions import REDAKTION_GRUPPE

User = get_user_model()
A = "/api/v1/akte"
B = f"{A}/beweis"


class _Grundlage(TestCase):
    def setUp(self):
        cache.clear()
        self.konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        self.konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.mensch = APIClient()
        self.mensch.force_authenticate(self.konto)
        self.werkzeug = APIClient()
        self.werkzeug.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.konto).key}")
        self.besucher = APIClient()
        self.privat = Ed25519PrivateKey.generate()
        r = self.mensch.post(f"{B}/schluessel/", {"oeffentlich": b64url(oeffentlicher_schluessel(self.privat))},
                             format="json")
        self.kid = r.json()["kid"]
        self.oeffentlich = Board.objects.create(titel="Öffentlich", slug="offen", oeffentlich=True)
        self.arbeit = Board.objects.create(titel="Arbeit", slug="arbeit")

    def freigeben(self, art, objekt_id, ueberstimmungen=None, mit=None, kid=None):
        vor = self.mensch.post(f"{B}/freigabe/vorbereiten/", {"objekt": art, "id": objekt_id, "kid": kid or self.kid,
                                                               "ueberstimmungen": ueberstimmungen or {}},
                               format="json")
        self.assertEqual(vor.status_code, 200, vor.content)
        sig = (mit or self.privat).sign(b64url_lesen(vor.json()["signing_input"]))
        return self.mensch.post(f"{B}/freigabe/abschliessen/", {"event_id": vor.json()["event_id"],
                                                               "signatur": b64url(sig)}, format="json")

    def werkzeug_legt_an(self):
        """Wie ein Agent über den MCP: zwei Karten, eine Quelle mit Archiv, ein belegter Faden – alles Entwurf."""
        a = self.werkzeug.post(f"{A}/entitaeten/", {"name": "Senat Musterhafen", "typ": "behoerde"},
                               format="json").json()
        b = self.werkzeug.post(f"{A}/entitaeten/", {"name": "Nordlicht Analytik GmbH", "typ": "firma"},
                               format="json").json()
        q = Quelle.objects.create(titel="Drucksache 9/1234", url="https://buergerschaft.beispiel.test/d.pdf",
                                  herausgeber="Bürgerschaft", abgerufen_am=date(2026, 10, 1),
                                  archiv_url="https://web.archive.org/web/1/x")
        v = self.werkzeug.post(f"{A}/verbindungen/", {
            "von": a["id"], "nach": b["id"], "typ": "auftrag", "beschreibung": "beauftragt", "start": "2024-01-01",
            "aktuell": True, "aussageart": "belegt",
            "belege": [{"quelle": q.pk, "zitat_woertlich": "Der Senat beauftragt"}]}, format="json")
        self.assertEqual(v.status_code, 201, v.content)
        return a, b, q, v.json()


@override_settings(AKTE_OEFFENTLICH_AKTIV=True)
class SondeDesReviewsTest(_Grundlage):
    def test_werkzeug_aendert_kein_veroeffentlichtes_board(self):
        a, *_ = self.werkzeug_legt_an()
        o = f"{A}/boards/offen"
        self.assertEqual(self.werkzeug.post(f"{o}/karten/", {"entitaet": a["id"]}, format="json").status_code, 403)
        self.assertEqual(self.werkzeug.post(f"{o}/zettel/", {"art": "notiz", "text": "x"},
                                            format="json").status_code, 403)
        self.assertEqual(self.werkzeug.post(f"{o}/rahmen/", {"titel": "Täter"}, format="json").status_code, 403)
        self.assertEqual(self.werkzeug.patch(f"{o}/", {"titel": "Neu"}, format="json").status_code, 403)
        self.assertEqual(self.werkzeug.delete(f"{o}/").status_code, 403)
        # Anordnung und Fahrten bleiben erlaubt: Leser sehen sie nicht als Inhalt.
        self.assertEqual(self.werkzeug.post(f"{o}/positionen/", [], format="json").status_code, 204)
        self.assertEqual(self.werkzeug.post(f"{o}/fahrten/", {"titel": "F", "stationen": []},
                                            format="json").status_code, 201)
        # Auf dem Arbeits-Board darf das Werkzeug alles außer Meinungen und Löschen des Boards.
        self.assertEqual(self.werkzeug.post(f"{A}/boards/arbeit/karten/", {"entitaet": a["id"]},
                                            format="json").status_code, 201)
        self.assertEqual(self.werkzeug.post(f"{A}/boards/arbeit/zettel/", {"art": "meinung", "text": "x"},
                                            format="json").status_code, 403)
        self.assertEqual(self.werkzeug.delete(f"{A}/boards/arbeit/").status_code, 403)

    def test_besucher_sehen_keine_entwuerfe(self):
        a, b, _, v = self.werkzeug_legt_an()
        for e in (a, b):  # ein Mensch legt die Entwürfe auf das öffentliche Board
            self.assertEqual(self.mensch.post(f"{A}/boards/offen/karten/", {"entitaet": e["id"]},
                                              format="json").status_code, 201)
        Zettel.objects.create(board=self.oeffentlich, art="notiz", text="intern")
        daten = self.besucher.get(f"{A}/boards/offen/").json()
        self.assertEqual((daten["karten"], daten["faeden"], daten["zettel"]), ([], [], []))
        self.assertEqual(self.besucher.get(f"{A}/oeffentlich/offen/").json()["karten"], [])

        # Erst nach den Unterschriften eines Menschen erscheint alles.
        for art, pk in (("karte", a["id"]), ("karte", b["id"]), ("faden", v["id"])):
            self.assertEqual(self.freigeben(art, pk).status_code, 201)
        daten = self.besucher.get(f"{A}/boards/offen/").json()
        self.assertEqual(len(daten["karten"]), 2)
        self.assertEqual(len(daten["faeden"]), 1)

    def test_veraenderte_karte_verschwindet_bis_neu_unterschrieben(self):
        a, b, _, v = self.werkzeug_legt_an()
        for e in (a, b):
            BoardKarte.objects.create(board=self.oeffentlich, entitaet_id=e["id"])
        for art, pk in (("karte", a["id"]), ("karte", b["id"]), ("faden", v["id"])):
            self.freigeben(art, pk)
        # Hinter dem Rücken der Oberfläche geändert (ORM, Verwaltung): die Unterschrift passt nicht mehr.
        Entitaet.objects.filter(pk=a["id"]).update(kurzbeschreibung="nachträglich")
        daten = self.besucher.get(f"{A}/boards/offen/").json()
        self.assertEqual([k["entitaet_detail"]["name"] for k in daten["karten"]], ["Nordlicht Analytik GmbH"])
        self.assertEqual(daten["faeden"], [])


class WerkzeugRechteTest(_Grundlage):
    def test_werkzeug_macht_niemanden_oeffentlich(self):
        p = self.werkzeug.post(f"{A}/entitaeten/", {"name": "Erika Muster", "typ": "person",
                                                    "oeffentliche_person": False}, format="json").json()
        r = self.werkzeug.patch(f"{A}/entitaeten/{p['id']}/", {"oeffentliche_person": True}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.mensch.patch(f"{A}/entitaeten/{p['id']}/", {"oeffentliche_person": True},
                                           format="json").status_code, 200)

    @override_settings(AKTE_LESEANSICHT="alles_belegte", AKTE_OEFFENTLICH_AKTIV=True)
    def test_vorgeschlagene_oeffentliche_person_bleibt_bis_zur_unterschrift_verdeckt(self):
        p = self.werkzeug.post(f"{A}/entitaeten/", {"name": "Erika Muster", "typ": "person",
                                                    "oeffentliche_person": True}, format="json").json()
        BoardKarte.objects.create(board=self.oeffentlich, entitaet_id=p["id"])
        text = str(self.besucher.get(f"{A}/boards/offen/").json())
        self.assertIn("E. M.", text)
        self.assertNotIn("Erika", text)

    def test_quelle_eines_freigegebenen_fadens(self):
        a, b, q, v = self.werkzeug_legt_an()
        for art, pk in (("karte", a["id"]), ("karte", b["id"]), ("faden", v["id"])):
            self.freigeben(art, pk)
        self.assertEqual(self.werkzeug.patch(f"{A}/quellen/{q.pk}/", {"titel": "Gefälscht"},
                                             format="json").status_code, 409)
        self.assertEqual(self.werkzeug.delete(f"{A}/quellen/{q.pk}/").status_code, 400)  # belegt noch Fäden
        self.assertTrue(Quelle.objects.filter(pk=q.pk).exists())
        # Ein Mensch darf ändern; der Faden ist danach wieder Entwurf und muss neu unterschrieben werden.
        self.assertEqual(self.mensch.patch(f"{A}/quellen/{q.pk}/", {"titel": "Drucksache 9/1235"},
                                           format="json").status_code, 200)
        self.assertEqual(Verbindung.objects.get(pk=v["id"]).status, Status.ENTWURF)
        self.assertTrue(Verlauf.objects.filter(aktion="zurueck_auf_entwurf", objekt_id=v["id"]).exists())

    def test_umbenannte_karte_setzt_ihre_faeden_zurueck(self):
        a, b, _, v = self.werkzeug_legt_an()
        for art, pk in (("karte", a["id"]), ("karte", b["id"]), ("faden", v["id"])):
            self.freigeben(art, pk)
        self.mensch.patch(f"{A}/entitaeten/{b['id']}/", {"name": "Nordlicht Analytik AG"}, format="json")
        self.assertEqual(Entitaet.objects.get(pk=b["id"]).status, Status.ENTWURF)
        self.assertEqual(Verbindung.objects.get(pk=v["id"]).status, Status.ENTWURF)

    def test_meinungs_zettel(self):
        privat = Entitaet.objects.create(name="Thea Beispiel", slug="thea", typ="person", oeffentliche_person=False)
        BoardKarte.objects.create(board=self.arbeit, entitaet=privat)
        z = f"{A}/boards/arbeit/zettel/"
        self.assertEqual(self.mensch.post(z, {"art": "meinung", "text": "Thea Beispiel lügt"},
                                          format="json").status_code, 400)
        gut = self.mensch.post(z, {"art": "meinung", "text": "T. B. sollte gehört werden"}, format="json")
        self.assertEqual(gut.status_code, 201)
        notiz = self.werkzeug.post(z, {"art": "notiz", "text": "prüfen"}, format="json").json()
        self.assertEqual(self.werkzeug.patch(f"{z}{notiz['id']}/", {"art": "meinung"}, format="json").status_code, 403)
        self.assertEqual(self.werkzeug.patch(f"{z}{gut.json()['id']}/", {"text": "x"}, format="json").status_code, 403)
        self.assertEqual(self.werkzeug.delete(f"{z}{gut.json()['id']}/").status_code, 403)


class BeweisschichtHaertungTest(_Grundlage):
    def test_nutzlast_ohne_namen_und_kennungen(self):
        a, b, q, v = self.werkzeug_legt_an()
        Quelle.objects.filter(pk=q.pk).update(archiv_url="")  # ergibt den Hinweis „quelle_ohne_archiv“
        self.assertEqual(self.freigeben("faden", v["id"], ueberstimmungen={"quelle_ohne_archiv": "Archiv folgt"})
                         .status_code, 201)
        e = Ereignis.objects.get(typ="akte.freigabe")
        import json

        signiert = json.loads(e.json)
        self.assertEqual(set(signiert["payload"]), {"type", "objekt", "inhalt_zusage"})
        self.assertNotIn("redaktion", e.kid)
        self.assertRegex(e.kid, r"^akte-mensch:[0-9a-f]{16}$")
        self.assertEqual(e.inhalt["ueberstimmungen"], [{"code": "quelle_ohne_archiv", "begruendung": "Archiv folgt"}])

    def test_geraeteschluessel_kennung_mit_fingerabdruck(self):
        kid, _ = beweisschicht.geraeteschluessel()
        self.assertRegex(kid, r"^akte-geraet:[0-9a-f]{16}$")
        self.assertEqual(beweisschicht.geraeteschluessel()[0], kid)

    def test_widerruf_in_der_kette(self):
        neu = Ed25519PrivateKey.generate()
        kid_neu = self.mensch.post(f"{B}/schluessel/", {"oeffentlich": b64url(oeffentlicher_schluessel(neu))},
                                   format="json").json()["kid"]
        vor = self.mensch.post(f"{B}/widerruf/vorbereiten/", {"kid": self.kid, "mit": kid_neu}, format="json")
        self.assertEqual(vor.status_code, 200, vor.content)
        sig = neu.sign(b64url_lesen(vor.json()["signing_input"]))
        fertig = self.mensch.post(f"{B}/widerruf/abschliessen/", {"event_id": vor.json()["event_id"],
                                                                  "signatur": b64url(sig)}, format="json")
        self.assertEqual(fertig.status_code, 201, fertig.content)
        self.assertIsNotNone(Schluessel.objects.get(kid=self.kid).widerrufen_am)
        a, *_ = self.werkzeug_legt_an()
        vor = self.mensch.post(f"{B}/freigabe/vorbereiten/", {"objekt": "karte", "id": a["id"], "kid": self.kid},
                               format="json")
        self.assertEqual(vor.status_code, 403)
        self.assertEqual(self.freigeben("karte", a["id"], mit=neu, kid=kid_neu).status_code, 201)
        export = self.mensch.get(f"{B}/export/").json()
        self.assertIn(self.kid, export["widerrufen"])
        self.assertTrue(trace_pruefen(export["trace"], export["buendel"], strikte_kette=True).gueltig)
        self.assertTrue(pruefen(export["trace"], export["offenlegung"]).gueltig)

    def test_werkzeug_widerruft_nichts(self):
        self.assertEqual(self.werkzeug.post(f"{B}/widerruf/vorbereiten/", {"kid": self.kid},
                                            format="json").status_code, 403)

    def test_schwaerzen(self):
        a, b, _, v = self.werkzeug_legt_an()
        for art, pk in (("karte", a["id"]), ("karte", b["id"]), ("faden", v["id"])):
            self.freigeben(art, pk)
        call_command("akte_schwaerzen", "--faden", str(v["id"]), "--ja", stdout=io.StringIO())
        e = Ereignis.objects.get(verbindung_id=v["id"])
        self.assertEqual((e.salz, e.inhalt), ("", None))
        export = self.mensch.get(f"{B}/export/").json()
        self.assertIn(e.event_hash, export["geschwaerzt"])
        self.assertNotIn(e.event_hash, export["offenlegung"])
        self.assertTrue(trace_pruefen(export["trace"], export["buendel"], strikte_kette=True).gueltig)
        self.assertTrue(beweisschicht.veraendert_seit_freigabe(Verbindung.objects.get(pk=v["id"]), "faden"))

    @override_settings(AKTE_OEFFENTLICH_AKTIV=True)
    def test_besucher_bekommen_nur_die_juengste_freigabe(self):
        a, b, q, v = self.werkzeug_legt_an()
        for e in (a, b):
            BoardKarte.objects.create(board=self.oeffentlich, entitaet_id=e["id"])
        for art, pk in (("karte", a["id"]), ("karte", b["id"]), ("faden", v["id"])):
            self.freigeben(art, pk)
        self.mensch.patch(f"{A}/verbindungen/{v['id']}/", {"beschreibung": "beauftragt (korrigiert)"}, format="json")
        self.assertEqual(self.freigeben("faden", v["id"]).status_code, 201)
        export = self.besucher.get(f"{B}/export/").json()
        beschreibungen = [x["inhalt"]["inhalt"].get("beschreibung") for x in export["offenlegung"].values()
                          if x["inhalt"].get("objekt") == "faden"]
        self.assertEqual(beschreibungen, ["beauftragt (korrigiert)"])
        self.assertTrue(pruefen(export["trace"], export["offenlegung"]).gueltig)

    def test_lokal_gemeldetes_video_unterschreibt_das_geraet_nicht(self):
        q = Quelle.objects.create(titel="Video", url="https://video.beispiel.test/v")
        with self.captureOnCommitCallbacks(execute=True):
            r = self.werkzeug.post(f"{A}/quellen/{q.pk}/video-lokal/", {"pfad": "/archiv/v.mp4", "sha256": "ab" * 32},
                                   format="json")
        self.assertEqual(r.status_code, 201)
        self.assertFalse(Ereignis.objects.filter(typ="akte.sicherung").exists())


class SpeicherUndArchivTest(TestCase):
    def test_veraenderte_kopie_wird_nicht_ausgeliefert(self):
        import hashlib
        import tempfile

        with tempfile.TemporaryDirectory() as ordner, override_settings(AKTE_SPEICHER_LOKAL=ordner, AKTE_R2_BUCKET=""):
            daten = b"%PDF-1.4 echt"
            schl = speicher.schluessel(hashlib.sha256(daten).hexdigest(), "pdf")
            speicher.ablegen(schl, daten, "application/pdf")
            self.assertEqual(speicher.lesen(schl), daten)
            (Path(ordner) / schl).write_bytes(b"%PDF-1.4 gefaelscht")
            with self.assertRaises(speicher.KopieBeschaedigt):
                speicher.lesen(schl)
            self.assertEqual([p.name for p in (Path(ordner) / "beweise").iterdir()], [schl.split("/")[1]])

    def test_archive_org_bekommt_keine_zugangsdaten_und_laesst_sich_abschalten(self):
        from akte.sicherung import archive_org_sichern

        q = Quelle.objects.create(titel="Intern", url="https://nutzer:geheim@beispiel.test/x")
        with mock.patch("akte.sicherung.requests") as netz:
            s = archive_org_sichern(q)
            netz.get.assert_not_called()
            netz.post.assert_not_called()
        self.assertEqual(s.status, "fehler")
        self.assertIn("Zugangsdaten", s.fehler)
        with override_settings(AKTE_ARCHIV_AKTIV=False):
            self.assertIsNone(archive_org_sichern(Quelle.objects.create(titel="X", url="https://x.beispiel.test/")))
        self.assertFalse(Sicherung.objects.filter(quelle__titel="X").exists())

    def test_archive_org_bekommt_nichts_aus_dem_eigenen_netz(self):
        from akte.sicherung import archive_org_sichern

        q = Quelle.objects.create(titel="Router", url="http://192.0.2.1/admin")  # scrub:erlaubt (Dokumentations-IP)
        with mock.patch("akte.sicherung.requests") as netz:
            s = archive_org_sichern(q)
            netz.get.assert_not_called()
        self.assertEqual(s.status, "fehler")



class NachgereichtUndZwischenzeitTest(_Grundlage):
    """Code-Review Runde 2: Was die Beweissicherung nachreicht, ist keine Änderung; was zwischen Vorbereiten und
    Unterschreiben passiert, fällt auf."""

    def _alles_freigeben(self, archiv=""):
        a, b, q, v = self.werkzeug_legt_an()
        Quelle.objects.filter(pk=q.pk).update(archiv_url=archiv)
        for art, pk in (("karte", a["id"]), ("karte", b["id"]), ("faden", v["id"])):
            self.assertEqual(self.freigeben(art, pk).status_code, 201)
        return q, Verbindung.objects.get(pk=v["id"])

    def _veraendert(self, v):
        from akte.pruefung import faeden_qs

        return beweisschicht.veraendert_seit_freigabe(faeden_qs().get(pk=v.pk), "faden")

    def test_archivkopie_und_erste_sicherung_duerfen_nachkommen(self):
        q, v = self._alles_freigeben()
        Quelle.objects.filter(pk=q.pk).update(archiv_url="https://web.archive.org/web/2/x")
        Sicherung.objects.create(quelle=q, art="original", status="fertig", sha256="cd" * 32, bytes=5)
        self.assertFalse(self._veraendert(v))

    def test_unterschriebene_archivadresse_bleibt(self):
        q, v = self._alles_freigeben(archiv="https://web.archive.org/web/1/x")
        Quelle.objects.filter(pk=q.pk).update(archiv_url="https://web.archive.org/web/3/anders")
        self.assertTrue(self._veraendert(v))

    def test_unterschriebene_kopie_bleibt_massgeblich(self):
        a, b, q, v = self.werkzeug_legt_an()
        Sicherung.objects.create(quelle=q, art="original", status="fertig", sha256="ab" * 32, bytes=5)
        for art, pk in (("karte", a["id"]), ("karte", b["id"]), ("faden", v["id"])):
            self.freigeben(art, pk)
        faden = Verbindung.objects.get(pk=v["id"])
        Sicherung.objects.create(quelle=q, art="original", status="fertig", sha256="ef" * 32, bytes=6)
        self.assertFalse(self._veraendert(faden))
        Sicherung.objects.filter(sha256="ab" * 32).delete()
        self.assertTrue(self._veraendert(faden))

    def _vorbereiten(self, art, pk, kid=None):
        vor = self.mensch.post(f"{B}/freigabe/vorbereiten/", {"objekt": art, "id": pk, "kid": kid or self.kid},
                               format="json")
        self.assertEqual(vor.status_code, 200, vor.content)
        return vor.json()

    def _abschliessen(self, vor):
        sig = self.privat.sign(b64url_lesen(vor["signing_input"]))
        return self.mensch.post(f"{B}/freigabe/abschliessen/", {"event_id": vor["event_id"], "signatur": b64url(sig)},
                                format="json")

    def test_inhalt_aendert_sich_zwischen_vorbereiten_und_unterschreiben(self):
        a, b, q, v = self.werkzeug_legt_an()
        vor = self._vorbereiten("faden", v["id"])
        Verbindung.objects.filter(pk=v["id"]).update(beschreibung="untergeschoben")
        self.assertEqual(self._abschliessen(vor).status_code, 409)
        self.assertEqual(Verbindung.objects.get(pk=v["id"]).status, Status.ENTWURF)
        self.assertFalse(Ereignis.objects.filter(typ="akte.freigabe").exists())

    def test_pruefung_aendert_sich_zwischen_vorbereiten_und_unterschreiben(self):
        a, b, q, v = self.werkzeug_legt_an()
        Quelle.objects.filter(pk=q.pk).update(archiv_url="")
        vor = self.mensch.post(f"{B}/freigabe/vorbereiten/", {"objekt": "faden", "id": v["id"], "kid": self.kid,
                                                               "board": "arbeit"}, format="json").json()
        self.arbeit.regeln = {"quelle_ohne_archiv": "sperrt"}
        self.arbeit.save()
        self.assertIn(self._abschliessen(vor).status_code, (400, 409))
        self.assertEqual(Verbindung.objects.get(pk=v["id"]).status, Status.ENTWURF)

    def test_widerruf_zwischen_vorbereiten_und_unterschreiben(self):
        a, *_ = self.werkzeug_legt_an()
        vor = self._vorbereiten("karte", a["id"])
        from django.utils import timezone

        Schluessel.objects.filter(kid=self.kid).update(widerrufen_am=timezone.now())
        self.assertEqual(self._abschliessen(vor).status_code, 403)
        self.assertFalse(Ereignis.objects.filter(typ="akte.freigabe").exists())

    def test_speicher_ersetzt_beschaedigte_kopie(self):
        import hashlib
        import tempfile

        with tempfile.TemporaryDirectory() as ordner, override_settings(AKTE_SPEICHER_LOKAL=ordner, AKTE_R2_BUCKET=""):
            daten = b"%PDF-1.4 echt"
            schl = speicher.schluessel(hashlib.sha256(daten).hexdigest(), "pdf")
            speicher.ablegen(schl, daten, "application/pdf")
            (Path(ordner) / schl).write_bytes(b"halb")
            speicher.ablegen(schl, daten, "application/pdf")
            self.assertEqual(speicher.lesen(schl), daten)
