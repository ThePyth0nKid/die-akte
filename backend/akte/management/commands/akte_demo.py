"""Erfundene Demo-Akte „Freie Stadt Musterhafen“: alles, was die Akte kann, an ausgedachten Beispielen.

    python manage.py akte_demo                    # anlegen (einmalig)
    python manage.py akte_demo --neu              # Board und Demo-Objekte entfernen und neu anlegen
    python manage.py akte_demo --oeffentlich      # das Demo-Board zusätzlich öffentlich schalten

Alle Personen, Firmen, Behörden, Gesetze und Dokumente sind erfunden. Die Quellen sind PDFs, die dieser Befehl
erzeugt; deshalb funktionieren Beweissicherung und Fundstellen ohne Internet. Absichtlich dabei:

* ein Zitat, das leicht vom Wortlaut abweicht (Fundstelle „nicht gefunden“),
* ein Faden zu einer Privatperson über Familie (sperrt, bis ein Mensch mit Begründung überstimmt),
* alle drei Faden-Arten: belegt, ein Verdacht (bleibt Entwurf) und eine Meinung (unterschrieben),
* Kartenbilder in jeder Variante: KI-Fotos mit Kennzeichnung, Logo und Wappen als eigene Zeichnung, eine
  Privatperson nur mit Initialen. Die Bilder liegen unter ``akte/static/akte/demo/`` (CC0) und kommen mit der Akte,
* signierte Freigaben mit einem Demo-Schlüssel, damit ``akte pruefe-signaturen`` sofort etwas zu prüfen hat.

Demo-Objekte tragen die Markierung ``akte-demo`` (Karten im Feld ``tags``, Quellen in ``notiz``). ``--neu`` löscht nur
markierte Objekte, nie gleichnamige eigene.

Der Befehl arbeitet über die eigene API (im selben Prozess) – so gelten dieselben Prüfungen wie in der Oberfläche.
Der private Demo-Schlüssel wird nach dem Lauf verworfen.
"""

from __future__ import annotations

from akte_beweis import b64url, b64url_lesen, oeffentlicher_schluessel
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings
from rest_framework.test import APIClient

from akte.demo_pdf import pdf
from akte.models import Board, Entitaet, Quelle
from akte.permissions import REDAKTION_GRUPPE

SLUG = "demo-musterhafen"
MARKE = "akte-demo"
A = "/api/v1/akte"

KARTEN = [
    # schluessel, name, typ, kurz, öffentliche Person
    ("senat", "Senat der Freien Stadt Musterhafen", "behoerde", "Landesregierung", False),
    ("rechnungshof", "Rechnungshof Musterhafen", "behoerde", "prüft die Haushaltsführung", False),
    ("nordlicht", "Nordlicht Analytik GmbH", "firma", "Datenanalyse für Behörden", False),
    ("kranich", "Kranich Holding AG", "firma", "Beteiligungsgesellschaft", False),
    ("erika", "Erika Mustermann", "person", "Senatorin für Inneres", True),
    ("max", "Max Mustermann", "person", "Vorstand der Nordlicht Analytik GmbH", True),
    ("thea", "Thea Beispiel", "person", "Privatperson", False),
    ("mdag", "Musterhafener Datengesetz (MDAG) § 4", "gesetz", "Entwurf: zentrale Datenauswertung", False),
    ("kameras", "Verkehrskameras Musterhafen", "system", "Kameranetz an den Kreuzungen der Stadt", False),
]

# Bild und Nachweis je Karte. Der Nachweis steht auf der Karte; „Logo:“ und „Wappen:“ am Anfang zeigen das Bild als
# Zeichen auf hellem Grund (web/src/lib/akte/ordnung.ts, bildArt). Thea bleibt mit Absicht ohne Bild, MDAG auch.
BILD = "/static/akte/demo/"
BILDER = {
    "erika": (BILD + "erika-mustermann.webp", "KI-Bild · erfundene Person"),
    "max": (BILD + "max-mustermann.webp", "KI-Bild · erfundene Person"),
    "rechnungshof": (BILD + "rechnungshof.webp", "KI-Bild · erfundenes Gebäude"),
    "kameras": (BILD + "verkehrskameras.webp", "KI-Bild · erfundene Anlage"),
    "senat": (BILD + "senat-wappen.svg", "Wappen: Freie Stadt Musterhafen (erfunden) · eigene Zeichnung"),
    "nordlicht": (BILD + "nordlicht-logo.svg", "Logo: Nordlicht Analytik GmbH (erfunden) · eigene Zeichnung"),
    "kranich": (BILD + "kranich-logo.svg", "Logo: Kranich Holding AG (erfunden) · eigene Zeichnung"),
}

