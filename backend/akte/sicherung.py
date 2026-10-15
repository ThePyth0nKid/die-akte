"""Beweissicherung — jede Quelle wird kopiert, geprüft und auf Wunsch bei archive.org hinterlegt.

``quelle_sichern`` (im Hintergrund, siehe ``hintergrund.py`` und ``tasks.py``; keine Anfrage wartet darauf) macht
drei Dinge, jedes für sich fehlertolerant, damit ein gescheitertes archive.org nicht die eigene Kopie verhindert:

1. **Original**: Datei oder Seite laden (``abruf.py``), Art an den ersten Bytes erkennen,
   Prüfsumme bilden, privat ablegen (``speicher.py``). Bei Webseiten Titel, Herausgeber
   und Vorschaubild lesen.
2. **Vorschaubild**: das og:image der Seite, oder das Original selbst, wenn es ein Bild ist.
3. **archive.org** (nur wenn die Redaktion es eingeschaltet hat, ``einstellungen.py``): Save Page Now; die
   Schnappschuss-Adresse landet in ``Quelle.archiv_url`` (das erfüllt die Prüfregel „Archivkopie“).

Anhänge (eigene Dateien, Handy-Screenshots) gehen über ``anhang_speichern`` denselben Weg.
"""

import hashlib
import html
import logging
import re
import time
from datetime import timedelta
from urllib.parse import parse_qsl, urlsplit

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import hintergrund, speicher
from .abruf import ARTEN, BILDER, AbrufFehler, abrufen, erkenne, pruefe_url
from .einstellungen import archiv_org_aktiv
from .models import Quelle, Sicherung, SicherungArt, SicherungStatus

logger = logging.getLogger(__name__)

ANHANG_ERLAUBT = {"pdf", "png", "jpeg", "gif", "webp"}
ANHANG_MAX = 15 * 1024 * 1024
VORSCHAU_MAX = 10 * 1024 * 1024
ARCHIVE_ORG = "https://web.archive.org/save/"
#: Harte Gesamtfristen im Hintergrund (Sekunden): Original, Vorschaubild, archive.org (Auftrag samt Statusabfragen).
ORIGINAL_FRIST = 120.0
VORSCHAU_FRIST = 30.0
ARCHIV_FRIST = 180.0


def sicherung_anstossen(quelle: Quelle) -> None:
    """Nach dem Speichern der Quelle im Hintergrund sichern (nur mit Link). Kehrt sofort zurück."""
    if not quelle.url or not getattr(settings, "AKTE_SICHERUNG_AKTIV", True):
        return
    from .tasks import quelle_sichern

    quelle_id = quelle.id
    transaction.on_commit(lambda: hintergrund.starten(quelle_sichern, quelle_id))


def _juengste_gleiche(quelle: Quelle, art: str, sha: str, beleg=None) -> Sicherung | None:
    """Die jüngste Sicherung dieser Art (und dieses Belegs), wenn sie fertig ist und dieselbe Prüfsumme hat.

    Dann entsteht keine neue Zeile: „Neu sichern“ einer unveränderten Seite ändert nichts an der Akte, keine neue
    Zeile, kein neues Ereignis in der Kette."""
    juengste = (quelle.sicherungen.filter(art=art, beleg=beleg).order_by("-erstellt_am", "-id")
                .only("id", "status", "sha256").first())
    if juengste is not None and juengste.status == SicherungStatus.FERTIG and juengste.sha256 == sha:
        return Sicherung.objects.get(pk=juengste.pk)
    return None


def _ablegen(quelle: Quelle, art: str, daten: bytes, *, dateiname="", abgerufen_von="", beleg=None) -> Sicherung:
    erkannt = erkenne(daten)
    mime, endung = ARTEN[erkannt]
    sha = hashlib.sha256(daten).hexdigest()
    schl = speicher.schluessel(sha, endung)
    speicher.ablegen(schl, daten, mime)
    gleich = _juengste_gleiche(quelle, art, sha, beleg)
    if gleich is not None:
        return gleich
    return Sicherung.objects.create(
        quelle=quelle, beleg=beleg, art=art, status=SicherungStatus.FERTIG, schluessel=schl, sha256=sha,
        bytes=len(daten), mime=mime, dateiname=dateiname[:200], abgerufen_von=abgerufen_von[:1000],
        gesichert_am=timezone.now(),
    )


