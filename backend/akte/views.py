"""Die Akte — API der Werkstatt und die öffentliche Wand.

Die Werkstatt (alles außer ``OeffentlicheWandView``) ist nur für die Redaktion.
Die öffentliche Wand ist doppelt verriegelt: ``settings.AKTE_OEFFENTLICH_AKTIV``
(bleibt aus, bis ein Medienanwalt das Regelwerk geprüft hat) und ``Board.oeffentlich``.
Was sie dann zeigt, filtert ``pruefung.py`` Faden für Faden.
"""

import hashlib
import math
from collections import defaultdict

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, AllowAny
from rest_framework.response import Response
from rest_framework.authentication import TokenAuthentication
from rest_framework.parsers import MultiPartParser
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from . import einstellungen, lesecache, menschenrecht, speicher
from .export import vault_zip
from .graph import finde_weg
from .kamera import bild_fuer, format_name, karten_rechteck
from .layout import RahmenBox, Teil, aufraeumen
from .mappen import Buendel, buendel_rechnen, kinder_aus, lage_rechnen, teilbaum, wuerde_zyklus
from .mappen import gesichter as mappen_gesichter
from .mappen import vorschau as mappen_vorschau
from .mappen import zaehler as mappen_zaehler
from .models import (
    Aussageart,
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
    Status,
    Verbindung,
    Zettel,
    ZettelArt,
)
from .permissions import (
    AkteOeffentlichThrottle,
    IstRedaktion,
    LesenMitgliedSonstRedaktion,
    MitgliedLesenThrottle,
    ist_redaktion,
    lese_boards,
    mitglieder_boards,
)
from .beweisschicht import freigaben_prefetch, veraendert_seit_freigabe
from .pruefung import darf_oeffentlich, faeden_qs, pruefe_verbindung, sperrende
from .regeln import uebersicht as regeln_uebersicht
from .serializers import (
    BeweisSerializer,
    BoardSerializer,
    EntitaetKurzSerializer,
    EntitaetSerializer,
    FahrtSerializer,
    KarteSerializer,
    MappeSerializer,
    QuelleSerializer,
    RahmenSerializer,
    SicherungSerializer,
    VerbindungSerializer,
    ZettelSerializer,
    farbe_pruefen,
)
from .sicherung import anhang_speichern, sicherung_anstossen
from .verlauf import protokolliere


_faeden_qs = faeden_qs


def nur_gepruefte() -> bool:
    """Lese-Ansicht für Mitglieder und Besucher: nur Freigegebenes, das die Prüfung besteht (Standard), oder jeder
    belegte Faden (``AKTE_LESEANSICHT=alles_belegte``, nur für geschlossene Runden)."""
    return getattr(settings, "AKTE_LESEANSICHT", "nur_gepruefte") != "alles_belegte"


class Redaktion:
    """Nur die Redaktion. Neben dem Login (JWT) auch ein persönlicher Token für Werkzeuge (CLI, MCP).

    Werkzeuge ändern kein veröffentlichtes Board (``menschenrecht.pruefe_board_werkzeug``); Ausnahmen setzen
    ``werkzeug_auf_veroeffentlichten = True`` (Fahrten und Anordnung, die Leser nicht als Inhalt sehen).
    """

    authentication_classes = [JWTAuthentication, TokenAuthentication]
    permission_classes = [IstRedaktion]
    werkzeug_auf_veroeffentlichten = False

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        slug = kwargs.get("slug")
        if slug and request.method not in SAFE_METHODS and not self.werkzeug_auf_veroeffentlichten:
            menschenrecht.pruefe_board_werkzeug(request, slug)


class MitVerlauf(Redaktion):
    """Schreibt jede Änderung in den Verlauf — in derselben Transaktion wie die Änderung.

    Ein ``IntegrityError`` (zwei Redakteure legen gleichzeitig denselben Slug an)
    wird zum 400 statt zum Serverfehler.
    """

    def perform_create(self, serializer):
        zusatz = menschenrecht.pruefe_anlegen(self.request, serializer.Meta.model, serializer.validated_data)
        try:
            with transaction.atomic():
                obj = serializer.save(erstellt_von=self.request.user, **zusatz)
                protokolliere(obj, "angelegt", self.request.user)
        except IntegrityError:
            raise ValidationError("Gleichzeitig angelegt oder schon vorhanden. Bitte neu laden.") from None

    def perform_update(self, serializer):
        menschenrecht.pruefe_aendern(self.request, serializer.instance, serializer.validated_data)
        try:
            with transaction.atomic():
                obj = serializer.save()
                for zurueck in menschenrecht.nach_aenderung(obj):
                    protokolliere(zurueck, "zurueck_auf_entwurf", self.request.user)
                protokolliere(obj, "geaendert", self.request.user)
        except IntegrityError:
            raise ValidationError("Konflikt beim Speichern. Bitte neu laden.") from None

    @transaction.atomic
    def perform_destroy(self, instance):
        menschenrecht.pruefe_loeschen(self.request, instance)
        protokolliere(instance, "geloescht", self.request.user)
        instance.delete()


# ─── Entitäten, Quellen, Fäden ──────────────────────────────────────────────


class EntitaetListeView(MitVerlauf, generics.ListCreateAPIView):
    serializer_class = EntitaetSerializer

    def get_queryset(self):
        qs = Entitaet.objects.all()
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(kurzbeschreibung__icontains=q) | Q(slug__icontains=q))
            # Exakter Name zuerst, dann Namensanfang, dann Name enthält, zuletzt nur Beschreibung.
            qs = qs.annotate(rang=Case(
                When(name__iexact=q, then=Value(0)),
                When(name__istartswith=q, then=Value(1)),
                When(name__icontains=q, then=Value(2)),
                default=Value(3), output_field=IntegerField(),
            )).order_by("rang", "name")
        typ = self.request.query_params.get("typ")
        if typ:
            qs = qs.filter(typ=typ)
        return qs[:200]