QUELLEN = {
    "drs": ("Drucksache 9/1234 – Antwort des Senats", "Bürgerschaft Musterhafen", "primaer", [
        ["Antwort des Senats auf die Kleine Anfrage zur Datenauswertung.",
         "Der Senat beauftragt die Nordlicht Analytik GmbH mit der Auswertung der Verkehrsdaten.",
         "Das Auftragsvolumen beträgt 1.250.000 Euro.",
         "Die Verkehrsdaten stammen aus dem Netz der Verkehrskameras; zuständig ist die Senatorin für Inneres."],
        ["Der Entwurf des Musterhafener Datengesetzes sieht in § 4 eine zentrale Auswertung vor.",
         "Die Daten werden zentral gespeichert."],
    ]),
    "register": ("Handelsregister Musterhafen HRB 4711", "Registergericht Musterhafen", "primaer", [
        ["Nordlicht Analytik GmbH, Sitz Musterhafen.", "Vorstand: Max Mustermann, bestellt am 01.04.2019."],
    ]),
    "jahresbericht": ("Jahresbericht 2025 der Kranich Holding AG", "Kranich Holding AG", "primaer", [
        ["Beteiligungen: Die Kranich Holding AG hält 60 Prozent an der Nordlicht Analytik GmbH."],
    ]),
    "amtsblatt": ("Amtsblatt Musterhafen 3/2022", "Senatskanzlei Musterhafen", "primaer", [
        ["Erika Mustermann wird mit Wirkung vom 15.02.2022 zur Senatorin für Inneres ernannt."],
    ]),
    "pruefbericht": ("Prüfbericht 2025 des Rechnungshofs", "Rechnungshof Musterhafen", "primaer", [
        ["Feststellung 7: Die Vergabe erfolgte ohne öffentliche Ausschreibung.",
         "Der Rechnungshof empfiehlt, künftige Aufträge auszuschreiben."],
    ]),
    "zeitung": ("Musterhafener Rundschau, 12.05.2025", "Musterhafener Rundschau", "sekundaer", [
        ["Thea Beispiel ist die Schwester von Max Mustermann, berichten Nachbarn.",
         "Aus der Verwaltung heißt es, die Kranich Holding AG habe die Kameras geliefert."],
    ]),
}

FAEDEN = [
    # von, nach, typ, beschreibung, start, ende/aktuell, aussageart, beleg(quelle, zitat, fundstelle), freigeben
    ("senat", "nordlicht", "auftrag", "beauftragt Datenauswertung", "2024-03-01", "aktuell", "belegt",
     ("drs", "Der Senat beauftragt die Nordlicht Analytik GmbH mit der Auswertung der Verkehrsdaten.", "S. 1"), True),
    ("max", "nordlicht", "amt", "Vorstand", "2019-04-01", "aktuell", "belegt",
     ("register", "Vorstand: Max Mustermann, bestellt am 01.04.2019.", "HRB 4711"), True),
    ("kranich", "nordlicht", "eigentum", "hält 60 %", "2025-01-01", "aktuell", "belegt",
     ("jahresbericht", "Die Kranich Holding AG hält 60 Prozent an der Nordlicht Analytik GmbH.", "Beteiligungen"),
     True),
    ("erika", "senat", "amt", "Senatorin für Inneres", "2022-02-15", "aktuell", "belegt",
     ("amtsblatt", "Erika Mustermann wird mit Wirkung vom 15.02.2022 zur Senatorin für Inneres ernannt.", "S. 1"),
     True),
    ("nordlicht", "mdag", "gesetz_betrifft", "zentrale Auswertung (Entwurf)", "2025-06-01", "", "belegt",
     ("drs", "Der Entwurf des Musterhafener Datengesetzes sieht in § 4 eine zentrale Auswertung vor.", "S. 2"), True),
    # Absichtlich leicht falsch zitiert („öffentliche“ fehlt): die Fundstelle findet es nicht.
    ("rechnungshof", "senat", "aussage", "rügt Vergabe", "2025-05-01", "", "belegt",
     ("pruefbericht", "Die Vergabe erfolgte ohne Ausschreibung.", "Feststellung 7"), False),
    # Privatperson über Familie: sperrt von Haus aus.
    ("thea", "max", "familie", "verwandt", "2025-05-12", "aktuell", "belegt",
     ("zeitung", "Thea Beispiel ist die Schwester von Max Mustermann, berichten Nachbarn.", "S. 1"), False),
    # Nur eine Stimme aus der Verwaltung: ein Verdacht, kein Beleg. Bleibt Entwurf und damit intern.
    ("kranich", "kameras", "auftrag", "soll die Kameras geliefert haben", "2023-09-01", "aktuell", "verdacht",
     ("zeitung", "Aus der Verwaltung heißt es, die Kranich Holding AG habe die Kameras geliefert.", "S. 1"), False),
    # Einschätzung der Redaktion auf belegter Grundlage, als Meinung gekennzeichnet und unterschrieben.
    ("erika", "kameras", "sonstiges", "trägt die politische Verantwortung", "2022-02-15", "aktuell", "meinung",
     ("drs", "Die Verkehrsdaten stammen aus dem Netz der Verkehrskameras; zuständig ist die Senatorin für Inneres.",
      "S. 1"), True),
]

