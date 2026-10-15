"""E4: Kippt eine neue Original-Kopie nach der Unterschrift einen Faden auf „verändert seit Freigabe“?

Ergebnis (so ist es gebaut, ``beweisschicht._original`` und ``_nachgereicht``):
* Solange die unterschriebene Kopie noch da ist, bleibt sie maßgeblich: Eine spätere zweite Kopie (auch mit anderem
  Inhalt, die Seite hat sich geändert) kippt den Faden NICHT.
* Fehlte beim Unterschreiben jede Kopie, darf die erste später nachkommen, ohne dass der Faden kippt.
* Verschwindet die unterschriebene Kopie (Zeile gelöscht), zählt die jüngste übrige: Der Faden kippt, ein Mensch
  muss neu unterschreiben. Prüfen und „Neu sichern“ löschen nie eine Kopie.
"""

from datetime import date

from akte_beweis import b64url, b64url_lesen, oeffentlicher_schluessel
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from akte.beweisschicht import veraendert_seit_freigabe
from akte.models import Beleg, Entitaet, Quelle, Sicherung, Status, Verbindung
from akte.permissions import REDAKTION_GRUPPE

User = get_user_model()
B = "/api/v1/akte/beweis"


class KopieNachFreigabeTest(TestCase):
    def setUp(self):
        konto = User.objects.create_user("redaktion", "redaktion@example.org", "pw")
        konto.groups.add(Group.objects.create(name=REDAKTION_GRUPPE))
        self.mensch = APIClient()
        self.mensch.force_authenticate(konto)
        self.privat = Ed25519PrivateKey.generate()
        r = self.mensch.post(f"{B}/schluessel/", {"oeffentlich": b64url(oeffentlicher_schluessel(self.privat))},
                             format="json")
        self.kid = r.json()["kid"]
        a = Entitaet.objects.create(name="Senat Musterhafen", slug="senat", typ="behoerde")
        b = Entitaet.objects.create(name="Nordlicht Analytik GmbH", slug="nordlicht", typ="firma")
        self.quelle = Quelle.objects.create(titel="Drucksache 9/1234", url="https://buergerschaft.beispiel.test/d.pdf",
                                            abgerufen_am=date(2026, 10, 1))
        self.faden = Verbindung.objects.create(von=a, nach=b, typ="auftrag", beschreibung="beauftragt",
                                               start=date(2024, 1, 1), aktuell=True)
        Beleg.objects.create(verbindung=self.faden, quelle=self.quelle, zitat_woertlich="Der Senat beauftragt")

    def kopie(self, zeichen: str) -> Sicherung:
        return Sicherung.objects.create(quelle=self.quelle, art="original", status="fertig", sha256=zeichen * 64)

    def unterschreiben(self):
        vor = self.mensch.post(f"{B}/freigabe/vorbereiten/", {"objekt": "faden", "id": self.faden.pk, "kid": self.kid,
                                                               "ueberstimmungen": {}}, format="json")
        self.assertEqual(vor.status_code, 200, vor.content)
        signatur = self.privat.sign(b64url_lesen(vor.json()["signing_input"]))
        r = self.mensch.post(f"{B}/freigabe/abschliessen/", {"event_id": vor.json()["event_id"],
                                                             "signatur": b64url(signatur)}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.faden.refresh_from_db()
        self.assertEqual(self.faden.status, Status.FREIGEGEBEN)

    def veraendert(self) -> bool:
        return veraendert_seit_freigabe(Verbindung.objects.get(pk=self.faden.pk), "faden")

    def test_zweite_kopie_kippt_den_faden_nicht(self):
        self.kopie("a")
        self.unterschreiben()
        self.kopie("b")  # die Seite hat sich geändert, neu gesichert
        self.assertFalse(self.veraendert())

    def test_erste_kopie_darf_nachkommen(self):
        self.unterschreiben()
        self.kopie("a")
        self.assertFalse(self.veraendert())

    def test_verschwundene_unterschriebene_kopie_kippt(self):
        alt = self.kopie("a")
        self.unterschreiben()
        self.kopie("b")
        alt.delete()
        self.assertTrue(self.veraendert())
