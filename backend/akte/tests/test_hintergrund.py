"""Hintergrund-Arbeit: Anlegen und Sichern warten nicht, drei Arbeiter, Wächter, Fehler landen in der Akte, Nachholen.

Synchronisiert wird über Events, nie über die Wanduhr; vor und nach jedem Thread-Test ist die Hintergrund-Arbeit leer.
"""

import shutil
import tempfile
import threading
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from akte import hintergrund
from akte.models import Quelle, Sicherung, SicherungStatus
from akte.permissions import REDAKTION_GRUPPE

User = get_user_model()
WARTEN = 10  # Sekunden: nur eine Obergrenze gegen Hänger, kein Takt


class _Aufgabe:
    """Wie eine Celery-Aufgabe: hat einen Namen, eine Frist, lässt sich aufrufen und mit .delay anstoßen."""

    def __init__(self, name, tun=None, time_limit=None):
        self.name, self.tun, self.aufrufe = name, tun, []
        self.time_limit = time_limit
        self.delay = mock.Mock()

    def __call__(self, *args):
        self.aufrufe.append(args)
        if self.tun:
            self.tun(*args)


class _Sauber:
    def setUp(self):
        super().setUp()
        hintergrund.zuruecksetzen(WARTEN)

    def tearDown(self):
        hintergrund.zuruecksetzen(WARTEN)
        super().tearDown()