def _fehler(quelle: Quelle, art: str, text: str, *, beleg=None) -> Sicherung:
    return Sicherung.objects.create(quelle=quelle, beleg=beleg, art=art, status=SicherungStatus.FEHLER,
                                    fehler=text[:300])


# ─── Metadaten aus HTML ─────────────────────────────────────────────────────

_META = re.compile(r"<meta\s[^>]*>", re.I)
_ATTR = re.compile(r'([a-zA-Z:_-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')')
_TITEL = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def lies_meta(seite: str) -> dict:
    """og:title, og:site_name, og:description, og:image und <title> — ohne HTML-Parser-Abhängigkeit."""
    werte = {}
    for tag in _META.findall(seite[:300_000]):
        attr = {m.group(1).lower(): (m.group(3) if m.group(3) is not None else m.group(4)) for m in _ATTR.finditer(tag)}
        schl = attr.get("property") or attr.get("name")
        if schl and "content" in attr:
            schl = schl.lower()
            if schl in ("og:title", "og:site_name", "og:description", "og:image", "description", "twitter:image"):
                werte.setdefault(schl, html.unescape(attr["content"]).strip()[:500])
    titel = _TITEL.search(seite[:300_000])
    if titel:
        werte["title"] = html.unescape(re.sub(r"\s+", " ", titel.group(1))).strip()[:300]
    return {
        "titel": werte.get("og:title") or werte.get("title", ""),
        "herausgeber": werte.get("og:site_name", ""),
        "beschreibung": werte.get("og:description") or werte.get("description", ""),
        "bild": werte.get("og:image") or werte.get("twitter:image", ""),
    }


# ─── Die drei Schritte ──────────────────────────────────────────────────────

def original_sichern(quelle: Quelle) -> Sicherung:
    try:
        abruf = abrufen(quelle.url, frist=time.monotonic() + ORIGINAL_FRIST)
        s = _ablegen(quelle, SicherungArt.ORIGINAL, abruf.daten, abgerufen_von=abruf.url)
    except (AbrufFehler, speicher.SpeicherFehlt) as fehler:
        return _fehler(quelle, SicherungArt.ORIGINAL, str(fehler))

    art = erkenne(abruf.daten)
    _browser_anstossen(quelle, art)
    if art == "html":
        meta = lies_meta(abruf.daten.decode("utf-8", errors="replace"))
        quelle.meta = meta
        felder = ["meta"]
        if not quelle.herausgeber and meta["herausgeber"]:
            quelle.herausgeber = meta["herausgeber"][:200]
            felder.append("herausgeber")
        quelle.save(update_fields=felder)
        if meta["bild"]:
            vorschau_sichern(quelle, requests.compat.urljoin(abruf.url, meta["bild"]))
    elif art in BILDER:
        _als_vorschau(quelle, s)
    return s


def _als_vorschau(quelle: Quelle, s: Sicherung) -> None:
    """Ein Bild (Original oder Anhang) ist zugleich das Vorschaubild; nicht doppelt, wenn es schon eins ist."""
    if _juengste_gleiche(quelle, SicherungArt.VORSCHAU, s.sha256) is None:
        Sicherung.objects.create(
            quelle=quelle, art=SicherungArt.VORSCHAU, status=SicherungStatus.FERTIG, schluessel=s.schluessel,
            sha256=s.sha256, bytes=s.bytes, mime=s.mime, gesichert_am=s.gesichert_am,
        )


def vorschau_sichern(quelle: Quelle, bild_url: str) -> None:
    try:
        abruf = abrufen(bild_url, max_bytes=VORSCHAU_MAX, frist=time.monotonic() + VORSCHAU_FRIST)
        if erkenne(abruf.daten) not in BILDER:
            raise AbrufFehler("Vorschau ist kein Bild.")
        _ablegen(quelle, SicherungArt.VORSCHAU, abruf.daten, abgerufen_von=abruf.url)
    except (AbrufFehler, speicher.SpeicherFehlt) as fehler:
        logger.info("Akte: keine Vorschau für Quelle %s: %s", quelle.id, fehler)


