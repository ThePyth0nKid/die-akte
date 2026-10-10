import re

from django.conf import settings
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers

from .models import (
    Beleg,
    Board,
    BoardBeweis,
    BoardKarte,
    Entitaet,
    Fahrt,
    Mappe,
    Quelle,
    Rahmen,
    Sicherung,
    SicherungStatus,
    Station,
    Verbindung,
    Zettel,
)
from .pruefung import pruefe_verbindung

_NUR_LESEN = ["erstellt_am", "geaendert_am", "erstellt_von"]


def _in_wurzel(datei: str, wurzeln: list[str]) -> bool:
    """Liegt ``datei`` in einem der Ordner? Windows-Pfade ohne Groß-/Kleinschreibung, POSIX-Pfade genau."""
    if re.match(r"^[A-Za-z]:[\\/]", datei):
        normal = datei.replace("/", "\\").lower()
        return any(normal.startswith(w.replace("/", "\\").rstrip("\\").lower() + "\\")
                   for w in wurzeln if re.match(r"^[A-Za-z]:[\\/]", w))
    return any(datei.startswith(w.rstrip("/") + "/") for w in wurzeln if w.startswith("/"))


def freier_slug(modell, text: str, ausser_pk=None) -> str:
    basis = slugify(text)[:200] or "eintrag"
    slug, n = basis, 2
    andere = modell.objects.exclude(pk=ausser_pk) if ausser_pk else modell.objects.all()
    while andere.filter(slug=slug).exists():
        slug, n = f"{basis}-{n}", n + 1
    return slug


def _slug_frei(modell, slug, instanz) -> None:
    """Der Slug-Wunsch des Nutzers: ein vergebener Slug ist ein 400, kein Serverfehler."""
    if not slug:
        return
    andere = modell.objects.filter(slug=slug)
    if instanz is not None:
        andere = andere.exclude(pk=instanz.pk)
    if andere.exists():
        raise serializers.ValidationError({"slug": "Diese Kennung ist schon vergeben."})


class EntitaetSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False, allow_blank=True)

    class Meta:
        model = Entitaet
        fields = [
            "id", "typ", "name", "slug", "kurzbeschreibung", "notiz_md", "bild_url", "bild_nachweis",
            "wikidata_qid", "tags", "oeffentliche_person", "status", *_NUR_LESEN,
        ]
        read_only_fields = _NUR_LESEN

    def validate_tags(self, wert):
        if not isinstance(wert, list) or not all(isinstance(t, str) for t in wert):
            raise serializers.ValidationError("Tags sind eine Liste von Wörtern.")
        return wert

    def validate(self, daten):
        # Der Slug bleibt nach dem Anlegen stabil, auch wenn sich der Name ändert.
        if not self.instance and not daten.get("slug"):
            daten["slug"] = freier_slug(Entitaet, daten.get("name", ""))
        elif "slug" in daten and not daten["slug"]:
            daten.pop("slug")
        else:
            _slug_frei(Entitaet, daten.get("slug"), self.instance)
        return daten


class EntitaetKurzSerializer(serializers.ModelSerializer):
    class Meta:
        model = Entitaet
        fields = ["id", "typ", "name", "slug", "kurzbeschreibung", "bild_url", "bild_nachweis", "oeffentliche_person", "status"]


class SicherungSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sicherung
        fields = ["id", "art", "status", "sha256", "bytes", "mime", "dateiname", "fremd_url",
                  "abgerufen_von", "gesichert_am", "fehler", "beleg"]
        read_only_fields = fields


def sicherungsstand(quelle) -> dict:
    """Je Art die jüngste Sicherung; ``vorschau`` ist die ID des besten Vorschaubilds."""
    je_art = {}
    for s in quelle.sicherungen.all():  # neueste zuerst (Meta.ordering)
        je_art.setdefault(s.art, s)
    vorschau = next(
        (je_art[a].id for a in ("vorschau", "screenshot") if a in je_art and je_art[a].status == SicherungStatus.FERTIG),
        None,
    )
    fundstellen, gesehen = [], set()
    for s in quelle.sicherungen.all():
        if s.art == "fundstelle" and s.status == SicherungStatus.FERTIG and s.beleg_id not in gesehen:
            gesehen.add(s.beleg_id)
            fundstellen.append({"id": s.id, "beleg": s.beleg_id, "zitat": s.beleg.zitat_woertlich if s.beleg_id else ""})
    return {
        "sicherungen": SicherungSerializer(list(je_art.values()), many=True).data,
        "vorschau": vorschau,
        "fundstellen": fundstellen,
    }


class QuelleSerializer(serializers.ModelSerializer):
    stand = serializers.SerializerMethodField()

    class Meta:
        model = Quelle
        fields = [
            "id", "url", "titel", "herausgeber", "veroeffentlicht_am", "abgerufen_am",
            "archiv_url", "datei_url", "guete", "notiz", "meta", "stand", *_NUR_LESEN,
        ]
        read_only_fields = [*_NUR_LESEN, "meta"]

    def get_stand(self, q):
        return sicherungsstand(q)