@override_settings(AKTE_HINTERGRUND="thread")
class ThreadTest(_Sauber, SimpleTestCase):
    def setUp(self):
        super().setUp()
        aufraeumen = mock.patch("akte.hintergrund.close_old_connections")
        self.aufgeraeumt = aufraeumen.start()
        self.addCleanup(aufraeumen.stop)

    def test_kehrt_zurueck_waehrend_die_aufgabe_noch_laeuft(self):
        drin, los = threading.Event(), threading.Event()
        aufgabe = _Aufgabe("test.langsam", lambda *a: (drin.set(), los.wait(WARTEN)))
        hintergrund.starten(aufgabe, 1)
        self.assertTrue(drin.wait(WARTEN))  # sie läuft – und starten() ist längst zurück
        self.assertEqual(hintergrund.wartend(), 1)
        los.set()
        self.assertTrue(hintergrund.warten(WARTEN))
        self.assertEqual(aufgabe.aufrufe, [(1,)])
        aufgabe.delay.assert_not_called()
        self.assertGreaterEqual(self.aufgeraeumt.call_count, 2)  # vor und nach der Aufgabe

    def test_haengender_langer_auftrag_haelt_kurze_nicht_auf(self):
        los = threading.Event()
        lang = _Aufgabe("akte.tasks.quelle_sichern", lambda *a: los.wait(WARTEN))
        kurz_fertig = threading.Event()
        kurz = _Aufgabe("akte.tasks.fundstelle_sichern", lambda *a: kurz_fertig.set())
        hintergrund.starten(lang, 1)
        hintergrund.starten(kurz, 2)
        self.assertTrue(kurz_fertig.wait(WARTEN))  # läuft, obwohl der lange noch hängt
        los.set()
        self.assertTrue(hintergrund.warten(WARTEN))

    def test_archive_org_haelt_die_anderen_nicht_auf(self):
        los = threading.Event()
        archiv = _Aufgabe("akte.tasks.archiv_nachholen", lambda *a: los.wait(WARTEN))
        original_fertig = threading.Event()
        original = _Aufgabe("akte.tasks.quelle_sichern", lambda *a: original_fertig.set())
        hintergrund.starten(archiv, 1, 0)
        hintergrund.starten(original, 2)
        self.assertTrue(original_fertig.wait(WARTEN))  # läuft, obwohl archive.org noch hängt
        los.set()
        self.assertTrue(hintergrund.warten(WARTEN))

    def test_waechter_meldet_ueberzogene_frist_einmal(self):
        drin, los = threading.Event(), threading.Event()
        aufgabe = _Aufgabe("akte.tasks.quelle_sichern", lambda *a: (drin.set(), los.wait(WARTEN)), time_limit=5)
        hintergrund.starten(aufgabe, 7)
        self.assertTrue(drin.wait(WARTEN))
        lauf = hintergrund._arbeiter[hintergrund.LANG].lauf
        self.assertEqual(hintergrund.waechter_pruefen(lauf.anfang + 1), [])  # innerhalb der Frist: nichts
        with self.assertLogs("akte.hintergrund", level="ERROR") as log:
            self.assertEqual(hintergrund.waechter_pruefen(lauf.anfang + 6), ["akte.tasks.quelle_sichern"])
        self.assertIn("Frist 5 s", log.output[0])
        self.assertEqual(hintergrund.waechter_pruefen(lauf.anfang + 60), [])  # nur einmal
        los.set()
        self.assertTrue(hintergrund.warten(WARTEN))

    def test_fehler_beendet_den_arbeiter_nicht(self):
        def kaputt(*_):
            raise RuntimeError("archive.org weg")

        boese, gut = _Aufgabe("test.boese", kaputt), _Aufgabe("test.gut")
        with self.assertLogs("akte.hintergrund", level="ERROR"):
            hintergrund.starten(boese, 1)
            hintergrund.starten(gut, 2)
            self.assertTrue(hintergrund.warten(WARTEN))
        self.assertEqual(gut.aufrufe, [(2,)])

    def test_gleicher_wartender_auftrag_nur_einmal(self):
        drin, los = threading.Event(), threading.Event()
        blockiert = _Aufgabe("test.blockiert", lambda *a: (drin.set(), los.wait(WARTEN)))
        sichern = _Aufgabe("test.sichern")
        hintergrund.starten(blockiert, 0)
        self.assertTrue(drin.wait(WARTEN))
        for _ in range(6):  # ein Agent ruft sechsmal „sichern“ für dieselbe Quelle
            hintergrund.starten(sichern, 7)
        hintergrund.starten(sichern, 8)
        los.set()
        self.assertTrue(hintergrund.warten(WARTEN))
        self.assertEqual(sorted(sichern.aufrufe), [(7,), (8,)])

    @override_settings(AKTE_BROWSER_AKTIV=False)
    def test_browser_auftraege_nur_mit_browser(self):
        seite = _Aufgabe("akte.tasks.seite_rendern_task")
        hintergrund.starten(seite, 3)
        self.assertTrue(hintergrund.warten(WARTEN))
        self.assertEqual(seite.aufrufe, [])
        with override_settings(AKTE_BROWSER_AKTIV=True):
            self.assertEqual(hintergrund.arbeiter_fuer(seite), hintergrund.LANG)
            hintergrund.starten(seite, 3)
            self.assertTrue(hintergrund.warten(WARTEN))
        self.assertEqual(seite.aufrufe, [(3,)])


class ModusTest(SimpleTestCase):
    @override_settings(AKTE_HINTERGRUND="celery")
    def test_celery_geht_an_den_worker(self):
        aufgabe = _Aufgabe("test.celery")
        hintergrund.starten(aufgabe, 3)
        aufgabe.delay.assert_called_once_with(3)
        self.assertEqual(aufgabe.aufrufe, [])

    @override_settings(AKTE_HINTERGRUND="sofort", CELERY_TASK_ALWAYS_EAGER=False)
    def test_sofort_ohne_eager_ruft_direkt(self):
        aufgabe = _Aufgabe("test.sofort")
        hintergrund.starten(aufgabe, 4)
        self.assertEqual(aufgabe.aufrufe, [(4,)])

    @override_settings(AKTE_HINTERGRUND="quatsch")
    def test_unbekannter_modus_ist_thread(self):
        self.assertEqual(hintergrund.modus(), "thread")

    def test_frist_und_arbeiter_aus_der_aufgabe(self):
        from akte.tasks import archiv_nachholen, fundstelle_sichern, nachholen_charge, quelle_sichern

        self.assertEqual(hintergrund.frist_fuer(quelle_sichern), 300)
        self.assertEqual(hintergrund.arbeiter_fuer(fundstelle_sichern), hintergrund.KURZ)
        self.assertEqual(hintergrund.arbeiter_fuer(quelle_sichern), hintergrund.LANG)
        self.assertEqual(hintergrund.arbeiter_fuer(archiv_nachholen, (1, 0)), hintergrund.ARCHIV)
        self.assertEqual(hintergrund.arbeiter_fuer(nachholen_charge, ("archive_org", 3)), hintergrund.ARCHIV)
        self.assertEqual(hintergrund.arbeiter_fuer(nachholen_charge, ("original", 3)), hintergrund.LANG)
        self.assertEqual(hintergrund.frist_fuer(_Aufgabe("ohne")), hintergrund.FRIST_STANDARD)