ARCHIV_KOPF = {"User-Agent": f"{settings.AKTE_ABRUF_KENNUNG} (Beweissicherung)"}


def _schnappschuss_anlegen(url: str) -> tuple[str, str, bool]:
    """Save Page Now. Liefert (Schnappschuss-Adresse, Fehlertext, vorübergehend?).

    Mit Schlüssel (``AKTE_ARCHIVE_ORG_SCHLUESSEL`` = ``zugang:geheim`` von archive.org/account/s3.php)
    über die SPN2-API mit Statusabfrage — deutlich zuverlässiger. Ohne Schlüssel der anonyme Weg,
    den archive.org oft mit 429/5xx drosselt.
    """
    schluessel = getattr(settings, "AKTE_ARCHIVE_ORG_SCHLUESSEL", "")
    try:
        if schluessel:
            kopf = {**ARCHIV_KOPF, "Accept": "application/json", "Authorization": f"LOW {schluessel}"}
            job = requests.post("https://web.archive.org/save", data={"url": url, "skip_first_archive": "1"},
                                headers=kopf, timeout=(10, 60))
            if job.status_code >= 400 or "job_id" not in job.text:
                return "", f"archive.org antwortet mit {job.status_code}.", job.status_code in (429, 500, 502, 503, 504)
            job_id = job.json()["job_id"]
            ende = time.monotonic() + ARCHIV_FRIST
            for _ in range(20):
                if time.monotonic() + 4 > ende:
                    break
                time.sleep(4)
                rest = max(1.0, ende - time.monotonic())
                st = requests.get(f"https://web.archive.org/save/status/{job_id}", headers=kopf,
                                  timeout=(min(10, rest), min(30, rest))).json()
                if st.get("status") == "success":
                    return f"https://web.archive.org/web/{st['timestamp']}/{st.get('original_url', url)}", "", False
                if st.get("status") == "error":
                    return "", f"archive.org: {st.get('message', 'Fehler')[:200]}", True
            return "", "archive.org braucht zu lange.", True
        antwort = requests.get(ARCHIVE_ORG + url, timeout=(10, 120), allow_redirects=True, headers=ARCHIV_KOPF)
    except requests.RequestException as fehler:
        return "", f"archive.org nicht erreichbar: {type(fehler).__name__}", True
    ziel = antwort.url if "/web/" in antwort.url else antwort.headers.get("Content-Location", "")
    if ziel.startswith("/web/"):
        ziel = "https://web.archive.org" + ziel
    if antwort.status_code >= 400 or "/web/" not in ziel:
        return "", f"archive.org antwortet mit {antwort.status_code}.", antwort.status_code in (429, 500, 502, 503, 504)
    return ziel, "", False


def _vorhandener_schnappschuss(url: str) -> str:
    """Der jüngste Schnappschuss, den archive.org schon hat (Availability-API)."""
    try:
        daten = requests.get("https://archive.org/wayback/available", params={"url": url},
                             headers=ARCHIV_KOPF, timeout=(10, 30)).json()
    except (requests.RequestException, ValueError):
        return ""
    naechster = (daten.get("archived_snapshots") or {}).get("closest") or {}
    return naechster.get("url", "").replace("http://web.archive.org", "https://web.archive.org") if naechster.get("available") else ""


def _zugangs_parameter(name: str) -> bool:
    """Sieht der Query-Parameter nach Zugang aus (signierter Link, Sitzung, Schlüssel)? Dann nie an archive.org."""
    n = name.lower()
    if any(t in n for t in ("token", "signature", "secret", "passw", "session", "credential", "x-amz-", "ticket")):
        return True
    return n in {"key", "sig", "auth", "otp", "expires"} or n.endswith(("apikey", "_key", "-key", "_sig")) \
        or n.startswith("auth")


#: Frist für die Namensauflösung vor archive.org (ohne Frist hielte ein hängender DNS den archiv-Arbeiter fest).
ARCHIV_PRUEF_FRIST = 15.0
#: Meldungen von ``pruefe_url``, die vorübergehend sein können (DNS, Zeit): kein Dauer-Ausschluss vom Nachholen.
_VORUEBERGEHEND = ("Adresse nicht auflösbar", "Adresse nicht rechtzeitig auflösbar", "Gerade hängen zu viele",
                   "Zeitlimit überschritten")