class BelegSerializer(serializers.ModelSerializer):
    quelle = serializers.PrimaryKeyRelatedField(queryset=Quelle.objects.all())
    quelle_detail = QuelleSerializer(source="quelle", read_only=True)

    class Meta:
        model = Beleg
        fields = ["id", "quelle", "quelle_detail", "zitat_woertlich", "fundstelle"]


def _fundstelle_anstossen(beleg_id: int) -> None:
    from django.conf import settings

    # PDF-Fundstellen brauchen keinen Browser (pdfium); ob eine Webseite fotografiert wird, entscheidet die Aufgabe.
    if getattr(settings, "AKTE_SICHERUNG_AKTIV", True):
        from .tasks import fundstelle_sichern

        transaction.on_commit(lambda: fundstelle_sichern.delay(beleg_id))


class VerbindungSerializer(serializers.ModelSerializer):
    belege = BelegSerializer(many=True, required=False)
    befunde = serializers.SerializerMethodField()

    class Meta:
        model = Verbindung
        fields = [
            "id", "von", "nach", "typ", "beschreibung", "start", "ende", "aktuell",
            "betrag", "waehrung", "aussageart", "konfidenz", "anhoerung_angefragt_am",
            "anhoerung_antwort", "anhoerung_antwort_am", "status", "belege", "befunde",
            *_NUR_LESEN,
        ]
        read_only_fields = _NUR_LESEN

    def get_befunde(self, v):
        return [{"code": b.code, "text": b.text, "schwere": b.schwere, "ueberstimmt": b.ueberstimmt}
                for b in pruefe_verbindung(v, self.context.get("board"))]

    def validate_konfidenz(self, wert):
        if wert not in (1, 2, 3):
            raise serializers.ValidationError("Konfidenz ist 1, 2 oder 3.")
        return wert

    def validate(self, daten):
        von = daten.get("von") or getattr(self.instance, "von", None)
        nach = daten.get("nach") or getattr(self.instance, "nach", None)
        if von and nach and von == nach:
            raise serializers.ValidationError("Ein Faden braucht zwei verschiedene Karten.")
        quellen = [b["quelle"].pk for b in daten.get("belege", [])]
        if len(quellen) != len(set(quellen)):
            raise serializers.ValidationError({"belege": "Jede Quelle nur einmal je Faden."})
        return daten

    def _belege_setzen(self, v, belege):
        v.belege.all().delete()
        for b in belege:
            neu = Beleg.objects.create(verbindung=v, **b)
            if neu.zitat_woertlich.strip():
                _fundstelle_anstossen(neu.id)

    @transaction.atomic
    def create(self, daten):
        belege = daten.pop("belege", [])
        v = super().create(daten)
        self._belege_setzen(v, belege)
        return v

    @transaction.atomic
    def update(self, v, daten):
        belege = daten.pop("belege", None)
        v = super().update(v, daten)
        if belege is not None:
            self._belege_setzen(v, belege)
        return v


class BoardSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False, allow_blank=True)

    class Meta:
        model = Board
        fields = ["id", "titel", "slug", "beschreibung", "look", "oeffentlich", "regeln", *_NUR_LESEN]
        read_only_fields = _NUR_LESEN

    def validate_regeln(self, wert):
        from .regeln import pruefe_board_regeln

        try:
            return pruefe_board_regeln(wert)
        except ValueError as fehler:
            raise serializers.ValidationError(str(fehler)) from None

    def validate(self, daten):
        if not self.instance and not daten.get("slug"):
            daten["slug"] = freier_slug(Board, daten.get("titel", ""))
        elif "slug" in daten and not daten["slug"]:
            daten.pop("slug")
        else:
            _slug_frei(Board, daten.get("slug"), self.instance)
        return daten


class KarteSerializer(serializers.ModelSerializer):
    entitaet_detail = EntitaetKurzSerializer(source="entitaet", read_only=True)

    class Meta:
        model = BoardKarte
        fields = ["id", "entitaet", "entitaet_detail", "x", "y", "farbe"]


class ZettelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Zettel
        fields = ["id", "art", "text", "x", "y"]


def farbe_pruefen(wert):
    """Rahmen und Mappen: nur #RRGGBB (kein CSS aus der Datenbank)."""
    if wert and not re.fullmatch(r"#[0-9a-fA-F]{6}", wert):
        raise serializers.ValidationError("Farbe als #RRGGBB, z. B. #C8102E.")
    return wert


class RahmenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rahmen
        fields = ["id", "titel", "x", "y", "breite", "hoehe", "farbe"]

    def validate_farbe(self, wert):
        # Die Wand macht aus einer Farbe ein Schild.
        return farbe_pruefen(wert)


class MappeSerializer(serializers.ModelSerializer):
    """Ändern nur Lage und Farbe; das Ziel steht fest (neu anlegen statt umhängen)."""

    ziel = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = Mappe
        fields = ["id", "ziel", "x", "y", "farbe"]

    def validate_farbe(self, wert):
        return farbe_pruefen(wert)


class StationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        fields = [
            "position", "x", "y", "zoom", "fokus", "stichwort", "dauer_ms", "beweis_quelle", "beweis_zitat",
            "text", "einblendung", "einspieler",
        ]
        # Die Reihenfolge der Liste ist die Position; sie wird beim Speichern neu vergeben.
        read_only_fields = ["position"]

    def validate_fokus(self, wert):
        if not isinstance(wert, list) or not all(isinstance(i, int) for i in wert):
            raise serializers.ValidationError("Fokus ist eine Liste von Karten-IDs.")
        return wert

    def validate_einspieler(self, wert):
        """Lokale Videodatei mit Ausschnitt und Quellenmarke; ohne Quelle kein Einspieler (Zitatrecht)."""
        if wert in (None, ""):
            return {}
        if not isinstance(wert, dict):
            raise serializers.ValidationError("Einspieler ist ein Objekt (datei, ab, bis, quelle).")
        if not wert:
            return {}
        fremd = set(wert) - {"datei", "ab", "bis", "quelle", "freeze_ms", "untertitel"}
        if fremd:
            raise serializers.ValidationError(f"Unbekannte Felder: {', '.join(sorted(fremd))}")
        datei = str(wert.get("datei", "")).strip()
        absolut = re.match(r"^[A-Za-z]:[\\/]", datei) or datei.startswith("/")
        if not absolut or not re.search(r"\.(mp4|mov|webm|mkv)$", datei, re.I) or ".." in datei:
            raise serializers.ValidationError("datei: absoluter Pfad zu mp4/mov/webm/mkv.")
        # Nur aus den Archiv-Ordnern (Renderer und Mischung prüfen den echten Pfad noch einmal auf dem Rechner).
        if not _in_wurzel(datei, settings.AKTE_EINSPIELER_WURZELN):
            raise serializers.ValidationError("datei: nur aus den freigegebenen Archiv-Ordnern.")
        try:
            ab = float(wert.get("ab", 0))
            bis = float(wert["bis"])
            freeze = int(wert.get("freeze_ms", 700))
        except (KeyError, TypeError, ValueError):
            raise serializers.ValidationError("ab/bis in Sekunden, bis ist Pflicht.") from None
        if ab < 0 or bis <= ab or bis - ab > 30 or not 0 <= freeze <= 3000:
            raise serializers.ValidationError("Ausschnitt 0 < bis − ab ≤ 30 s, freeze_ms 0–3000.")
        quelle = str(wert.get("quelle", "")).strip()
        if not quelle:
            raise serializers.ValidationError("quelle (Urheberangabe) ist Pflicht.")
        sauber = {"datei": datei, "ab": round(ab, 2), "bis": round(bis, 2), "quelle": quelle[:200], "freeze_ms": freeze}
        # Deutsche Übersetzung des O-Tons (wird unter dem Clip gezeigt).
        if str(wert.get("untertitel", "")).strip():
            sauber["untertitel"] = str(wert["untertitel"]).strip()[:400]
        return sauber

    def validate_einblendung(self, wert):
        """Nur die bekannten Felder, als kurze Texte — die Karte liegt groß im Bild."""
        if wert in (None, ""):
            return {}
        if not isinstance(wert, dict):
            raise serializers.ValidationError("Einblendung ist ein Objekt (gross, klein, quelle, voll).")
        grenzen = {"gross": 60, "klein": 160, "quelle": 160}
        fremd = set(wert) - set(grenzen) - {"voll"}
        if fremd:
            raise serializers.ValidationError(f"Unbekannte Felder: {', '.join(sorted(fremd))}")
        sauber = {k: str(wert[k])[:n] for k, n in grenzen.items() if str(wert.get(k, "")).strip()}
        if wert.get("voll"):
            sauber["voll"] = True
        return sauber


class FahrtSerializer(serializers.ModelSerializer):
    stationen = StationSerializer(many=True)

    class Meta:
        model = Fahrt
        fields = ["id", "titel", "stationen"]

    def _stationen_setzen(self, fahrt, stationen):
        fahrt.stationen.all().delete()
        for i, s in enumerate(stationen):
            s = {**s, "position": i}
            Station.objects.create(fahrt=fahrt, **s)

    @transaction.atomic
    def create(self, daten):
        stationen = daten.pop("stationen")
        fahrt = Fahrt.objects.create(**daten)
        self._stationen_setzen(fahrt, stationen)
        return fahrt

    @transaction.atomic
    def update(self, fahrt, daten):
        stationen = daten.pop("stationen", None)
        fahrt.titel = daten.get("titel", fahrt.titel)
        fahrt.save()
        if stationen is not None:
            self._stationen_setzen(fahrt, stationen)
        return fahrt


class BeweisSerializer(serializers.ModelSerializer):
    quelle_detail = QuelleSerializer(source="quelle", read_only=True)
    faeden = serializers.SerializerMethodField()

    class Meta:
        model = BoardBeweis
        fields = ["id", "quelle", "quelle_detail", "x", "y", "faeden"]

    def get_faeden(self, b):
        """Die Fäden, die dieses Beweisstück belegt — für die goldenen Linien zu den Karten."""
        return [[beleg.verbindung.von_id, beleg.verbindung.nach_id] for beleg in b.quelle.belege.all()]