class FehlerInDerAkteTest(TestCase):
    """Eine unerwartete Ausnahme in einer Aufgabe steht danach als Sicherung „Fehler“ an der Quelle."""

    def test_ausnahme_wird_sichtbar(self):
        from akte.tasks import quelle_sichern

        q = Quelle.objects.create(titel="Seite", url="https://x.example/")
        with mock.patch("akte.sicherung.quelle_sichern_jetzt", side_effect=KeyError("kaputt")), \
                self.assertLogs("akte.tasks", level="ERROR"):
            quelle_sichern(q.id)
        s = Sicherung.objects.get(quelle=q)
        self.assertEqual((s.art, s.status), ("original", SicherungStatus.FEHLER))
        self.assertIn("KeyError", s.fehler)

    def test_fundstelle_haengt_am_beleg(self):
        from akte.models import Beleg, Entitaet, Verbindung
        from akte.tasks import fundstelle_sichern

        a = Entitaet.objects.create(name="A", slug="a", typ="firma")
        b = Entitaet.objects.create(name="B", slug="b", typ="firma")
        q = Quelle.objects.create(titel="Q")
        beleg = Beleg.objects.create(verbindung=Verbindung.objects.create(von=a, nach=b, typ="auftrag"), quelle=q,
                                     zitat_woertlich="Ein Satz aus der Quelle.")
        with mock.patch("akte.sicherung.fundstelle_jetzt", side_effect=MemoryError()), \
                self.assertLogs("akte.tasks", level="ERROR"):
            fundstelle_sichern(beleg.id)
        s = Sicherung.objects.get(quelle=q)
        self.assertEqual((s.art, s.status, s.beleg_id), ("fundstelle", SicherungStatus.FEHLER, beleg.id))