class EntitaetDetailView(MitVerlauf, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = EntitaetSerializer
    queryset = Entitaet.objects.all()

    def retrieve(self, request, *args, **kwargs):
        e = self.get_object()
        daten = self.get_serializer(e).data
        faeden = _faeden_qs().filter(Q(von=e) | Q(nach=e))
        daten["faeden"] = VerbindungSerializer(faeden, many=True).data
        daten["nachbarn"] = EntitaetKurzSerializer(
            Entitaet.objects.filter(Q(ausgehend__nach=e) | Q(eingehend__von=e)).distinct(), many=True
        ).data
        # Rückverweise wie in Obsidian: wer nennt [[Name]] in seiner Notiz?
        muster = f"[[{e.name}"
        daten["rueckverweise"] = EntitaetKurzSerializer(
            Entitaet.objects.filter(notiz_md__icontains=muster).exclude(pk=e.pk), many=True
        ).data
        # „Kommt vor in …“: jede Wand, auf der die Karte liegt.
        daten["boards"] = [
            {"slug": slug, "titel": titel}
            for slug, titel in BoardKarte.objects.filter(entitaet=e).values_list("board__slug", "board__titel")
        ]
        return Response(daten)


class QuelleListeView(MitVerlauf, generics.ListCreateAPIView):
    serializer_class = QuelleSerializer

    def perform_create(self, serializer):
        super().perform_create(serializer)
        sicherung_anstossen(serializer.instance)

    def get_queryset(self):
        qs = Quelle.objects.prefetch_related("sicherungen__beleg")
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(Q(titel__icontains=q) | Q(herausgeber__icontains=q) | Q(url__icontains=q))
        return qs[:200]


class QuelleDetailView(MitVerlauf, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = QuelleSerializer
    queryset = Quelle.objects.prefetch_related("sicherungen__beleg")

    def perform_update(self, serializer):
        alter_link = serializer.instance.url
        super().perform_update(serializer)
        if serializer.instance.url != alter_link:
            sicherung_anstossen(serializer.instance)

    def perform_destroy(self, instance):
        if instance.belege.exists():
            raise ValidationError("Diese Quelle belegt noch Fäden und kann nicht gelöscht werden.")
        super().perform_destroy(instance)


class SichernDrossel(UserRateThrottle):
    rate = "120/hour"


class QuelleSichernView(Redaktion, APIView):
    """„Neu sichern“: Original (und archive.org, wenn eingeschaltet) noch einmal holen. Kehrt sofort zurück (202);
    die Sicherung läuft im Hintergrund, ihr Ergebnis steht danach unter ``stand`` der Quelle."""

    throttle_classes = [SichernDrossel]

    def post(self, request, pk):
        quelle = get_object_or_404(Quelle, pk=pk)
        if not quelle.url:
            return Response({"detail": "Diese Quelle hat keinen Link."}, status=400)
        if not speicher.eingerichtet():
            return Response({"detail": "Kein Beweis-Speicher eingerichtet."}, status=503)
        sicherung_anstossen(quelle)
        return Response({"angestossen": True}, status=202)


class PruefenDrossel(UserRateThrottle):
    rate = "300/hour"


class BelegPruefenView(Redaktion, APIView):
    """Steht das Zitat dieses Belegs wörtlich in seiner Quelle? Synchron, höchstens 30 s (``zitatpruefung.py``).

    Antwort ``{"ergebnis": "gefunden" | "nicht_gefunden" | "nicht_pruefbar", "grund": str, "fundstelle": {…} | null}``.
    Ändert weder Status noch Beleg, darum dürfen auch Werkzeuge (Token) prüfen; hat die Quelle noch gar keine eigene
    Kopie, legt sie das geladene Original als erste Sicherung ab. Die Anfrage nimmt keine Adresse an: Geladen wird
    höchstens das Original von der gespeicherten Adresse der Quelle, über den sicheren Abruf.
    """

    throttle_classes = [PruefenDrossel]

    def post(self, request, pk):
        from .zitatpruefung import pruefen

        beleg = get_object_or_404(Beleg.objects.select_related("quelle"), pk=pk)
        return Response(pruefen(beleg))


class EinstellungenView(Redaktion, APIView):
    """Einstellungen für die ganze Akte: ``{"archiv_org": bool}`` (Quellen zusätzlich bei archive.org sichern).

    Lesen darf die Redaktion samt ihren Werkzeugen; ändern nur ein Mensch in der Oberfläche
    (``menschenrecht.pruefe_einstellungen``): archive.org macht jede Quell-URL öffentlich.
    """

    def get(self, request):
        return Response(einstellungen.als_dict())

    def patch(self, request):
        menschenrecht.pruefe_einstellungen(request)
        daten = request.data if isinstance(request.data, dict) else None
        if daten is None:
            raise ValidationError({"detail": "Erwartet wird ein Objekt, z. B. {\"archiv_org\": false}."})
        unbekannt = sorted(set(daten) - {"archiv_org"})
        if unbekannt:
            raise ValidationError({k: ["Unbekannte Einstellung."] for k in unbekannt})
        if "archiv_org" in daten:
            if not isinstance(daten["archiv_org"], bool):
                raise ValidationError({"archiv_org": ["Bitte true oder false angeben."]})
            with transaction.atomic():
                einst = einstellungen.archiv_org_setzen(daten["archiv_org"], request.user)
                protokolliere(einst, "geaendert", request.user)
        return Response(einstellungen.als_dict())


class AnhangDrossel(UserRateThrottle):
    rate = "60/hour"


class _AnhangBasis(Redaktion, APIView):
    parser_classes = [MultiPartParser]
    throttle_classes = [AnhangDrossel]

    def _speichern(self, quelle, datei):
        from .sicherung import ANHANG_MAX

        # Vor dem Lesen: sonst läge eine riesige Datei erst ganz im Speicher.
        if datei.size is None or datei.size > ANHANG_MAX:
            raise ValidationError({"datei": "Höchstens 15 MB je Anhang."})
        try:
            anhang_speichern(quelle, datei.read(), datei.name or "")
        except ValueError as fehler:
            raise ValidationError({"datei": str(fehler)}) from None
        except speicher.SpeicherFehlt as fehler:
            raise ValidationError({"datei": str(fehler)}) from None


class AnhangView(_AnhangBasis):
    """Eigene Datei (PDF, Bild) an eine vorhandene Quelle hängen."""

    def post(self, request, pk):
        quelle = get_object_or_404(Quelle, pk=pk)
        datei = request.FILES.get("datei")
        if not datei:
            return Response({"datei": "Datei fehlt."}, status=400)
        with transaction.atomic():
            self._speichern(quelle, datei)
            protokolliere(quelle, "anhang", request.user)
        return Response(QuelleSerializer(Quelle.objects.prefetch_related("sicherungen__beleg").get(pk=pk)).data, status=201)


class QuelleAusDateiView(_AnhangBasis):
    """Neue Quelle aus einer Datei (z. B. Handy-Screenshot); optional gleich als Beweisstück auf ein Board."""

    def post(self, request):
        datei = request.FILES.get("datei")
        if not datei:
            return Response({"datei": "Datei fehlt."}, status=400)
        titel = (request.data.get("titel") or datei.name or "Anhang").strip()[:300]
        with transaction.atomic():
            quelle = Quelle.objects.create(
                titel=titel, herausgeber=(request.data.get("herausgeber") or "")[:200],
                abgerufen_am=timezone.localdate(), erstellt_von=request.user,
            )
            self._speichern(quelle, datei)
            protokolliere(quelle, "angelegt", request.user)
            slug = request.data.get("board")
            if slug:
                menschenrecht.pruefe_board_werkzeug(request, slug)
                board = _board(slug)
                BoardBeweis.objects.get_or_create(
                    board=board, quelle=quelle,
                    defaults={"x": _zahl(request.data.get("x")), "y": _zahl(request.data.get("y"))},
                )
        return Response(QuelleSerializer(Quelle.objects.prefetch_related("sicherungen__beleg").get(pk=quelle.pk)).data, status=201)


def _zahl(wert) -> float:
    """Koordinate aus der Anfrage: NaN/Unendlich machen die Wand zu ungültigem JSON, also 0; sonst begrenzt."""
    try:
        zahl = float(wert)
    except (TypeError, ValueError):
        return 0.0
    return max(-1e7, min(1e7, zahl)) if math.isfinite(zahl) else 0.0


#: So werden Kopien ausgeliefert. HTML nie als HTML: fremde Skripte auf unserer Domain wären
#: ein Einfallstor; die Redaktion bekommt den Quelltext als Text.
_AUSLIEFERN_ALS = {
    "application/pdf": ("application/pdf", "inline"),
    "image/png": ("image/png", "inline"),
    "image/jpeg": ("image/jpeg", "inline"),
    "image/gif": ("image/gif", "inline"),
    "image/webp": ("image/webp", "inline"),
    "text/html": ("text/plain; charset=utf-8", "attachment"),
}


class SicherungDateiView(Redaktion, APIView):
    def get(self, request, pk):
        s = get_object_or_404(Sicherung, pk=pk, status=SicherungStatus.FERTIG)
        if not s.schluessel:
            raise Http404
        try:
            daten = speicher.lesen(s.schluessel)
        except (speicher.SpeicherFehlt, FileNotFoundError):
            raise Http404 from None
        except speicher.KopieBeschaedigt as fehler:
            return Response({"detail": str(fehler)}, status=status.HTTP_409_CONFLICT)
        mime, art = _AUSLIEFERN_ALS.get(s.mime, ("application/octet-stream", "attachment"))
        endung = s.schluessel.rsplit(".", 1)[-1]
        antwort = HttpResponse(daten, content_type=mime)
        antwort["Content-Disposition"] = f'{art}; filename="beweis-{s.sha256[:12]}.{endung}"'
        antwort["X-Content-Type-Options"] = "nosniff"
        antwort["Content-Security-Policy"] = "sandbox; default-src 'none'"
        antwort["Cache-Control"] = "private, max-age=3600"
        return antwort


class VideoLokalView(Redaktion, APIView):
    """Meldung des Video-Helfers: das Video liegt im lokalen Archiv auf dem eigenen Rechner."""

    throttle_classes = [SichernDrossel]

    def post(self, request, pk):
        from .sicherung import video_lokal_melden

        quelle = get_object_or_404(Quelle, pk=pk)
        d = request.data
        sha = str(d.get("sha256", ""))
        if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha) or not d.get("pfad"):
            return Response({"detail": "pfad und sha256 (64 Hex-Zeichen) angeben."}, status=400)
        s = video_lokal_melden(quelle, str(d["pfad"]), sha, _zahl(d.get("bytes")), str(d.get("dateiname", "")),
                               str(d.get("zeitmarke", "")))
        return Response(SicherungSerializer(s).data, status=201)


class SicherungListeView(Redaktion, APIView):
    def get(self, request, pk):
        quelle = get_object_or_404(Quelle, pk=pk)
        return Response(SicherungSerializer(quelle.sicherungen.all(), many=True).data)


class VerbindungListeView(MitVerlauf, generics.ListCreateAPIView):
    serializer_class = VerbindungSerializer

    def get_queryset(self):
        qs = _faeden_qs()
        e = self.request.query_params.get("entitaet")
        if e:
            qs = qs.filter(Q(von_id=e) | Q(nach_id=e))
        return qs


class VerbindungDetailView(MitVerlauf, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = VerbindungSerializer
    queryset = _faeden_qs()


# ─── Boards ─────────────────────────────────────────────────────────────────


def _board(slug) -> Board:
    return get_object_or_404(Board, slug=slug)


def wand_daten(board: Board) -> dict:
    """Alles, was die Werkstatt zum Zeichnen braucht, in einem Abruf."""
    karten = list(board.karten.select_related("entitaet"))
    auf_der_wand = {k.entitaet_id for k in karten}
    ausgeblendet = set(board.ausgeblendete_verbindungen.values_list("id", flat=True))
    faeden = _faeden_qs().filter(von_id__in=auf_der_wand, nach_id__in=auf_der_wand)
    faeden_daten = VerbindungSerializer(faeden, many=True).data
    for f in faeden_daten:
        f["ausgeblendet"] = f["id"] in ausgeblendet
    return {
        "board": BoardSerializer(board).data,
        "karten": KarteSerializer(karten, many=True).data,
        "faeden": faeden_daten,
        **_mappen_werkstatt(board, karten),
        "zettel": ZettelSerializer(board.zettel.all(), many=True).data,
        "rahmen": RahmenSerializer(board.rahmen.all(), many=True).data,
        "fahrten": FahrtSerializer(board.fahrten.prefetch_related("stationen"), many=True).data,
        "beweise": BeweisSerializer(
            board.beweise.select_related("quelle").prefetch_related(
                "quelle__sicherungen__beleg", "quelle__belege__verbindung"
            ),
            many=True,
        ).data,
    }


# ─── Mappen: Boards in Boards ────────────────────────────────────────────────
# Rechnung in ``mappen.py``; hier nur Laden und Ausgeben. Etwa zehn Abfragen je Wand, egal wie viele
# Mappen. Mitglieder bekommen dieselben Schlüssel, aber nur aus freigeschalteten Boards, nur belegte
# Fäden mit Beleg und Kennungen, die nur in dieser Antwort gelten (sonst verraten fortlaufende IDs,
# was es auf gesperrten Boards gibt).


def _mappen_kinder() -> dict[int, list[int]]:
    return kinder_aus(Mappe.objects.values_list("board_id", "ziel_id"))


def _mappen_stand(board: Board, direkt: dict[int, int], erlaubt: set[int] | None = None,
                  nur_belegt: bool = False, hier_ausgeblendete: bool = False, streng: bool = False) -> dict:
    """Lädt, was die Mappen dieser Wand brauchen, und rechnet Lage, Bündel, Zähler, Gesichter, Miniatur.

    ``streng`` (Lese-Ansicht ``nur_gepruefte``): nur freigegebene Karten und nur Fäden, die die Prüfung dieser Wand
    bestehen, zählen mit, auch in Zählern, Gesichtern und Miniaturen.
    """
    mappen = [m for m in board.mappen.select_related("ziel") if erlaubt is None or m.ziel_id in erlaubt]
    if not mappen:
        return {"mappen": []}
    kinder = _mappen_kinder()
    unter: set[int] = set()
    for m in mappen:
        unter |= teilbaum(m.ziel_id, kinder, erlaubt)
    karten_je_board: dict[int, set[int]] = defaultdict(set)
    lagen: dict[int, list[tuple[float, float]]] = defaultdict(list)
    karten_qs = BoardKarte.objects.filter(board_id__in=unter)
    if streng:
        karten_qs = karten_qs.filter(entitaet__status=Status.FREIGEGEBEN)
        veraendert = {e.pk for e in Entitaet.objects.filter(
            pk__in=karten_qs.values("entitaet_id")).prefetch_related(freigaben_prefetch())
            if veraendert_seit_freigabe(e, "karte")}
        karten_qs = karten_qs.exclude(entitaet_id__in=veraendert)
    for b, e, x, y in karten_qs.values_list("board_id", "entitaet_id", "x", "y"):
        karten_je_board[b].add(e)
        lagen[b].append((x, y))
    lage = lage_rechnen(direkt, [(m.id, m.ziel_id) for m in mappen], kinder, karten_je_board, erlaubt)
    alle = lage.auf_der_wand()

    # Was auf dieser Wand oder in einem Board darunter ausgeblendet ist, zählt nirgends mit. Die Werkstatt
    # bekommt die hier ausgeblendeten Bündel-Fäden getrennt zurück, damit sie sich wieder einblenden lassen.
    hier = set(board.ausgeblendete_verbindungen.values_list("id", flat=True))
    darunter = set(Board.ausgeblendete_verbindungen.through.objects.filter(board_id__in=unter)
                   .values_list("verbindung_id", flat=True))
    versteckt = hier | darunter
    qs = Verbindung.objects.filter(von_id__in=alle, nach_id__in=alle)
    if nur_belegt:
        qs = qs.filter(aussageart=Aussageart.BELEGT, belege__isnull=False).distinct()
    if streng:
        kandidaten = faeden_qs().filter(id__in=qs.filter(status=Status.FREIGEGEBEN).values("id"))
        qs = Verbindung.objects.filter(id__in=[v.id for v in kandidaten if darf_oeffentlich(v, board)])
    alle_zeilen = [
        (fid, von, nach, typ, art, betrag is not None)
        for fid, von, nach, typ, art, betrag in qs.values_list("id", "von_id", "nach_id", "typ", "aussageart", "betrag")
    ]
    zeilen = [z for z in alle_zeilen if z[0] not in versteckt]
    nur_hier = [z for z in alle_zeilen if z[0] in hier and z[0] not in darunter] if hier_ausgeblendete else []
    quellen_je: dict[int, set[int]] = defaultdict(set)
    for fid, qid in Beleg.objects.filter(verbindung_id__in=[z[0] for z in zeilen]).values_list("verbindung_id", "quelle_id"):
        quellen_je[fid].add(qid)

    im_inhalt = set().union(*lage.inhalt.values())
    mit_bild = {
        i for i, bild, typ, oeffentlich in Entitaet.objects.filter(id__in=im_inhalt)
        .values_list("id", "bild_url", "typ", "oeffentliche_person")
        if bild and not (typ == "person" and not oeffentlich)
    }
    rahmen_je: dict[int, list] = defaultdict(list)
    for b, x, y, rb, rh, farbe in Rahmen.objects.filter(board_id__in=[m.ziel_id for m in mappen]).values_list(
        "board_id", "x", "y", "breite", "hoehe", "farbe"
    ):
        rahmen_je[b].append((x, y, rb, rh, farbe))
    return {
        "mappen": mappen,
        "lage": lage,
        "buendel": buendel_rechnen(lage, zeilen),
        "ausgeblendet": buendel_rechnen(lage, nur_hier),
        "zaehler": mappen_zaehler(lage, zeilen, quellen_je),
        "gesichter": mappen_gesichter(lage, zeilen, mit_bild),
        "vorschau": {m.id: mappen_vorschau(lagen[m.ziel_id], rahmen_je[m.ziel_id]) for m in mappen},
    }


def _auch_in(board: Board, entitaeten, erlaubt: set[int] | None = None) -> dict[int, list[dict]]:
    """Je Entität die anderen Boards, auf denen sie liegt (Portale „auch in …“)."""
    qs = BoardKarte.objects.filter(entitaet_id__in=entitaeten).exclude(board=board)
    if erlaubt is not None:
        qs = qs.filter(board_id__in=erlaubt)
    je: dict[int, list[dict]] = defaultdict(list)
    for e, slug, titel in qs.order_by("board__titel").values_list("entitaet_id", "board__slug", "board__titel"):
        je[e].append({"slug": slug, "titel": titel})
    return je


def _eltern(board: Board, erlaubt: set[int] | None = None) -> list[dict]:
    qs = Mappe.objects.filter(ziel=board)
    if erlaubt is not None:
        qs = qs.filter(board_id__in=erlaubt)
    return [{"slug": slug, "titel": titel} for slug, titel in qs.values_list("board__slug", "board__titel")]


def _je_typ(bu) -> list:
    return [[t, n] for t, n in sorted(bu.je_typ.items(), key=lambda p: (-p[1], p[0]))[:3]]


def _mappen_werkstatt(board: Board, karten: list[BoardKarte]) -> dict:
    """Die Mappen-Schlüssel für die Werkstatt (Redaktion)."""
    direkt = {k.entitaet_id: k.id for k in karten}
    auch_in = _auch_in(board, list(direkt))
    grundgeruest = {"mappen": [], "buendel": [], "buendel_faeden": [], "ausser_haus": [],
                    "auch_in": auch_in, "eltern": _eltern(board), "gelenke": []}
    st = _mappen_stand(board, direkt, hier_ausgeblendete=True)
    if not st["mappen"]:
        return grundgeruest
    lage = st["lage"]
    # Auf dieser Wand ausgeblendete Fäden hängen am selben Bündel, getrennt geführt (zum Wiedereinblenden).
    versteckt_je = {(bu.a, bu.b): bu.faeden for bu in st["ausgeblendet"]}
    for bu in st["buendel"]:
        bu.versteckt = versteckt_je.pop((bu.a, bu.b), [])
    for (a, b), ids in versteckt_je.items():
        leer = Buendel(a=a, b=b, versteckt=ids)
        st["buendel"].append(leer)
    faden_ids = sorted({f for bu in st["buendel"] for f in (*bu.faeden, *bu.versteckt)})
    versteckte_ids = {f for bu in st["buendel"] for f in bu.versteckt}
    buendel_faeden = list(_faeden_qs().filter(id__in=faden_ids))
    ausser = {e for v in buendel_faeden for e in (v.von_id, v.nach_id) if e not in direkt}
    gesicht_ids = {e for ids in st["gesichter"].values() for e in ids}
    kurz = {e.id: e for e in Entitaet.objects.filter(id__in=ausser | gesicht_ids | set(lage.gelenke))}
    return {
        **grundgeruest,
        "mappen": [
            {
                "id": m.id, "ziel": m.ziel.slug, "titel": m.ziel.titel, "beschreibung": m.ziel.beschreibung[:600],
                "x": m.x, "y": m.y, "farbe": m.farbe, "zaehler": st["zaehler"][m.id],
                "gesichter": EntitaetKurzSerializer([kurz[e] for e in st["gesichter"][m.id]], many=True).data,
                "vorschau": st["vorschau"][m.id],
            }
            for m in st["mappen"]
        ],
        "buendel": [
            {"id": f"b-{bu.a[0]}{bu.a[1]}-{bu.b[0]}{bu.b[1]}", "von": f"{bu.a[0]}-{bu.a[1]}",
             "nach": f"{bu.b[0]}-{bu.b[1]}", "faeden": bu.faeden, "je_art": dict(bu.je_art),
             "je_typ": _je_typ(bu), "mit_betrag": bu.mit_betrag, "ausgeblendet": bu.versteckt}
            for bu in st["buendel"]
        ],
        "buendel_faeden": [
            {**f, "ausgeblendet": f["id"] in versteckte_ids}
            for f in VerbindungSerializer(buendel_faeden, many=True).data
        ],
        "ausser_haus": [
            {**EntitaetKurzSerializer(kurz[e]).data, "mappe": f"m-{lage.spezifischste(lage.in_mappen[e])}"}
            for e in sorted(ausser) if e in kurz and lage.in_mappen.get(e)
        ],
        "gelenke": EntitaetKurzSerializer([kurz[e] for e in lage.gelenke if e in kurz], many=True).data,
    }


def _mappen_mitglieder(board: Board, karten: list[BoardKarte], nr: dict[int, int], faeden_bisher: int,
                       qnr: dict[int, int], lesbar: set[str]) -> dict:
    """Die Mappen-Schlüssel für Mitglieder: nur freigeschaltete Boards, nur Belegtes, eigene Kennungen.

    Kennungen: Karten behalten ihre Nummer aus ``wand_fuer_mitglieder``; Entitäten aus Mappen bekommen
    Nummern dahinter, Mappen 1..m, Fäden zählen nach den gewöhnlichen weiter. Keine interne ID verlässt
    die Antwort; verdeckte Personen tragen nur Initialen und nie ein Portal.
    """
    erlaubt = set(Board.objects.filter(slug__in=lesbar).values_list("id", flat=True))
    direkt = {k.entitaet_id: k.id for k in karten}
    karte_zu_entitaet = {k.id: k.entitaet_id for k in karten}
    verdeckt = {k.entitaet_id for k in karten if _verdeckt(k.entitaet)}
    auch_in_roh = _auch_in(board, [e for e in direkt if e not in verdeckt], erlaubt)
    grundgeruest = {"mappen": [], "buendel": [], "buendel_faeden": [], "ausser_haus": [],
                    "auch_in": {str(nr[e]): boards for e, boards in auch_in_roh.items()},
                    "eltern": _eltern(board, erlaubt), "gelenke": []}
    st = _mappen_stand(board, direkt, erlaubt=erlaubt, nur_belegt=True, streng=nur_gepruefte())
    if not st["mappen"]:
        return grundgeruest
    lage = st["lage"]
    mnr = {m.id: i for i, m in enumerate(st["mappen"], start=1)}
    faden_ids = sorted({f for bu in st["buendel"] for f in bu.faeden})
    faeden = list(Verbindung.objects.filter(id__in=faden_ids).order_by("id").prefetch_related("belege__quelle"))
    ausser = sorted({e for v in faeden for e in (v.von_id, v.nach_id) if e not in direkt})
    gesicht_ids = {e for ids in st["gesichter"].values() for e in ids}
    ents = {e.id: e for e in Entitaet.objects.filter(id__in=set(ausser) | gesicht_ids)}
    alle_nr = dict(nr)
    for i, e in enumerate(ausser, start=len(karten) + 1):
        alle_nr[e] = i
    fnr = {v.id: i for i, v in enumerate(faeden, start=faeden_bisher + 1)}

    def knoten(ende: tuple[str, int]) -> str:
        art, wert = ende
        return f"k-{nr[karte_zu_entitaet[wert]]}" if art == "k" else f"m-{mnr[wert]}"

    def gesicht(e: Entitaet) -> dict:
        if _verdeckt(e):
            return {"typ": e.typ, "name": e.initialen(), "bild_url": "", "bild_nachweis": ""}
        return {"typ": e.typ, "name": e.name, "bild_url": e.bild_url, "bild_nachweis": e.bild_nachweis}

    def aussen(e: Entitaet) -> dict:
        mappe = f"m-{mnr[lage.spezifischste(lage.in_mappen[e.id])]}"
        return {**_mitglied_karte(BoardKarte(entitaet=e), alle_nr[e.id])["entitaet_detail"], "mappe": mappe}

    return {
        **grundgeruest,
        "mappen": [
            {
                "id": mnr[m.id], "ziel": m.ziel.slug, "titel": m.ziel.titel, "beschreibung": m.ziel.beschreibung[:600],
                "x": m.x, "y": m.y, "farbe": m.farbe, "zaehler": st["zaehler"][m.id],
                "gesichter": [gesicht(ents[e]) for e in st["gesichter"][m.id] if e in ents],
                "vorschau": st["vorschau"][m.id],
            }
            for m in st["mappen"]
        ],
        "buendel": [
            {"id": f"b{i}", "von": knoten(bu.a), "nach": knoten(bu.b), "faeden": [fnr[f] for f in bu.faeden],
             "je_art": dict(bu.je_art), "je_typ": _je_typ(bu), "mit_betrag": bu.mit_betrag}
            for i, bu in enumerate(st["buendel"], start=1)
        ],
        "buendel_faeden": [_mitglied_faden(v, alle_nr, fnr[v.id], qnr) for v in faeden],
        "ausser_haus": [aussen(ents[e]) for e in ausser if e in ents and lage.in_mappen.get(e)],
    }


def _alle_auf_der_wand(board: Board) -> set[int]:
    """Direkte Karten und alles in den Mappen darunter (für Ausblenden eines Bündel-Fadens)."""
    direkt = dict(board.karten.values_list("entitaet_id", "id"))
    mappen = list(board.mappen.values_list("id", "ziel_id"))
    if not mappen:
        return set(direkt)
    kinder = _mappen_kinder()
    unter = set().union(*(teilbaum(z, kinder) for _, z in mappen))
    karten_je_board: dict[int, set[int]] = defaultdict(set)
    for b, e in BoardKarte.objects.filter(board_id__in=unter).values_list("board_id", "entitaet_id"):
        karten_je_board[b].add(e)
    return lage_rechnen(direkt, mappen, kinder, karten_je_board).auf_der_wand()


# ─── Lese-Ansicht für Mitglieder ─────────────────────────────────────────────
# Ausdrückliche Feldliste statt der Werkstatt-Serializer: keine Notizen, Zettel, Fahrten,
# Beweisstücke, Befunde, Verfasser oder lokalen Pfade, und nur Fäden zwischen Karten
# dieses Boards (sonst wären Karten anderer Boards über geteilte Personen erreichbar).
# Entitäten, Fäden und Belege tragen Kennungen, die nur in dieser Antwort gelten: die internen
# IDs sind über alle Boards gleich und machten eine verdeckte Person wiedererkennbar.


def _verdeckt(e: Entitaet) -> bool:
    """Nur Initialen: Privatpersonen und Personen, deren Kennzeichnung als öffentliche Person noch kein Mensch
    unterschrieben hat (ein Werkzeug darf eine Person nicht selbst öffentlich machen)."""
    return e.ist_privatperson or (e.typ == "person" and e.status != Status.FREIGEGEBEN)


def _mitglied_karte(k: BoardKarte, nr: int) -> dict:
    e = k.entitaet
    verdeckt = _verdeckt(e)
    return {
        "id": nr, "entitaet": nr, "x": k.x, "y": k.y, "farbe": k.farbe,
        "entitaet_detail": {
            "id": nr, "typ": e.typ, "name": e.initialen() if verdeckt else e.name,
            "slug": "" if verdeckt else e.slug,
            "kurzbeschreibung": "" if verdeckt else e.kurzbeschreibung,
            "bild_url": "" if verdeckt else e.bild_url,
            "bild_nachweis": "" if verdeckt else e.bild_nachweis,
            "oeffentliche_person": e.oeffentliche_person and not verdeckt, "status": e.status,
        },
    }


def _mitglied_quelle(q: Quelle, qnr: dict[int, int]) -> dict:
    return {
        "id": qnr.setdefault(q.id, len(qnr) + 1), "url": q.url, "titel": q.titel, "herausgeber": q.herausgeber,
        "veroeffentlicht_am": q.veroeffentlicht_am, "abgerufen_am": q.abgerufen_am,
        "archiv_url": q.archiv_url, "guete": q.guete, "stand": None,
    }


def _mitglied_faden(v: Verbindung, nr: dict[int, int], fnr: int, qnr: dict[int, int]) -> dict:
    """Quellen tragen je Antwort eigene Nummern (``qnr``): die internen IDs verbänden sonst Fäden über Boards hinweg."""
    return {
        "id": fnr, "von": nr[v.von_id], "nach": nr[v.nach_id], "typ": v.typ, "beschreibung": v.beschreibung,
        "start": v.start, "ende": v.ende, "aktuell": v.aktuell, "betrag": v.betrag, "waehrung": v.waehrung,
        "aussageart": v.aussageart, "status": v.status, "befunde": [], "ausgeblendet": False,
        "belege": [
            {"id": fnr * 1000 + i, "quelle": qnr.setdefault(b.quelle_id, len(qnr) + 1), "zitat_woertlich": b.zitat_woertlich,
             "fundstelle": b.fundstelle, "quelle_detail": _mitglied_quelle(b.quelle, qnr)}
            for i, b in enumerate(v.belege.all(), start=1)
        ],
    }


def wand_fuer_mitglieder(board: Board, lesbar: set[str] | None = None) -> dict:
    """Die Wand zum Lesen: Karten, Rahmen, belegte Fäden mit Quelle und die Meinungs-Zettel der Redaktion.

    Standard (``AKTE_LESEANSICHT=nur_gepruefte``): nur Karten, die ein Mensch freigegeben hat und die seitdem
    unverändert sind, und nur Fäden, die die Prüfung dieser Wand bestehen (freigegeben, unverändert, kein
    sperrender Befund). Meinungs-Zettel schreiben nur Menschen (``menschenrecht.pruefe_zettel``).

    ``lesbar``: Slugs, deren Mappen, Portale und Brotkrumen sichtbar sind (Standard: Mitglieder-Boards).
    Frage- und Notiz-Zettel bleiben intern: Sie sind Redaktionsnotizen und nennen Privatpersonen,
    deren Karten nur Initialen zeigen.
    """
    if lesbar is None:
        lesbar = mitglieder_boards()
    streng = nur_gepruefte()
    karten = list(board.karten.select_related("entitaet").prefetch_related(freigaben_prefetch("entitaet__ereignisse"))
                  .order_by("id"))
    if streng:
        karten = [k for k in karten if k.entitaet.status == Status.FREIGEGEBEN
                  and not veraendert_seit_freigabe(k.entitaet, "karte")]
    auf_der_wand = {k.entitaet_id for k in karten}
    nr = {k.entitaet_id: i for i, k in enumerate(karten, start=1)}
    ausgeblendet = set(board.ausgeblendete_verbindungen.values_list("id", flat=True))
    faeden = (
        faeden_qs().filter(von_id__in=auf_der_wand, nach_id__in=auf_der_wand, aussageart=Aussageart.BELEGT)
        .exclude(id__in=ausgeblendet)
        .order_by("id")
    )
    if streng:
        faeden = faeden.filter(status=Status.FREIGEGEBEN)
    sichtbar = (v for v in faeden if v.belege.all() and (not streng or darf_oeffentlich(v, board)))
    qnr: dict[int, int] = {}
    faeden_daten = [_mitglied_faden(v, nr, i, qnr) for i, v in enumerate(sichtbar, start=1)]
    return {
        "board": {"id": board.id, "titel": board.titel, "slug": board.slug, "beschreibung": board.beschreibung,
                  "look": board.look, "darf_bearbeiten": False},
        "karten": [_mitglied_karte(k, nr[k.entitaet_id]) for k in karten],
        "faeden": faeden_daten,
        **_mappen_mitglieder(board, karten, nr, len(faeden_daten), qnr, lesbar),
        "zettel": [
            {"id": i, "art": z.art, "text": z.text, "x": z.x, "y": z.y}
            for i, z in enumerate(board.zettel.filter(art=ZettelArt.MEINUNG).order_by("id"), start=1)
        ],
        "rahmen": RahmenSerializer(board.rahmen.all(), many=True).data,
        "fahrten": [],
        "beweise": [],
        "darf_bearbeiten": False,
    }


class _BoardLesen:
    """Board-Liste und Wand: lesen darf jedes eingeloggte Konto die freigeschalteten Boards,
    alles andere bleibt Redaktion."""

    permission_classes = [LesenMitgliedSonstRedaktion]
    throttle_classes = [MitgliedLesenThrottle, AkteOeffentlichThrottle]

    def get_queryset(self):
        if ist_redaktion(self.request.user):
            return Board.objects.all()
        return Board.objects.filter(slug__in=lese_boards(self.request.user))


class BoardListeView(_BoardLesen, MitVerlauf, generics.ListCreateAPIView):
    serializer_class = BoardSerializer

    def list(self, request, *args, **kwargs):
        darf = ist_redaktion(request.user)
        boards = self.get_queryset()
        daten = BoardSerializer(boards, many=True).data
        if not darf:
            daten = [{k: b[k] for k in ("id", "titel", "slug", "beschreibung", "look")} for b in daten]
        # Eltern nur aus derselben (für Mitglieder gefilterten) Liste: der Baum der Akte.
        eltern: dict[int, list[str]] = defaultdict(list)
        for ziel, slug in Mappe.objects.filter(ziel__in=boards, board__in=boards).values_list("ziel_id", "board__slug"):
            eltern[ziel].append(slug)
        for b in daten:
            b["darf_bearbeiten"] = darf
            b["eltern"] = eltern.get(b["id"], [])
        return Response(daten)


class BoardDetailView(_BoardLesen, MitVerlauf, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = BoardSerializer
    lookup_field = "slug"

    def retrieve(self, request, *args, **kwargs):
        board = self.get_object()
        if not ist_redaktion(request.user):
            lesbar = lese_boards(request.user)
            if request.user.is_authenticated:
                return Response(wand_fuer_mitglieder(board, lesbar))
            # Ohne Konto sieht jeder dasselbe: fünf Minuten im Cache, jede Änderung macht ihn ungültig (lesecache.py).
            return Response(lesecache.holen(board.slug, lesbar, lambda: wand_fuer_mitglieder(board, lesbar)))
        daten = wand_daten(board)
        daten["board"]["darf_bearbeiten"] = True
        daten["darf_bearbeiten"] = True
        return Response(daten)


def _redaktion_gemerkt(request) -> bool:
    """``ist_redaktion`` einmal je Anfrage (Drossel und View fragen beide)."""
    wert = getattr(request, "_akte_redaktion", None)
    if wert is None:
        wert = ist_redaktion(request.user)
        request._akte_redaktion = wert
    return wert


class StandDrossel(UserRateThrottle):
    """Deckel für das Abfragen des Stands (alle paar Sekunden je offenem Tab); die Redaktion bleibt ungebremst.
    Eigener Zähler, damit das Abfragen nicht den Lese-Deckel der Mitglieder aufbraucht."""

    scope = "akte_stand"

    def get_rate(self):
        return self.THROTTLE_RATES.get(self.scope, "120/min")

    def allow_request(self, request, view):
        if _redaktion_gemerkt(request):
            return True
        return super().allow_request(request, view)


class BoardStandView(_BoardLesen, APIView):
    """Live-Aktualisierung: ``{"stand": "<undurchsichtig>"}``, ändert sich, sobald sich an der Wand etwas ändert.

    Gleiche Leserechte wie die Wand. Die Redaktion bekommt den Stand der Werkstatt: Board und eine Version, die jede
    Änderung an Karten, Platzierungen, Fäden, Belegen, Zetteln, Rahmen, Mappen, Fahrten, Beweisstücken, Freigaben
    und Sicherungen neu setzt (``lesecache``, Signale in ``apps.py``) – billig: das Board und ein Cache-Wert, nichts
    wird geschrieben. Die Version gilt für die ganze Akte; eine Änderung an einer anderen Wand lädt diese also
    unnötig, aber unschädlich neu.

    Mitglieder und Besucher bekommen einen Fingerabdruck genau dessen, was sie sehen (die Lese-Ansicht, einmal je
    Cache-Version gerechnet und gemerkt, ``lesecache.fingerabdruck``): Er verrät nicht, wann die Redaktion an
    Entwürfen arbeitet.
    """

    throttle_classes = [StandDrossel]

    def get(self, request, slug):
        if _redaktion_gemerkt(request):
            board = get_object_or_404(Board, slug=slug)
            roh = f"werkstatt|{board.pk}|{board.geaendert_am.isoformat()}|{lesecache.werkstatt_version()}"
        else:
            lesbar = lese_boards(request.user)
            board = get_object_or_404(Board, slug=slug, slug__in=lesbar)
            roh = "lesen|" + lesecache.fingerabdruck(board.slug, lesbar, lambda: wand_fuer_mitglieder(board, lesbar))
        return Response({"stand": hashlib.sha256(roh.encode("utf-8")).hexdigest()[:32]})


class KarteListeView(Redaktion, APIView):
    def post(self, request, slug):
        board = _board(slug)
        s = KarteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        karte, _ = BoardKarte.objects.update_or_create(
            board=board,
            entitaet=s.validated_data["entitaet"],
            defaults={k: v for k, v in s.validated_data.items() if k != "entitaet"},
        )
        return Response(KarteSerializer(karte).data, status=status.HTTP_201_CREATED)


class _BoardTeilView(Redaktion, generics.RetrieveUpdateDestroyAPIView):
    """Karte, Zettel, Rahmen oder Fahrt — immer nur innerhalb des genannten Boards."""

    modell = None

    def get_queryset(self):
        return self.modell.objects.filter(board__slug=self.kwargs["slug"])


class KarteDetailView(_BoardTeilView):
    modell = BoardKarte
    serializer_class = KarteSerializer


class ZettelDetailView(_BoardTeilView):
    modell = Zettel
    serializer_class = ZettelSerializer

    def perform_update(self, serializer):
        menschenrecht.pruefe_zettel(self.request, serializer.instance.art, serializer.validated_data.get("art", ""))
        serializer.save()

    def perform_destroy(self, instance):
        menschenrecht.pruefe_zettel(self.request, instance.art)
        instance.delete()


class RahmenDetailView(_BoardTeilView):
    modell = Rahmen
    serializer_class = RahmenSerializer


class FahrtDetailView(_BoardTeilView):
    modell = Fahrt
    serializer_class = FahrtSerializer
    werkzeug_auf_veroeffentlichten = True


class MappeDetailView(MitVerlauf, _BoardTeilView):
    modell = Mappe
    serializer_class = MappeSerializer


class MappeAnlegenView(Redaktion, APIView):
    """Ein anderes Board als Mappe auf diese Wand legen: ``{"ziel": "<slug>", "x": 0, "y": 0, "farbe": ""}``."""

    def post(self, request, slug):
        daten = request.data if isinstance(request.data, dict) else {}
        board = _board(slug)
        ziel = get_object_or_404(Board, slug=str(daten.get("ziel", "")))
        farbe = farbe_pruefen(str(daten.get("farbe") or ""))
        try:
            with transaction.atomic():
                # Beide Wände sperren (Postgres): zwei gegenläufige Anfragen A→B und B→A bilden sonst einen Kreis.
                list(Board.objects.select_for_update().filter(pk__in=[board.pk, ziel.pk]))
                if wuerde_zyklus(board.id, ziel.id, _mappen_kinder()):
                    return Response({"detail": "Das ergäbe einen Kreis: diese Wand steckt schon in der Mappe."}, status=400)
                mappe = Mappe.objects.create(board=board, ziel=ziel, x=_zahl(daten.get("x")), y=_zahl(daten.get("y")),
                                             farbe=farbe)
                protokolliere(mappe, "angelegt", request.user)
        except IntegrityError:
            return Response({"detail": "Diese Mappe liegt schon auf der Wand."}, status=400)
        return Response(MappeSerializer(mappe).data, status=status.HTTP_201_CREATED)


class _BoardTeilAnlegenView(Redaktion, generics.CreateAPIView):
    def perform_create(self, serializer):
        serializer.save(board=_board(self.kwargs["slug"]))


class BeweisAnlegenView(Redaktion, APIView):
    def post(self, request, slug):
        board = _board(slug)
        quelle = get_object_or_404(Quelle, pk=request.data.get("quelle"))
        beweis, _ = BoardBeweis.objects.get_or_create(
            board=board, quelle=quelle,
            defaults={"x": _zahl(request.data.get("x")), "y": _zahl(request.data.get("y"))},
        )
        return Response({"id": beweis.id}, status=status.HTTP_201_CREATED)


class BeweisDetailView(_BoardTeilView):
    modell = BoardBeweis
    serializer_class = BeweisSerializer


class ZettelAnlegenView(_BoardTeilAnlegenView):
    serializer_class = ZettelSerializer

    def perform_create(self, serializer):
        menschenrecht.pruefe_zettel(self.request, serializer.validated_data.get("art", ZettelArt.NOTIZ))
        super().perform_create(serializer)


class RahmenAnlegenView(_BoardTeilAnlegenView):
    serializer_class = RahmenSerializer


class FahrtAnlegenView(_BoardTeilAnlegenView):
    serializer_class = FahrtSerializer
    werkzeug_auf_veroeffentlichten = True


class PositionenView(Redaktion, APIView):
    """Nach dem Ziehen: viele Positionen auf einmal speichern."""

    werkzeug_auf_veroeffentlichten = True

    MODELLE = {"karte": BoardKarte, "zettel": Zettel, "rahmen": Rahmen, "beweis": BoardBeweis, "mappe": Mappe}

    @transaction.atomic
    def post(self, request, slug):
        board = _board(slug)
        eintraege = request.data if isinstance(request.data, list) else []
        for e in eintraege[:1000]:
            modell = self.MODELLE.get(e.get("art"))
            try:
                felder = {"x": float(e["x"]), "y": float(e["y"])}
                if modell is Rahmen:
                    for k in ("breite", "hoehe"):
                        if k in e:
                            felder[k] = max(80.0, float(e[k]))
                pk = int(e["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(v) for v in felder.values()):
                continue
            felder = {k: max(-1e7, min(1e7, v)) for k, v in felder.items()}
            if modell:
                modell.objects.filter(board=board, pk=pk).update(**felder)
        # .update() löst kein Signal aus: Lese-Cache und Stand der Wand selbst erneuern (Leser sehen die Lage).
        lesecache.veraltet()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FadenAusblendenView(Redaktion, APIView):
    def post(self, request, slug, pk):
        board = _board(slug)
        # Auch Fäden in Bündeln lassen sich auf dieser Wand ausblenden.
        ids = _alle_auf_der_wand(board)
        faden = get_object_or_404(Verbindung.objects.filter(von_id__in=ids, nach_id__in=ids), pk=pk)
        if board.ausgeblendete_verbindungen.filter(pk=pk).exists():
            board.ausgeblendete_verbindungen.remove(faden)
            return Response({"ausgeblendet": False})
        board.ausgeblendete_verbindungen.add(faden)
        return Response({"ausgeblendet": True})


class LesevorschauView(Redaktion, APIView):
    """Was Besucher ohne Konto sähen, wenn dieses Board öffentlich wäre. Die Oberfläche zeigt das vor dem
    Veröffentlichen, mit allen Freitexten (Titel, Beschreibung, Rahmen, Meinungs-Zettel, Mappen), damit ein Mensch
    nichts mitveröffentlicht, das ein Werkzeug geschrieben hat und er nie gesehen hat."""

    def get(self, request, slug):
        board = _board(slug)
        lesbar = set(Board.objects.filter(oeffentlich=True).values_list("slug", flat=True)) | {board.slug}
        return Response(wand_fuer_mitglieder(board, lesbar))


class PruefungView(Redaktion, APIView):
    """Was würde von diesem Board öffentlich erscheinen — und was nicht, warum?"""

    def get(self, request, slug):
        board = _board(slug)
        ids = board.karten.values_list("entitaet_id", flat=True)
        ergebnis = []
        for v in _faeden_qs().filter(von_id__in=ids, nach_id__in=ids):
            befunde = pruefe_verbindung(v, board)
            ergebnis.append({"id": v.id, "titel": str(v), "ok": not sperrende(befunde),
                             "befunde": [{"code": b.code, "text": b.text, "schwere": b.schwere,
                                          "ueberstimmt": b.ueberstimmt} for b in befunde]})
        return Response({"faeden": ergebnis, "alle_ok": all(f["ok"] for f in ergebnis),
                         "regeln": regeln_uebersicht(board)})


class AufraeumenView(Redaktion, APIView):
    """Ordnet die ganze Wand neu, ohne Überlappung (siehe ``layout.py``)."""

    werkzeug_auf_veroeffentlichten = True

    @transaction.atomic
    def post(self, request, slug):
        board = _board(slug)
        karten = list(board.karten.all())
        zettel = list(board.zettel.all())
        rahmen = list(board.rahmen.all())
        teile = [Teil("karte", k.id, k.x, k.y, k.entitaet_id) for k in karten]
        teile += [Teil("zettel", z.id, z.x, z.y) for z in zettel]
        beweise = list(board.beweise.all())
        teile += [Teil("beweis", b.id, b.x, b.y) for b in beweise]
        mappen = list(board.mappen.all())
        teile += [Teil("mappe", m.id, m.x, m.y) for m in mappen]
        ids = [k.entitaet_id for k in karten]
        kanten = list(
            Verbindung.objects.filter(von_id__in=ids, nach_id__in=ids)
            .exclude(id__in=board.ausgeblendete_verbindungen.values("id"))
            .values_list("von_id", "nach_id")
        )
        positionen, neue_rahmen = aufraeumen(
            teile, [RahmenBox(r.id, r.x, r.y, r.breite, r.hoehe) for r in rahmen], kanten
        )
        for k in karten:
            k.x, k.y = positionen[("karte", k.id)]
        for z in zettel:
            z.x, z.y = positionen[("zettel", z.id)]
        for b in beweise:
            b.x, b.y = positionen[("beweis", b.id)]
        BoardBeweis.objects.bulk_update(beweise, ["x", "y"])
        for m in mappen:
            m.x, m.y = positionen[("mappe", m.id)]
        Mappe.objects.bulk_update(mappen, ["x", "y"])
        for r in rahmen:
            if r.id in neue_rahmen:
                r.x, r.y, r.breite, r.hoehe = neue_rahmen[r.id]
        BoardKarte.objects.bulk_update(karten, ["x", "y"])
        Zettel.objects.bulk_update(zettel, ["x", "y"])
        Rahmen.objects.bulk_update(rahmen, ["x", "y", "breite", "hoehe"])
        lesecache.veraltet()  # bulk_update löst kein Signal aus
        return Response(wand_daten(board))


class FahrtAusBeschreibungView(Redaktion, APIView):
    """Eine Fahrt aus Kartennamen bauen. Gleicher Titel ersetzt die alte Fahrt.

    ``{"titel": "K3", "format": "16:9", "stationen": [{"fokus": ["Max Mustermann", "Nordlicht"],
    "stichwort": "…", "dauer_ms": 1400, "zoom": null}]}`` — leerer Fokus zeigt die ganze Wand.
    """

    werkzeug_auf_veroeffentlichten = True

    @transaction.atomic
    def post(self, request, slug):
        board = _board(slug)
        daten = request.data if isinstance(request.data, dict) else {}
        titel = str(daten.get("titel", "")).strip()[:120]
        stationen = daten.get("stationen")
        format_ = format_name(str(daten.get("format", "16:9")))
        if not titel or not isinstance(stationen, list) or not stationen or not format_:
            return Response({"detail": "titel, format (16:9|9:16|1:1|oben) und stationen angeben."}, status=400)

        karten = list(board.karten.select_related("entitaet"))
        def rechteck(k):
            return karten_rechteck(k.x, k.y, k.entitaet.typ == "person" or bool(k.entitaet.bild_url))

        alle = [rechteck(k) for k in karten]
        nach_name = {}
        for k in karten:
            nach_name[k.entitaet.name.lower()] = k
            nach_name[k.entitaet.slug.lower()] = k

        fertig, unbekannt = [], []
        for i, st in enumerate(stationen[:200]):
            if not isinstance(st, dict):
                return Response({"detail": f"Station {i + 1} ist kein Objekt."}, status=400)
            namen = [str(n) for n in st.get("fokus", []) if str(n).strip()]
            treffer = [nach_name.get(n.strip().lower()) for n in namen]
            unbekannt += [n for n, t in zip(namen, treffer) if t is None]
            fokus_karten = [t for t in treffer if t is not None]
            rechtecke = [rechteck(k) for k in fokus_karten] or alle
            if not rechtecke:
                return Response({"detail": "Das Board hat keine Karten."}, status=400)
            try:
                zoom = float(st["zoom"]) if st.get("zoom") not in (None, "") else None
                dauer = max(0, min(int(st.get("dauer_ms", 1400)), 10000))
            except (TypeError, ValueError):
                return Response({"detail": f"Station {i + 1}: zoom und dauer_ms müssen Zahlen sein."}, status=400)
            bild = bild_fuer(rechtecke, format_, zoom)
            beweis = st.get("beweis")
            beweis_id = None
            if beweis not in (None, ""):
                treffer_q = (
                    Quelle.objects.filter(pk=beweis).first() if str(beweis).isdigit()
                    else Quelle.objects.filter(titel__icontains=str(beweis)).first()
                )
                if not treffer_q:
                    unbekannt.append(f"Beweis: {beweis}")
                else:
                    beweis_id = treffer_q.id
            fertig.append({
                "x": bild.x, "y": bild.y, "zoom": bild.zoom,
                "fokus": [k.entitaet_id for k in fokus_karten],
                "stichwort": str(st.get("stichwort", ""))[:200],
                "dauer_ms": dauer,
                "beweis_quelle": beweis_id,
                "beweis_zitat": str(st.get("zitat", ""))[:2000],
                "text": str(st.get("text", ""))[:4000],
                "einblendung": st.get("einblendung") or {},
                "einspieler": st.get("einspieler") or {},
            })
        if unbekannt:
            return Response({"detail": "Karten nicht auf diesem Board.", "unbekannt": sorted(set(unbekannt))}, status=400)

        board.fahrten.filter(titel=titel).delete()
        s = FahrtSerializer(data={"titel": titel, "stationen": fertig})
        s.is_valid(raise_exception=True)
        fahrt = s.save(board=board)
        return Response(FahrtSerializer(fahrt).data, status=status.HTTP_201_CREATED)


# ─── Graph und Export ───────────────────────────────────────────────────────


class WegView(Redaktion, APIView):
    def get(self, request):
        try:
            von = int(request.query_params["von"])
            nach = int(request.query_params["nach"])
            tiefe = min(int(request.query_params.get("tiefe", 4)), 6)
        except (KeyError, ValueError):
            return Response({"detail": "von und nach als IDs angeben."}, status=400)
        arten = [Aussageart.BELEGT] if request.query_params.get("nur_belegt") == "1" else None
        weg = finde_weg(von, nach, max_tiefe=tiefe, aussagearten=arten)
        if weg is None:
            return Response({"gefunden": False, "entitaeten": [], "faeden": []})
        knoten, faeden = weg
        return Response({"gefunden": True, "entitaeten": knoten, "faeden": faeden})


class ObsidianExportView(Redaktion, APIView):
    def get(self, request):
        antwort = HttpResponse(vault_zip(), content_type="application/zip")
        antwort["Content-Disposition"] = 'attachment; filename="akte-vault.zip"'
        return antwort


# ─── Öffentliche Wand (Stufe 2) ─────────────────────────────────────────────

def _oeffentliche_karte(e: Entitaet, kennung: str) -> dict:
    if e.ist_privatperson:
        return {"id": kennung, "typ": e.typ, "name": e.initialen(), "kurzbeschreibung": "",
                "bild_url": "", "bild_nachweis": "", "verdeckt": True}
    # Der Nachweis gehört zum Bild: Urheber und Lizenz, bei KI-Bildern die Kennzeichnung.
    return {"id": kennung, "typ": e.typ, "name": e.name, "kurzbeschreibung": e.kurzbeschreibung,
            "bild_url": e.bild_url, "bild_nachweis": e.bild_nachweis if e.bild_url else "", "verdeckt": False}


def _oeffentlicher_faden(v: Verbindung, kennung: dict[int, str], nr: int) -> dict:
    daten = {
        "id": f"f{nr}", "von": kennung[v.von_id], "nach": kennung[v.nach_id], "typ": v.typ,
        "beschreibung": v.beschreibung, "start": v.start, "ende": v.ende, "aktuell": v.aktuell,
        "betrag": v.betrag, "waehrung": v.waehrung, "aussageart": v.aussageart,
        "quellen": [
            {"titel": b.quelle.titel, "herausgeber": b.quelle.herausgeber, "url": b.quelle.url,
             "archiv_url": b.quelle.archiv_url, "guete": b.quelle.guete,
             "zitat_woertlich": b.zitat_woertlich, "fundstelle": b.fundstelle}
            for b in v.belege.all()
        ],
    }
    if v.aussageart == Aussageart.VERDACHT:
        # Die Stellungnahme gehört sichtbar zum Verdacht.
        daten["stellungnahme"] = {
            "angefragt_am": v.anhoerung_angefragt_am,
            "antwort": v.anhoerung_antwort or "Keine Antwort erhalten.",
            "antwort_am": v.anhoerung_antwort_am,
        }
    return daten


class OeffentlicheWandView(APIView):
    """Lese-Ansicht ohne Konto. Zettel und Notizen bleiben intern: sie tragen keine Belege."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, slug):
        if not getattr(settings, "AKTE_OEFFENTLICH_AKTIV", False):
            raise Http404
        board = get_object_or_404(Board, slug=slug, oeffentlich=True)
        karten = [k for k in board.karten.select_related("entitaet").prefetch_related(
            freigaben_prefetch("entitaet__ereignisse")).filter(entitaet__status=Status.FREIGEGEBEN)
            if not veraendert_seit_freigabe(k.entitaet, "karte")]
        ids = {k.entitaet_id for k in karten}
        ausgeblendet = set(board.ausgeblendete_verbindungen.values_list("id", flat=True))
        faeden = [
            v for v in _faeden_qs().filter(von_id__in=ids, nach_id__in=ids).exclude(id__in=ausgeblendet)
            if darf_oeffentlich(v, board)
        ]
        # Kennungen gelten nur innerhalb dieser Antwort. Die internen IDs sind über alle
        # Boards gleich; öffentlich würden sie eine verdeckte Person wiedererkennbar machen.
        kennung = {k.entitaet_id: f"k{i}" for i, k in enumerate(karten, start=1)}
        return Response({
            "board": {"titel": board.titel, "slug": board.slug, "beschreibung": board.beschreibung,
                      "look": board.look},
            "karten": [{**_oeffentliche_karte(k.entitaet, kennung[k.entitaet_id]), "x": k.x, "y": k.y}
                       for k in karten],
            "faeden": [_oeffentlicher_faden(v, kennung, i) for i, v in enumerate(faeden, start=1)],
            "rahmen": RahmenSerializer(board.rahmen.all(), many=True).data,
        })