def _archiv_verweigert(url: str) -> str:
    """Warum diese Adresse (jetzt) nicht an archive.org geht (leer = sie darf). archive.org bekommt die URL und macht
    sie öffentlich: keine Zugangsdaten in der Adresse, nichts aus dem eigenen Netz.

    Dauerhafte Ablehnungen beginnen mit einem Text aus ``_VERWEIGERT`` (die Quelle kommt nie wieder dran); ein
    vorübergehender DNS-Fehler zählt nur als gewöhnlicher Fehlschlag."""
    try:
        teile = urlsplit(url)
    except ValueError:  # „http://[::1“
        return "Nicht an archive.org gegeben: Ungültige Adresse."
    if teile.username or teile.password:
        return "Die Adresse enthält Zugangsdaten und geht nicht an archive.org."
    heikel = [k for k, _ in parse_qsl(teile.query, keep_blank_values=True) if _zugangs_parameter(k)]
    if heikel:
        return f"Die Adresse trägt einen Zugangs-Parameter ({heikel[0][:30]}) und geht nicht an archive.org."
    try:
        pruefe_url(url, frist=time.monotonic() + ARCHIV_PRUEF_FRIST)
    except AbrufFehler as fehler:
        if str(fehler).startswith(_VORUEBERGEHEND):
            return f"archive.org später erneut: {fehler}"
        return f"Nicht an archive.org gegeben: {fehler}"
    return ""


def archive_org_sichern(quelle: Quelle, versuch: int = 0) -> Sicherung | None:
    """Frischer Schnappschuss; gelingt er nicht, zählt der jüngste vorhandene, und später wird es erneut versucht.
    Ist archive.org aus (Einstellung der Redaktion, sonst ``AKTE_ARCHIV_AKTIV``), geht nichts hinaus (``None``)."""
    if not archiv_org_aktiv():
        return None
    verweigert = _archiv_verweigert(quelle.url)
    if verweigert:
        return _fehler(quelle, SicherungArt.ARCHIVE_ORG, verweigert)
    ziel, text, voruebergehend = _schnappschuss_anlegen(quelle.url)
    vermerk = ""
    if not ziel:
        ziel = _vorhandener_schnappschuss(quelle.url)
        vermerk = f"Älterer Schnappschuss; neuer gescheitert ({text})" if ziel else ""
        if voruebergehend:
            _spaeter_nochmal(quelle.id, versuch)
    if not ziel:
        return _fehler(quelle, SicherungArt.ARCHIVE_ORG, text)
    if not quelle.archiv_url:
        quelle.archiv_url = ziel[:1000]
        quelle.save(update_fields=["archiv_url"])
    return Sicherung.objects.create(
        quelle=quelle, art=SicherungArt.ARCHIVE_ORG, status=SicherungStatus.FERTIG,
        fremd_url=ziel[:1000], gesichert_am=timezone.now(), fehler=vermerk[:300],
    )


ARCHIV_VERSUCHE = 3


def _spaeter_nochmal(quelle_id: int, versuch: int) -> None:
    """archive.org drosselt anonyme Anfragen: in 5, 20, 60 Minuten erneut. Nur mit Celery-Worker (der kennt
    Wartezeiten); im Thread des API-Prozesses und in Tests nicht."""
    if (versuch + 1 >= ARCHIV_VERSUCHE or hintergrund.modus() != "celery"
            or getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)):
        return
    from .tasks import archiv_nachholen

    archiv_nachholen.apply_async((quelle_id, versuch + 1), countdown=(300, 1200, 3600)[versuch])


def quelle_sichern_jetzt(quelle: Quelle) -> None:
    """Original sichern; archive.org (wenn eingeschaltet) als eigener Auftrag in der Warteschlange „archiv“, damit
    ein langsames archive.org die übrigen Sicherungen nicht aufhält. Im Modus ``sofort`` läuft er gleich mit."""
    if not quelle.url:
        return
    original_sichern(quelle)
    if archiv_org_aktiv():
        from .tasks import archiv_nachholen

        hintergrund.starten(archiv_nachholen, quelle.id, 0)