@override_settings(AKTE_HINTERGRUND="thread", AKTE_SICHERUNG_AKTIV=True, AKTE_ARCHIV_AKTIV=False)
class NachholenTest(TestCase):
    def test_beim_start_quellen_ohne_eigene_kopie(self):
        from akte.sicherung import nachholen_beim_start
        from akte.tasks import quelle_sichern

        ohne = Quelle.objects.create(titel="ohne", url="https://x.example/1")
        mit = Quelle.objects.create(titel="mit", url="https://x.example/2")
        Sicherung.objects.create(quelle=mit, art="original", status="fertig", sha256="a" * 64)
        eben = Quelle.objects.create(titel="eben versucht", url="https://x.example/3")
        Sicherung.objects.create(quelle=eben, art="original", status="fehler", fehler="404")
        Quelle.objects.create(titel="ohne Link")
        with mock.patch("akte.hintergrund._einreihen") as einreihen:
            self.assertEqual(nachholen_beim_start(), {"original": 1, "archiv": 0})
        einreihen.assert_called_once_with(quelle_sichern, (ohne.id,))

    def test_beim_start_mit_archive_org_auch_archivkopien(self):
        from akte.einstellungen import archiv_org_setzen
        from akte.sicherung import nachholen_beim_start
        from akte.tasks import archiv_nachholen, quelle_sichern

        archiv_org_setzen(True)
        ohne_alles = Quelle.objects.create(titel="ohne", url="https://x.example/1")
        nur_kopie = Quelle.objects.create(titel="kopie", url="https://x.example/2")
        Sicherung.objects.create(quelle=nur_kopie, art="original", status="fertig", sha256="a" * 64)
        fertig = Quelle.objects.create(titel="fertig", url="https://x.example/3",
                                       archiv_url="https://web.archive.org/web/1/x")
        Sicherung.objects.create(quelle=fertig, art="original", status="fertig", sha256="b" * 64)
        with mock.patch("akte.hintergrund._einreihen") as einreihen:
            self.assertEqual(nachholen_beim_start(), {"original": 1, "archiv": 2})
        self.assertEqual(einreihen.call_args_list, [mock.call(quelle_sichern, (ohne_alles.id,)),
                                                     mock.call(archiv_nachholen, (ohne_alles.id, 0)),
                                                     mock.call(archiv_nachholen, (nur_kopie.id, 0))])

    def test_auswahl_ohne_dauerversager_und_verweigerte_aelteste_zuerst(self):
        from datetime import timedelta

        from django.utils import timezone

        from akte.einstellungen import archiv_org_setzen
        from akte.sicherung import nachhol_kandidaten

        archiv_org_setzen(True)
        jetzt = timezone.now()

        def quelle(titel, *versuche):
            q = Quelle.objects.create(titel=titel, url=f"https://x.example/{titel}")
            for vor_stunden, fehler in versuche:
                s = Sicherung.objects.create(quelle=q, art="archive_org", status="fehler", fehler=fehler)
                Sicherung.objects.filter(pk=s.pk).update(erstellt_am=jetzt - timedelta(hours=vor_stunden))
            return q

        nie = quelle("nie")
        alt = quelle("alt", (48, "archive.org antwortet mit 429."))
        juenger = quelle("juenger", (5, "archive.org antwortet mit 503."))
        quelle("dreimal", (30, "429"), (20, "429"), (10, "429"))  # drei Fehlschläge: nicht mehr von selbst
        quelle("verweigert", (30, "Die Adresse enthält Zugangsdaten und geht nicht an archive.org."))
        quelle("eben", (0, "archive.org antwortet mit 429."))  # in der letzten Stunde versucht
        reihe = list(nachhol_kandidaten("archive_org").values_list("id", flat=True))
        self.assertEqual(reihe, [nie.id, alt.id, juenger.id])

    def test_dns_fehler_vor_archive_org_sperrt_nicht_dauerhaft(self):
        from akte.abruf import AbrufFehler
        from akte.sicherung import _archiv_verweigert

        with mock.patch("akte.sicherung.pruefe_url", side_effect=AbrufFehler("Adresse nicht auflösbar: x.example")):
            vorlaeufig = _archiv_verweigert("https://x.example/a")
        with mock.patch("akte.sicherung.pruefe_url",
                        side_effect=AbrufFehler("x.example zeigt nicht ins offene Internet.")):
            dauerhaft = _archiv_verweigert("https://x.example/b")
        self.assertTrue(vorlaeufig.startswith("archive.org später erneut"), vorlaeufig)
        self.assertTrue(dauerhaft.startswith("Nicht an archive.org gegeben"), dauerhaft)

    def test_chargen_bis_alles_durch_ist(self):
        from akte.sicherung import nachholen_charge_jetzt
        from akte.tasks import nachholen_charge, quelle_sichern

        quellen = [Quelle.objects.create(titel=f"q{i}", url=f"https://x.example/{i}") for i in range(3)]
        with mock.patch("akte.sicherung.CHARGE", 2), mock.patch("akte.hintergrund._einreihen") as einreihen:
            self.assertEqual(nachholen_charge_jetzt("original"), 2)
        self.assertEqual(einreihen.call_args_list, [mock.call(quelle_sichern, (quellen[0].id,)),
                                                     mock.call(quelle_sichern, (quellen[1].id,)),
                                                     mock.call(nachholen_charge, ("original", 1))])
        # Die ersten beiden sind inzwischen versucht worden: Die nächste Charge nimmt nur noch die dritte.
        for q in quellen[:2]:
            Sicherung.objects.create(quelle=q, art="original", status="fehler", fehler="404")
        with mock.patch("akte.sicherung.CHARGE", 2), mock.patch("akte.hintergrund._einreihen") as einreihen:
            self.assertEqual(nachholen_charge_jetzt("original", 1), 1)
        einreihen.assert_called_once_with(quelle_sichern, (quellen[2].id,))  # keine weitere Charge: Kette endet

    def test_archiv_charge_endet_wenn_archive_org_aus_ist(self):
        from akte.sicherung import nachholen_charge_jetzt

        Quelle.objects.create(titel="q", url="https://x.example/q")
        with mock.patch("akte.hintergrund._einreihen") as einreihen:
            self.assertEqual(nachholen_charge_jetzt("archive_org"), 0)
        einreihen.assert_not_called()

    def test_archive_org_als_eigener_auftrag_nach_dem_original(self):
        from akte.abruf import Abruf
        from akte.einstellungen import archiv_org_setzen
        from akte.sicherung import quelle_sichern_jetzt
        from akte.tasks import archiv_nachholen

        archiv_org_setzen(True)
        q = Quelle.objects.create(titel="q", url="https://x.example/q.pdf")
        with mock.patch("akte.sicherung.abrufen", return_value=Abruf(q.url, 200, "", b"%PDF-1.4 x")), \
                mock.patch("akte.sicherung.speicher.eingerichtet", return_value=True), \
                mock.patch("akte.sicherung.speicher.ablegen"), \
                mock.patch("akte.hintergrund._einreihen") as einreihen, \
                mock.patch("akte.sicherung.requests") as netz:
            quelle_sichern_jetzt(q)
        einreihen.assert_called_once_with(archiv_nachholen, (q.id, 0))
        netz.get.assert_not_called()  # archive.org nicht im Arbeiter des Originals

    def test_gunicorn_haken_ruft_nachholen_und_startet_auch_bei_fehlern(self):
        import importlib.util
        from pathlib import Path

        datei = Path(__file__).resolve().parents[2] / "gunicorn.conf.py"
        spec = importlib.util.spec_from_file_location("akte_gunicorn_conf", datei)
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)
        with mock.patch("akte.sicherung.nachholen_beim_start") as nachholen:
            modul.post_worker_init(None)
        nachholen.assert_called_once_with()
        with mock.patch("akte.sicherung.nachholen_beim_start", side_effect=RuntimeError("DB weg")), \
                self.assertLogs("akte", level="ERROR"):
            modul.post_worker_init(None)  # wirft nicht: der Worker startet trotzdem

    def test_nur_im_thread_betrieb(self):
        from akte.sicherung import nachholen_beim_start

        Quelle.objects.create(titel="ohne", url="https://x.example/1")
        for art in ("sofort", "celery"):
            with override_settings(AKTE_HINTERGRUND=art), mock.patch("akte.hintergrund._einreihen") as einreihen:
                self.assertEqual(nachholen_beim_start(), {"original": 0, "archiv": 0})
            einreihen.assert_not_called()

    def test_einschalten_von_archive_org_holt_nach(self):
        from akte.einstellungen import archiv_org_setzen
        from akte.tasks import archiv_nachholen

        alt = Quelle.objects.create(titel="alt", url="https://x.example/1")
        with mock.patch("akte.hintergrund._einreihen") as einreihen:
            with self.captureOnCommitCallbacks(execute=True):
                archiv_org_setzen(False)  # aus bleibt aus: nichts
            einreihen.assert_not_called()
            with self.captureOnCommitCallbacks(execute=True):
                archiv_org_setzen(True)
            einreihen.assert_called_once_with(archiv_nachholen, (alt.id, 0))
            with self.captureOnCommitCallbacks(execute=True):
                archiv_org_setzen(True)  # schon an: kein zweites Nachholen
            self.assertEqual(einreihen.call_count, 1)