RAHMEN = {
    "Der Auftrag": ["Senat der Freien Stadt Musterhafen", "Nordlicht Analytik GmbH", "Erika Mustermann",
                    "Verkehrskameras Musterhafen"],
    "Die Eigentümer": ["Kranich Holding AG", "Max Mustermann", "Thea Beispiel"],
    "Kontrolle und Gesetz": ["Rechnungshof Musterhafen", "Musterhafener Datengesetz (MDAG) § 4"],
}

FAHRT = {
    "titel": "Wer wertet Musterhafens Daten aus?", "format": "16:9",
    "stationen": [
        {"fokus": [], "stichwort": "Die ganze Wand", "dauer_ms": 2500},
        {"fokus": ["Senat der Freien Stadt Musterhafen", "Nordlicht Analytik GmbH"], "stichwort": "Der Auftrag",
         "beweis": "Drucksache 9/1234 – Antwort des Senats",
         "zitat": "Der Senat beauftragt die Nordlicht Analytik GmbH mit der Auswertung der Verkehrsdaten."},
        {"fokus": ["Kranich Holding AG", "Max Mustermann", "Nordlicht Analytik GmbH"], "stichwort": "Wem gehört sie?"},
        {"fokus": ["Rechnungshof Musterhafen"], "stichwort": "Die Rüge"},
    ],
}


