"""Die Akte — Personen, Organisationen und belegte Verbindungen auf einer Wand.

Drei Sichten auf dieselben Daten:

* **Graph** — ``Entitaet`` sind die Knoten, ``Verbindung`` die typisierten Kanten.
  Eine Verbindung ist ein eigenes Objekt mit Zeitraum und Belegen (Vorbild:
  FollowTheMoney von OCCRP, Kategorien nach LittleSis).
* **Notiz** — jede Entität trägt ``notiz_md`` mit ``[[Links]]``; der Export
  schreibt daraus einen Obsidian-Vault.
* **Wand** — ``Board`` legt Karten, Zettel und Rahmen auf eine Leinwand. Eine
  Entität kann auf vielen Boards liegen und bleibt dieselbe, mit denselben Quellen.

Die Wand erzwingt Belege. Was davon veröffentlicht werden darf, entscheidet
allein ``akte/pruefung.py`` — keine View und kein Serializer entscheidet selbst.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


class Status(models.TextChoices):
    ENTWURF = "entwurf", "Entwurf"
    VORSCHLAG = "vorschlag", "Vorschlag"
    FREIGEGEBEN = "freigegeben", "Freigegeben"


class EntitaetTyp(models.TextChoices):
    PERSON = "person", "Person"
    ORGANISATION = "organisation", "Organisation"
    FIRMA = "firma", "Firma"
    BEHOERDE = "behoerde", "Behörde"
    PARTEI = "partei", "Partei"
    EREIGNIS = "ereignis", "Ereignis"
    GESETZ = "gesetz", "Gesetz / Verfahren"
    SYSTEM = "system", "System / Produkt"
    ORT = "ort", "Ort"
    DOKUMENT = "dokument", "Dokument"


class Guete(models.TextChoices):
    """Wie in den Belegblättern: ★ Original geöffnet, ☆ Presse oder Sekundär."""

    PRIMAER = "primaer", "★ Original"
    SEKUNDAER = "sekundaer", "☆ Presse / Sekundär"


class VerbindungTyp(models.TextChoices):
    AMT = "amt", "Amt / Position"
    EIGENTUM = "eigentum", "Eigentum / Beteiligung"
    FINANZIERUNG = "finanzierung", "Finanzierung / Zahlung"
    MITGLIEDSCHAFT = "mitgliedschaft", "Mitgliedschaft"
    AUFTRAG = "auftrag", "Auftrag / Vertrag"
    LOBBY = "lobby", "Lobby / Beratung"
    GESETZ_BETRIFFT = "gesetz_betrifft", "Gesetz betrifft"
    AUSSAGE = "aussage", "Aussage / Zitat"
    FAMILIE = "familie", "Familie"
    SONSTIGES = "sonstiges", "Sonstiges"


class Aussageart(models.TextChoices):
    """Was ein Faden behauptet. Bestimmt sein Aussehen auf der Wand."""

    BELEGT = "belegt", "Belegt"
    VERDACHT = "verdacht", "Verdacht"
    MEINUNG = "meinung", "Meinung"


class Zeitstempel(models.Model):
    erstellt_am = models.DateTimeField(auto_now_add=True)
    geaendert_am = models.DateTimeField(auto_now=True)
    erstellt_von = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True


class Entitaet(Zeitstempel):
    typ = models.CharField(max_length=20, choices=EntitaetTyp.choices)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    kurzbeschreibung = models.CharField(max_length=300, blank=True)
    notiz_md = models.TextField(blank=True, help_text="Obsidian-Notiz, [[Name]] verlinkt.")
    bild_url = models.URLField(blank=True)
    #: Pflicht bei fremden Fotos: „Foto: <Urheber>, CC BY-SA 4.0, Wikimedia Commons“ — steht auf der Karte.
    bild_nachweis = models.CharField(max_length=200, blank=True)
    wikidata_qid = models.CharField(max_length=20, blank=True)
    tags = models.JSONField(default=list, blank=True)
    #: Nur Personen mit Amt, Macht oder öffentlicher Rolle werden öffentlich mit
    #: Namen und Bild gezeigt. Alle anderen erscheinen mit Initialen (Regel 6).
    oeffentliche_person = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ENTWURF)

    class Meta:
        ordering = ["name"]
        verbose_name = "Entität"
        verbose_name_plural = "Entitäten"

    def __str__(self):
        return self.name

    @property
    def ist_privatperson(self) -> bool:
        return self.typ == EntitaetTyp.PERSON and not self.oeffentliche_person

    def initialen(self) -> str:
        teile = [t for t in self.name.split() if t]
        return " ".join(f"{t[0]}." for t in teile) or "?"


class Quelle(Zeitstempel):
    url = models.URLField(max_length=1000, blank=True)
    titel = models.CharField(max_length=300)
    herausgeber = models.CharField(max_length=200, blank=True)
    veroeffentlicht_am = models.DateField(null=True, blank=True)
    abgerufen_am = models.DateField(null=True, blank=True)
    archiv_url = models.URLField(max_length=1000, blank=True)
    datei_url = models.URLField(max_length=1000, blank=True, help_text="PDF-Kopie auf R2.")
    guete = models.CharField(max_length=20, choices=Guete.choices, default=Guete.SEKUNDAER)
    notiz = models.TextField(blank=True)
    #: Aus der Seite gelesen (og:title, og:site_name, Beschreibung) — für die Link-Vorschau.
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-abgerufen_am", "titel"]
        verbose_name_plural = "Quellen"

    def __str__(self):
        return self.titel


class Verbindung(Zeitstempel):
    von = models.ForeignKey(Entitaet, on_delete=models.CASCADE, related_name="ausgehend")
    nach = models.ForeignKey(Entitaet, on_delete=models.CASCADE, related_name="eingehend")
    typ = models.CharField(max_length=30, choices=VerbindungTyp.choices)
    beschreibung = models.CharField(max_length=300, blank=True, help_text="z. B. „Mitgründer“")
    start = models.DateField(null=True, blank=True)
    ende = models.DateField(null=True, blank=True)
    aktuell = models.BooleanField(default=False)
    betrag = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    waehrung = models.CharField(max_length=3, blank=True)
    aussageart = models.CharField(
        max_length=20, choices=Aussageart.choices, default=Aussageart.BELEGT
    )
    #: 1 schwach · 2 mittel · 3 stark — eigene Einschätzung, FtM kennt das Feld nicht.
    konfidenz = models.PositiveSmallIntegerField(default=2)
    #: Anhörung vor Verdachtsberichterstattung (BGH VI ZR 1241/20).
    anhoerung_angefragt_am = models.DateField(null=True, blank=True)
    anhoerung_antwort = models.TextField(blank=True)
    anhoerung_antwort_am = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ENTWURF)
    quellen = models.ManyToManyField(Quelle, through="Beleg", related_name="verbindungen")

    class Meta:
        ordering = ["-start", "id"]
        verbose_name_plural = "Verbindungen"

    def __str__(self):
        return f"{self.von} → {self.nach} ({self.get_typ_display()})"


class Beleg(models.Model):
    verbindung = models.ForeignKey(Verbindung, on_delete=models.CASCADE, related_name="belege")
    quelle = models.ForeignKey(Quelle, on_delete=models.PROTECT, related_name="belege")
    zitat_woertlich = models.TextField(blank=True)
    fundstelle = models.CharField(max_length=120, blank=True, help_text="Seite, Absatz, Zeitmarke")

    class Meta:
        unique_together = [("verbindung", "quelle")]
        verbose_name_plural = "Belege"


class BoardLook(models.TextChoices):
    DUNKEL = "dunkel", "Dunkel"
    PAPIER = "papier", "Papier / Kork"


class Board(Zeitstempel):
    titel = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    beschreibung = models.TextField(blank=True)
    look = models.CharField(max_length=20, choices=BoardLook.choices, default=BoardLook.DUNKEL)
    #: Nur ein Wunsch. Ob etwas öffentlich erscheint, entscheidet zusätzlich
    #: ``settings.AKTE_OEFFENTLICH_AKTIV`` und die Prüfung je Faden.
    oeffentlich = models.BooleanField(default=False)
    ausgeblendete_verbindungen = models.ManyToManyField(Verbindung, blank=True, related_name="+")
    #: Stufen der Prüfregeln für dieses Board: {code: "aus" | "hinweis" | "sperrt"} (akte/regeln.py).
    regeln = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-geaendert_am"]

    def __str__(self):
        return self.titel


class BoardKarte(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="karten")
    entitaet = models.ForeignKey(Entitaet, on_delete=models.CASCADE, related_name="karten")
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)
    farbe = models.CharField(max_length=20, blank=True)

    class Meta:
        unique_together = [("board", "entitaet")]


class Mappe(models.Model):
    """Ein anderes Board als Aktenmappe auf dieser Wand. Man klickt hinein und gräbt tiefer.

    Die Mappe steht auf der Elternwand für alle Karten ihres Unter-Boards (rekursiv). Sie ist
    keine Entität: ein Faden kann nie an einer Mappe hängen, nur an belegten Karten. Und sie gibt
    kein Leserecht weiter: Mitglieder sehen nur Mappen, deren Ziel freigeschaltet ist.
    """

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="mappen")
    ziel = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="in_mappen")
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)
    #: #RRGGBB wie beim Rahmen; leer = Manila. Am Feld geprüft, damit auch Admin und ORM kein CSS durchlassen.
    farbe = models.CharField(max_length=20, blank=True,
                             validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "Farbe als #RRGGBB, z. B. #C8102E.")])

    class Meta:
        unique_together = [("board", "ziel")]
        constraints = [
            models.CheckConstraint(condition=~models.Q(board=models.F("ziel")), name="mappe_nicht_in_sich_selbst"),
        ]
        ordering = ["id"]
        verbose_name_plural = "Mappen"

    def clean(self):
        """Auch im Admin: kein Board in sich selbst, kein Kreis."""
        from .mappen import kinder_aus, wuerde_zyklus

        if self.board_id and self.ziel_id:
            kanten = Mappe.objects.exclude(pk=self.pk).values_list("board_id", "ziel_id")
            if wuerde_zyklus(self.board_id, self.ziel_id, kinder_aus(kanten)):
                raise ValidationError("Das ergäbe einen Kreis: diese Wand steckt schon in der Mappe.")


class ZettelArt(models.TextChoices):
    NOTIZ = "notiz", "Notiz"
    MEINUNG = "meinung", "Meine Einschätzung"
    FRAGE = "frage", "Offene Frage"


class Zettel(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="zettel")
    art = models.CharField(max_length=20, choices=ZettelArt.choices, default=ZettelArt.NOTIZ)
    text = models.TextField()
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)

    class Meta:
        verbose_name_plural = "Zettel"


class Rahmen(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="rahmen")
    titel = models.CharField(max_length=120)
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)
    breite = models.FloatField(default=600)
    hoehe = models.FloatField(default=400)
    farbe = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name_plural = "Rahmen"


class Fahrt(models.Model):
    """Ein Präsentationspfad für die Aufnahme: Station für Station über die Wand."""

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="fahrten")
    titel = models.CharField(max_length=120)

    class Meta:
        verbose_name_plural = "Fahrten"


class Station(models.Model):
    fahrt = models.ForeignKey(Fahrt, on_delete=models.CASCADE, related_name="stationen")
    position = models.PositiveIntegerField()
    x = models.FloatField()
    y = models.FloatField()
    zoom = models.FloatField(default=1)
    #: IDs der Entitäten, die der Scheinwerfer hervorhebt. Leer = nichts dimmen.
    fokus = models.JSONField(default=list, blank=True)
    stichwort = models.CharField(max_length=200, blank=True)
    dauer_ms = models.PositiveIntegerField(default=1200)
    #: Beweis-Ansicht: dieses Dokument wird groß aufgezogen, das Zitat gelb markiert.
    beweis_quelle = models.ForeignKey("Quelle", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    beweis_zitat = models.TextField(blank=True)
    #: Sprechtext der Station (gesichtsloses Video): die Stimme liest ihn, die Kamera kommt beim ersten Wort an.
    text = models.TextField(blank=True)
    #: Zahlen- oder Zitatkarte über der Wand: {"gross": "39 Mio.", "klein": "…", "quelle": "…", "voll": false}.
    einblendung = models.JSONField(default=dict, blank=True)
    #: O-Ton-Einspieler (nur Render, lokal): {"datei": "D:\\…\\F2.mp4", "ab": 0.0, "bis": 6.3, "quelle": "…",
    #: "freeze_ms": 700}. Die Stimme schweigt, der Originalton läuft; Clip + Standbild zeigen die Quelle mindestens
    #: 5 s (Hausregel zu § 51 UrhG, das Standbild wird bei kurzen Clips verlängert).
    einspieler = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["position"]
        unique_together = [("fahrt", "position")]
        verbose_name_plural = "Stationen"


class Verlauf(models.Model):
    """Jede Änderung an der Akte, mit Stand danach — damit jede Aussage später verteidigt werden kann."""

    objekt_art = models.CharField(max_length=40)
    objekt_id = models.PositiveBigIntegerField()
    aktion = models.CharField(max_length=20)
    nutzer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    zeitpunkt = models.DateTimeField(auto_now_add=True)
    stand = models.JSONField(default=dict)

    class Meta:
        ordering = ["-zeitpunkt"]
        indexes = [models.Index(fields=["objekt_art", "objekt_id"])]
        verbose_name_plural = "Verlauf"


class SicherungArt(models.TextChoices):
    ORIGINAL = "original", "Original (Datei/Seite)"
    VORSCHAU = "vorschau", "Vorschaubild"
    SCREENSHOT = "screenshot", "Bild der Seite"
    SEITE_PDF = "seite_pdf", "Seite als PDF"
    FUNDSTELLE = "fundstelle", "Fundstelle markiert"
    ARCHIVE_ORG = "archive_org", "archive.org"
    VIDEO_LOKAL = "video_lokal", "Video im ARCHIV (D:)"
    ANHANG = "anhang", "Anhang"


class SicherungStatus(models.TextChoices):
    WARTET = "wartet", "Wartet"
    LAEUFT = "laeuft", "Läuft"
    FERTIG = "fertig", "Gesichert"
    FEHLER = "fehler", "Fehler"


class Sicherung(models.Model):
    """Eine gesicherte Kopie einer Quelle — damit das Internet sie nicht einfach löschen kann.

    Jeder Lauf ist eine neue Zeile; angezeigt wird je Art die jüngste. Die Datei liegt
    inhaltsadressiert im privaten Speicher (``akte/speicher.py``), die Prüfsumme
    belegt später, dass sie unverändert ist.
    """

    quelle = models.ForeignKey(Quelle, on_delete=models.CASCADE, related_name="sicherungen")
    beleg = models.ForeignKey("Beleg", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    art = models.CharField(max_length=20, choices=SicherungArt.choices)
    status = models.CharField(max_length=10, choices=SicherungStatus.choices, default=SicherungStatus.WARTET)
    schluessel = models.CharField(max_length=200, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    bytes = models.PositiveBigIntegerField(default=0)
    mime = models.CharField(max_length=100, blank=True)
    dateiname = models.CharField(max_length=200, blank=True)
    #: Fremde Kopie (archive.org) oder lokaler Pfad (Video auf D:).
    fremd_url = models.CharField(max_length=1000, blank=True)
    abgerufen_von = models.URLField(max_length=1000, blank=True, help_text="Adresse nach Weiterleitungen")
    gesichert_am = models.DateTimeField(null=True, blank=True)
    fehler = models.CharField(max_length=300, blank=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-erstellt_am", "-id"]
        verbose_name_plural = "Sicherungen"
        indexes = [models.Index(fields=["quelle", "art"])]


class BoardBeweis(models.Model):
    """Ein Beweisstück (eine Quelle) als eigene Karte auf der Wand."""

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="beweise")
    quelle = models.ForeignKey(Quelle, on_delete=models.CASCADE, related_name="auf_boards")
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)

    class Meta:
        unique_together = [("board", "quelle")]
        verbose_name_plural = "Beweisstücke auf Boards"


# ─── Beweisschicht: Schlüssel, signierte Ereignisse, Überstimmungen ─────────────


class Instanz(models.Model):
    """Genau eine Zeile: die Kennung dieser Installation (Arbeitsbereich der Ereigniskette)."""

    kennung = models.UUIDField(unique=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)


class SchluesselRolle(models.TextChoices):
    MENSCH = "mensch", "Mensch"
    GERAET = "geraet", "Gerät"
    AGENT = "agent", "Agent"


class Schluessel(models.Model):
    """Öffentlicher Ed25519-Schlüssel. Der private Schlüssel eines Menschen verlässt nie seinen Browser."""

    kid = models.CharField(max_length=200, unique=True)
    rolle = models.CharField(max_length=10, choices=SchluesselRolle.choices)
    nutzer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                               related_name="akte_schluessel")
    oeffentlich = models.CharField(max_length=64, help_text="32 Byte, base64url ohne Auffüllung")
    fingerabdruck = models.CharField(max_length=16)
    erstellt_am = models.DateTimeField(auto_now_add=True)
    widerrufen_am = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Schlüssel"

    def __str__(self):
        return self.kid


class Ereignis(models.Model):
    """Ein signiertes Ereignis der Kette (Format atlas-trace-v1). ``json`` ist genau das signierte Ereignis.

    ``salz`` und ``inhalt`` sind die Offenlegung zur Zusage in der Nutzlast; sie bleiben auf dem Server, bis das
    betroffene Objekt öffentlich wird.
    """

    position = models.PositiveIntegerField(unique=True)
    event_id = models.CharField(max_length=40, unique=True)
    event_hash = models.CharField(max_length=64, unique=True)
    typ = models.CharField(max_length=40)
    kid = models.CharField(max_length=200)
    json = models.TextField()
    salz = models.CharField(max_length=40, blank=True)
    inhalt = models.JSONField(null=True, blank=True)
    entitaet = models.ForeignKey(Entitaet, on_delete=models.SET_NULL, null=True, blank=True, related_name="ereignisse")
    verbindung = models.ForeignKey(Verbindung, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="ereignisse")
    sicherung = models.ForeignKey(Sicherung, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="ereignisse")
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position"]
        verbose_name_plural = "Ereignisse"


class Ueberstimmung(models.Model):
    """Ein Mensch überstimmt einen Befund der Prüfung, mit Begründung. Gilt, bis sich der Faden ändert."""

    verbindung = models.ForeignKey(Verbindung, on_delete=models.CASCADE, related_name="ueberstimmungen")
    code = models.CharField(max_length=60)
    begruendung = models.TextField()
    nutzer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    ereignis = models.ForeignKey(Ereignis, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("verbindung", "code")]
        verbose_name_plural = "Überstimmungen"