@override_settings(AKTE_HINTERGRUND="thread", AKTE_SICHERUNG_AKTIV=True, AKTE_BROWSER_AKTIV=False,
                   AKTE_ARCHIV_AKTIV=False)
class EchterThreadTest(_Sauber, TransactionTestCase):
    """Der Arbeiter-Thread mit eigener Datenbankverbindung sichert wirklich (Netz ersetzt)."""

    def setUp(self):
        super().setUp()
        self.ordner = tempfile.mkdtemp()
        self.einst = override_settings(AKTE_SPEICHER_LOKAL=self.ordner, AKTE_R2_BUCKET="")
        self.einst.enable()

    def tearDown(self):
        super().tearDown()
        self.einst.disable()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def test_quelle_wird_im_hintergrund_gesichert_und_nicht_doppelt(self):
        from akte.abruf import Abruf

        c = APIClient()
        konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        c.force_authenticate(konto)
        pdf = b"%PDF-1.4\n" + b"x" * 100
        with mock.patch("akte.sicherung.abrufen", return_value=Abruf("https://x.example/a.pdf", 200, "", pdf)):
            antwort = c.post("/api/v1/akte/quellen/", {"titel": "T", "url": "https://x.example/a.pdf"}, format="json")
            self.assertEqual(antwort.status_code, 201)
            self.assertTrue(hintergrund.warten(WARTEN))
            # „Neu sichern“ einer unveränderten Quelle legt keine zweite Zeile an (E4).
            self.assertEqual(c.post(f"/api/v1/akte/quellen/{antwort.json()['id']}/sichern/").status_code, 202)
            self.assertTrue(hintergrund.warten(WARTEN))
        q = Quelle.objects.get(pk=antwort.json()["id"])
        self.assertEqual(list(Sicherung.objects.filter(quelle=q).values_list("art", "status")), [("original", "fertig")])