class Command(BaseCommand):
    help = "Erfundene Demo-Akte „Freie Stadt Musterhafen“ anlegen."

    def add_arguments(self, parser):
        parser.add_argument("--neu", action="store_true", help="vorhandene Demo entfernen und neu anlegen")
        parser.add_argument("--oeffentlich", action="store_true", help="Demo-Board öffentlich schalten")
        parser.add_argument("--benutzer", default="demo-redaktion", help="Redaktionskonto, unter dem angelegt wird")

    def handle(self, *args, **opts):
        if Board.objects.filter(slug=SLUG).exists():
            if not opts["neu"]:
                raise CommandError(f"Board {SLUG} gibt es schon. Mit --neu neu anlegen.")
            Board.objects.filter(slug=SLUG).delete()
            demo = [e.pk for e in Entitaet.objects.filter(name__in=[k[1] for k in KARTEN]) if MARKE in (e.tags or [])]
            Entitaet.objects.filter(pk__in=demo).delete()
            Quelle.objects.filter(titel__in=[q[0] for q in QUELLEN.values()], notiz=MARKE).delete()

        konto, _ = get_user_model().objects.get_or_create(username=opts["benutzer"])
        konto.groups.add(Group.objects.get_or_create(name=REDAKTION_GRUPPE)[0])
        api = APIClient(HTTP_HOST="localhost")
        api.force_authenticate(konto)

        def ok(antwort, erwartet=(200, 201, 204)):
            if antwort.status_code not in erwartet:
                raise CommandError(f"{antwort.request['PATH_INFO']}: {antwort.status_code} {antwort.content[:300]!r}")
            return antwort.json() if antwort.content else None

        # Gleich hier sichern (nicht im Hintergrund-Thread): der Befehl endet sonst, bevor die Fundstellen da sind.
        with override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False,
                               AKTE_HINTERGRUND="sofort"):
            ok(api.post(f"{A}/boards/", {"titel": "Freie Stadt Musterhafen (Demo)", "slug": SLUG, "beschreibung":
                       "Erfundenes Beispiel: Wer wertet die Daten der Stadt aus? Alle Namen sind ausgedacht."},
                        format="json"))
            karten = {}
            for i, (schl, name, typ, kurz, oeffentlich) in enumerate(KARTEN):
                # Das Bild gleich beim Anlegen: es gehört damit zum unterschriebenen Inhalt der Karte.
                bild_url, bild_nachweis = BILDER.get(schl, ("", ""))
                e = ok(api.post(f"{A}/entitaeten/", {"name": name, "typ": typ, "kurzbeschreibung": kurz,
                                                     "oeffentliche_person": oeffentlich, "tags": [MARKE],
                                                     "bild_url": bild_url, "bild_nachweis": bild_nachweis},
                                format="json"))
                karten[schl] = e
                ok(api.post(f"{A}/boards/{SLUG}/karten/", {"entitaet": e["id"], "x": (i % 4) * 400, "y": (i // 4) * 500},
                            format="json"))
            quellen = {}
            for schl, (titel, herausgeber, guete, seiten) in QUELLEN.items():
                q = ok(api.post(f"{A}/quellen/", {"titel": titel, "herausgeber": herausgeber, "guete": guete,
                                                  "abgerufen_am": "2026-10-01", "notiz": MARKE}, format="json"))
                datei = SimpleUploadedFile(f"{schl}.pdf", pdf(seiten, titel=titel), content_type="application/pdf")
                ok(api.post(f"{A}/quellen/{q['id']}/anhang/", {"datei": datei}, format="multipart"))
                quellen[schl] = q
            faeden = []
            for von, nach, typ, text, start, ende, art, (qs, zitat, fundstelle), freigeben in FAEDEN:
                v = ok(api.post(f"{A}/verbindungen/", {
                    "von": karten[von]["id"], "nach": karten[nach]["id"], "typ": typ, "beschreibung": text,
                    "start": start, "aktuell": ende == "aktuell", "aussageart": art,
                    "belege": [{"quelle": quellen[qs]["id"], "zitat_woertlich": zitat, "fundstelle": fundstelle}],
                }, format="json"))
                faeden.append((v, freigeben))
            wand = ok(api.get(f"{A}/boards/{SLUG}/"))
            je_name = {k["entitaet_detail"]["name"]: k for k in wand["karten"]}
            positionen = []
            for i, (titel, namen) in enumerate(RAHMEN.items()):
                ox = (i + 1) * 20000
                for j, n in enumerate(namen):
                    positionen.append({"art": "karte", "id": je_name[n]["id"], "x": ox + (j % 4) * 340, "y": 0})
                ok(api.post(f"{A}/boards/{SLUG}/rahmen/", {"titel": titel, "x": ox - 60, "y": -60,
                                                          "breite": min(len(namen), 4) * 340 + 60, "hoehe": 590,
                                                          "farbe": "#C8102E" if i == 0 else ""}, format="json"))
            ok(api.post(f"{A}/boards/{SLUG}/positionen/", positionen, format="json"))
            for art, text in (("frage", "Wer hat den Auftrag ohne Ausschreibung vergeben?"),
                              ("meinung", "Meinung der Redaktion: Ein Auftrag dieser Größe gehört ausgeschrieben.")):
                ok(api.post(f"{A}/boards/{SLUG}/zettel/", {"art": art, "text": text, "x": 0, "y": 0}, format="json"))
            ok(api.post(f"{A}/boards/{SLUG}/aufraeumen/"))
            ok(api.post(f"{A}/boards/{SLUG}/fahrten/aus-beschreibung/", FAHRT, format="json"))

            # Signierte Freigaben mit einem Wegwerf-Demo-Schlüssel (der private Teil wird nicht gespeichert).
            privat = Ed25519PrivateKey.generate()
            kid = ok(api.post(f"{A}/beweis/schluessel/", {"oeffentlich": b64url(oeffentlicher_schluessel(privat))},
                              format="json"))["kid"]

            def freigeben(objekt, objekt_id):
                vor = ok(api.post(f"{A}/beweis/freigabe/vorbereiten/", {"objekt": objekt, "id": objekt_id,
                                                                        "kid": kid}, format="json"))
                sig = privat.sign(b64url_lesen(vor["signing_input"]))
                ok(api.post(f"{A}/beweis/freigabe/abschliessen/", {"event_id": vor["event_id"],
                                                                   "signatur": b64url(sig)}, format="json"))

            # Alle Karten freigeben, auch die Privatperson: Besucher sehen sie dann mit Initialen.
            for schl, *_ in KARTEN:
                freigeben("karte", karten[schl]["id"])
            for v, frei in faeden:
                if frei:
                    freigeben("faden", v["id"])
            if opts["oeffentlich"]:
                ok(api.patch(f"{A}/boards/{SLUG}/", {"oeffentlich": True}, format="json"))

        self.stdout.write(self.style.SUCCESS(
            f"Demo-Akte angelegt: /akte/{SLUG}  ({len(KARTEN)} Karten, {len(QUELLEN)} Quellen, {len(FAEDEN)} Fäden)"))
        self.stdout.write("Prüfen: akte pruefung " + SLUG + "   ·   Kette: akte pruefe-signaturen")