# ─── Nachholen ──────────────────────────────────────────────────────────────
#: So viele Quellen je Charge; die nächste Charge reiht sich hinter der laufenden ein, bis alles durch ist.
CHARGE = 25
#: Höchstens so viele Chargen hintereinander (Notbremse; 1000 × 25 Quellen).
CHARGEN_MAX = 1000
#: Wer in dieser Zeit schon versucht wurde, kommt nicht gleich wieder dran (kein Sturm nach mehreren Neustarts).
NACHHOLEN_PAUSE = timedelta(hours=1)
#: Nach so vielen Fehlschlägen holt die Akte eine Quelle nicht mehr von selbst nach („Neu sichern“ geht weiter).
FEHLSCHLAEGE_MAX = 3
#: Fehlertexte, mit denen ``_archiv_verweigert`` eine Adresse für archive.org ablehnt: Die kommt nie wieder dran.
_VERWEIGERT = ("Die Adresse enthält Zugangsdaten", "Die Adresse trägt einen Zugangs-Parameter",
               "Nicht an archive.org gegeben")
NACHHOLARTEN = (SicherungArt.ORIGINAL, SicherungArt.ARCHIVE_ORG)


def nachhol_kandidaten(art: str):
    """Quellen mit Link, denen das Original (``original``) bzw. die Archivkopie (``archive_org``) fehlt.

    Ausgenommen: in der letzten Stunde versucht, schon ``FEHLSCHLAEGE_MAX`` Fehlschläge, für archive.org verweigerte
    Adressen. Reihenfolge: noch nie versucht zuerst, dann der am längsten zurückliegende letzte Versuch."""
    from django.db.models import Count, F, Max, Q

    qs = Quelle.objects.exclude(url="")
    if art == SicherungArt.ORIGINAL:
        fertig = Sicherung.objects.filter(art__in=[SicherungArt.ORIGINAL, SicherungArt.ANHANG],
                                          status=SicherungStatus.FERTIG).values("quelle_id")
        qs = qs.exclude(pk__in=fertig)
    else:
        verweigert = Q()
        for anfang in _VERWEIGERT:
            verweigert |= Q(fehler__startswith=anfang)
        qs = qs.filter(archiv_url="").exclude(pk__in=Sicherung.objects.filter(
            verweigert, art=SicherungArt.ARCHIVE_ORG, status=SicherungStatus.FEHLER).values("quelle_id"))
    qs = qs.annotate(
        letzter_versuch=Max("sicherungen__erstellt_am", filter=Q(sicherungen__art=art)),
        fehlschlaege=Count("sicherungen", filter=Q(sicherungen__art=art, sicherungen__status=SicherungStatus.FEHLER)),
    )
    qs = qs.filter(Q(letzter_versuch__isnull=True) | Q(letzter_versuch__lt=timezone.now() - NACHHOLEN_PAUSE),
                   fehlschlaege__lt=FEHLSCHLAEGE_MAX)
    return qs.order_by(F("letzter_versuch").asc(nulls_first=True), "erstellt_am", "id")


def nachholen_charge_jetzt(art: str, runde: int = 0) -> int:
    """Eine Charge in die passende Warteschlange (Original: „lang“, archive.org: „archiv“) und, wenn danach noch
    mehr kommen kann, die nächste Charge dahinter. Weil jede Sicherung eine Zeile hinterlässt (fertig oder Fehler),
    fällt jede Quelle nach ihrem Versuch aus der Auswahl: Die Kette endet von selbst. Gibt die Zahl zurück."""
    from .tasks import archiv_nachholen, nachholen_charge, quelle_sichern

    if hintergrund.modus() == "sofort" or not getattr(settings, "AKTE_SICHERUNG_AKTIV", True):
        return 0
    if art == SicherungArt.ARCHIVE_ORG and not archiv_org_aktiv():
        return 0  # inzwischen ausgeschaltet: nichts mehr hinausgeben
    ids = list(nachhol_kandidaten(art).values_list("id", flat=True)[:CHARGE])
    for quelle_id in ids:
        if art == SicherungArt.ORIGINAL:
            hintergrund.starten(quelle_sichern, quelle_id)
        else:
            hintergrund.starten(archiv_nachholen, quelle_id, 0)
    if len(ids) == CHARGE and runde + 1 < CHARGEN_MAX:
        hintergrund.starten(nachholen_charge, art, runde + 1)
    return len(ids)