@override_settings(AKTE_HINTERGRUND="thread", AKTE_SICHERUNG_AKTIV=True)
class AnfrageWartetNichtTest(TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.einst = override_settings(AKTE_SPEICHER_LOKAL=self.ordner, AKTE_R2_BUCKET="")
        self.einst.enable()
        self.c = APIClient()
        konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.c.force_authenticate(konto)

    def tearDown(self):
        self.einst.disable()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def test_quelle_anlegen_und_sichern_nur_eingereiht(self):
        from akte.tasks import quelle_sichern

        with mock.patch("akte.hintergrund._einreihen") as einreihen, \
                mock.patch("akte.sicherung.abrufen") as abruf, \
                self.captureOnCommitCallbacks(execute=True):
            antwort = self.c.post("/api/v1/akte/quellen/", {"titel": "T", "url": "https://x.example/a"}, format="json")
        self.assertEqual(antwort.status_code, 201)
        einreihen.assert_called_once_with(quelle_sichern, (antwort.json()["id"],))
        abruf.assert_not_called()  # nichts aus dem Netz, solange die Anfrage läuft

        with mock.patch("akte.hintergrund._einreihen") as einreihen, \
                mock.patch("akte.sicherung.abrufen") as abruf, \
                self.captureOnCommitCallbacks(execute=True):
            antwort = self.c.post(f"/api/v1/akte/quellen/{antwort.json()['id']}/sichern/")
        self.assertEqual((antwort.status_code, antwort.json()), (202, {"angestossen": True}))
        einreihen.assert_called_once()
        abruf.assert_not_called()

    def test_faden_mit_zitat_reiht_die_fundstelle_ein(self):
        from akte.models import Entitaet
        from akte.tasks import fundstelle_sichern

        a = Entitaet.objects.create(name="A", slug="a", typ="firma")
        b = Entitaet.objects.create(name="B", slug="b", typ="firma")
        q = Quelle.objects.create(titel="Q")
        with mock.patch("akte.hintergrund._einreihen") as einreihen, self.captureOnCommitCallbacks(execute=True):
            antwort = self.c.post("/api/v1/akte/verbindungen/", {
                "von": a.id, "nach": b.id, "typ": "auftrag",
                "belege": [{"quelle": q.id, "zitat_woertlich": "Ein Satz aus der Quelle, wörtlich."}]}, format="json")
        self.assertEqual(antwort.status_code, 201)
        einreihen.assert_called_once_with(fundstelle_sichern, (antwort.json()["belege"][0]["id"],))