def nachholen_beim_start() -> dict:
    """Beim Start des API-Prozesses (``gunicorn.conf.py``): Was ein Neustart aus der Warteschlange verloren hat, kommt
    wieder hinein – Quellen ohne eigene Kopie, und bei eingeschaltetem archive.org Quellen ohne Archivkopie, jeweils
    in Chargen, bis alles durch ist. Nur im Thread-Betrieb (ein Celery-Worker hat seine eigene, beständige
    Warteschlange). Gibt die Zahlen der ersten Charge zurück."""
    if hintergrund.modus() != "thread" or not getattr(settings, "AKTE_SICHERUNG_AKTIV", True):
        return {"original": 0, "archiv": 0}
    originale = nachholen_charge_jetzt(SicherungArt.ORIGINAL)
    archiv = nachholen_charge_jetzt(SicherungArt.ARCHIVE_ORG) if archiv_org_aktiv() else 0
    if originale or archiv:
        logger.info("Akte: Nachholen beim Start: %s Originale, %s Archivkopien (erste Charge)", originale, archiv)
    return {"original": originale, "archiv": archiv}


def archiv_nachholen_alle() -> int:
    """archive.org wurde eingeschaltet: ältere Quellen ohne Archivkopie in Chargen in die Warteschlange „archiv“.
    Nicht im Modus ``sofort`` (Tests, Demo): dort ginge es gleich ins Netz."""
    return nachholen_charge_jetzt(SicherungArt.ARCHIVE_ORG)


def anhang_speichern(quelle: Quelle, daten: bytes, dateiname: str) -> Sicherung:
    """Eigene Datei (PDF oder Bild). Wirft ``ValueError`` mit einer Meldung für Menschen."""
    if len(daten) > ANHANG_MAX:
        raise ValueError("Höchstens 15 MB je Anhang.")
    art = erkenne(daten)
    if art not in ANHANG_ERLAUBT:
        raise ValueError("Nur PDF, PNG, JPEG, GIF oder WEBP.")
    s = _ablegen(quelle, SicherungArt.ANHANG, daten, dateiname=dateiname)
    if art in BILDER and not quelle.sicherungen.filter(art=SicherungArt.VORSCHAU, status=SicherungStatus.FERTIG).exists():
        Sicherung.objects.create(
            quelle=quelle, art=SicherungArt.VORSCHAU, status=SicherungStatus.FERTIG, schluessel=s.schluessel,
            sha256=s.sha256, bytes=s.bytes, mime=s.mime, gesichert_am=s.gesichert_am,
        )
    return s


# ─── Bild der Seite und Fundstellen ─────────────────────────────────────────

def _browser_anstossen(quelle: Quelle, art: str) -> None:
    """Nach dem Original: Seite fotografieren (nur HTML, nur mit Browser) und jede Zitatstelle markieren.

    PDF-Fundstellen brauchen keinen Browser (pdfium). Seit die Sicherung im Hintergrund läuft, steht ein Beleg oft
    schon vor dem Original in der Akte; seine Fundstelle entsteht dann erst hier."""
    from .tasks import fundstelle_sichern, seite_rendern_task

    browser = getattr(settings, "AKTE_BROWSER_AKTIV", True)
    quelle_id = quelle.id
    if art == "html" and browser:
        transaction.on_commit(lambda: hintergrund.starten(seite_rendern_task, quelle_id))
    if art != "pdf" and not browser:
        return
    for beleg_id in quelle.belege.exclude(zitat_woertlich="").values_list("id", flat=True):
        transaction.on_commit(lambda b=beleg_id: hintergrund.starten(fundstelle_sichern, b))


def seite_sichern(quelle: Quelle) -> None:
    from .rendern import seite_rendern

    try:
        bild, pdf = seite_rendern(quelle.url)
    except Exception as fehler:  # noqa: BLE001 — Browser-Fehler sind vielfältig; festhalten statt abstürzen
        _fehler(quelle, SicherungArt.SCREENSHOT, f"Seite nicht fotografiert: {str(fehler)[:200]}")
        return
    _ablegen(quelle, SicherungArt.SCREENSHOT, bild, abgerufen_von=quelle.url)
    _ablegen(quelle, SicherungArt.SEITE_PDF, pdf, abgerufen_von=quelle.url)
    if not quelle.sicherungen.filter(art=SicherungArt.VORSCHAU, status=SicherungStatus.FERTIG).exists():
        _ablegen(quelle, SicherungArt.VORSCHAU, _kopfbild(bild))


def _kopfbild(bild: bytes) -> bytes:
    """Oberer Teil des Seitenbilds, 640 px breit — leicht genug für die Karte auf der Wand."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(bild)) as b:
        kopf = b.convert("RGB").crop((0, 0, b.width, min(b.height, int(b.width * 0.75))))
        kopf.thumbnail((640, 480))
        aus = io.BytesIO()
        kopf.save(aus, "JPEG", quality=82)
        return aus.getvalue()


def eigene_kopie(quelle: Quelle) -> Sicherung | None:
    """Die jüngste fertige eigene Kopie (Original oder Anhang) einer Quelle."""
    return (
        quelle.sicherungen.filter(art__in=[SicherungArt.ORIGINAL, SicherungArt.ANHANG], status=SicherungStatus.FERTIG)
        .order_by("-erstellt_am", "-id").first()
    )


_eigene_kopie = eigene_kopie  # alter Name


def fundstelle_jetzt(beleg) -> str:
    """Markierte Fundstelle für einen Beleg. Liefert ``pdf``, ``browser`` (dort weitermachen) oder ``nichts``.

    Die Sicherung entsteht gleich mit dem Beleg (nicht nachträglich per ``.update()``): sonst sähe die
    Live-Aktualisierung der Wand kurz eine Fundstelle ohne Beleg."""
    quelle = beleg.quelle
    if not beleg.zitat_woertlich.strip():
        return "nichts"
    kopie = eigene_kopie(quelle)
    if kopie and kopie.mime == "application/pdf":
        from .rendern import fundstelle_pdf

        try:
            pdf = speicher.lesen(kopie.schluessel)
        except speicher.KopieBeschaedigt as fehler:
            _fehler(quelle, SicherungArt.FUNDSTELLE, str(fehler), beleg=beleg)
            return "nichts"
        bild = fundstelle_pdf(pdf, beleg.zitat_woertlich)
        if bild:
            _ablegen(quelle, SicherungArt.FUNDSTELLE, bild, beleg=beleg)
        else:
            _fehler(quelle, SicherungArt.FUNDSTELLE, "Zitat im PDF nicht gefunden.", beleg=beleg)
        return "pdf"
    if quelle.url:
        return "browser"
    return "nichts"


def fundstelle_im_browser(beleg) -> None:
    from .rendern import fundstelle_html

    quelle = beleg.quelle
    try:
        bild = fundstelle_html(quelle.url, beleg.zitat_woertlich)
    except Exception as fehler:  # noqa: BLE001
        _fehler(quelle, SicherungArt.FUNDSTELLE, f"Fundstelle nicht fotografiert: {str(fehler)[:180]}", beleg=beleg)
        return
    if bild:
        _ablegen(quelle, SicherungArt.FUNDSTELLE, bild, beleg=beleg)
    else:
        _fehler(quelle, SicherungArt.FUNDSTELLE, "Zitat auf der Seite nicht gefunden.", beleg=beleg)


def video_lokal_melden(quelle: Quelle, pfad: str, sha256: str, groesse: int, dateiname: str, zeitmarke: str) -> Sicherung:
    """Der Video-Helfer auf dem eigenen Rechner meldet: das Video liegt im lokalen Archiv, mit Prüfsumme."""
    return Sicherung.objects.create(
        quelle=quelle, art=SicherungArt.VIDEO_LOKAL, status=SicherungStatus.FERTIG, sha256=sha256[:64],
        bytes=max(0, int(groesse)), mime="video/mp4", dateiname=dateiname[:200], fremd_url=pfad[:1000],
        fehler=(f"Zeitmarke {zeitmarke}" if zeitmarke else "")[:300], gesichert_am=timezone.now(),
    )
