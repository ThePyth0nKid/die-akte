"""Beweissicherung — jede Quelle wird kopiert, geprüft und bei archive.org hinterlegt.

``quelle_sichern`` (per Celery, siehe ``tasks.py``) macht drei Dinge, jedes für sich
fehlertolerant, damit ein gescheitertes archive.org nicht die eigene Kopie verhindert:

1. **Original**: Datei oder Seite laden (``abruf.py``), Art an den ersten Bytes erkennen,
   Prüfsumme bilden, privat ablegen (``speicher.py``). Bei Webseiten Titel, Herausgeber
   und Vorschaubild lesen.
2. **Vorschaubild**: das og:image der Seite, oder das Original selbst, wenn es ein Bild ist.
3. **archive.org**: Save Page Now; die Schnappschuss-Adresse landet in ``Quelle.archiv_url``
   (das erfüllt die Prüfregel „Archivkopie“).

Anhänge (eigene Dateien, Handy-Screenshots) gehen über ``anhang_speichern`` denselben Weg.
"""

import hashlib
import html
import logging
import re
import time

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import speicher
from .abruf import ARTEN, BILDER, AbrufFehler, abrufen, erkenne
from .models import Quelle, Sicherung, SicherungArt, SicherungStatus

logger = logging.getLogger(__name__)

ANHANG_ERLAUBT = {"pdf", "png", "jpeg", "gif", "webp"}
ANHANG_MAX = 15 * 1024 * 1024
VORSCHAU_MAX = 10 * 1024 * 1024
ARCHIVE_ORG = "https://web.archive.org/save/"


def sicherung_anstossen(quelle: Quelle) -> None:
    """Nach dem Speichern der Quelle im Hintergrund sichern (nur mit Link)."""
    if not quelle.url or not getattr(settings, "AKTE_SICHERUNG_AKTIV", True):
        return
    from .tasks import quelle_sichern

    transaction.on_commit(lambda: quelle_sichern.delay(quelle.id))


def _ablegen(quelle: Quelle, art: str, daten: bytes, *, dateiname="", abgerufen_von="") -> Sicherung:
    erkannt = erkenne(daten)
    mime, endung = ARTEN[erkannt]
    sha = hashlib.sha256(daten).hexdigest()
    schl = speicher.schluessel(sha, endung)
    speicher.ablegen(schl, daten, mime)
    return Sicherung.objects.create(
        quelle=quelle, art=art, status=SicherungStatus.FERTIG, schluessel=schl, sha256=sha,
        bytes=len(daten), mime=mime, dateiname=dateiname[:200], abgerufen_von=abgerufen_von[:1000],
        gesichert_am=timezone.now(),
    )


def _fehler(quelle: Quelle, art: str, text: str) -> Sicherung:
    return Sicherung.objects.create(quelle=quelle, art=art, status=SicherungStatus.FEHLER, fehler=text[:300])


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
        abruf = abrufen(quelle.url)
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
        Sicherung.objects.create(
            quelle=quelle, art=SicherungArt.VORSCHAU, status=SicherungStatus.FERTIG, schluessel=s.schluessel,
            sha256=s.sha256, bytes=s.bytes, mime=s.mime, gesichert_am=s.gesichert_am,
        )
    return s


def vorschau_sichern(quelle: Quelle, bild_url: str) -> None:
    try:
        abruf = abrufen(bild_url, max_bytes=VORSCHAU_MAX)
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
            for _ in range(20):
                time.sleep(4)
                st = requests.get(f"https://web.archive.org/save/status/{job_id}", headers=kopf, timeout=(10, 30)).json()
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


def archive_org_sichern(quelle: Quelle, versuch: int = 0) -> Sicherung:
    """Frischer Schnappschuss; gelingt er nicht, zählt der jüngste vorhandene, und später wird es erneut versucht."""
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
    """archive.org drosselt anonyme Anfragen: in 5, 20, 60 Minuten erneut (nicht im Eager-Modus der Tests)."""
    if versuch + 1 >= ARCHIV_VERSUCHE or getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return
    from .tasks import archiv_nachholen

    archiv_nachholen.apply_async((quelle_id, versuch + 1), countdown=(300, 1200, 3600)[versuch])


def quelle_sichern_jetzt(quelle: Quelle) -> None:
    if not quelle.url:
        return
    original_sichern(quelle)
    archive_org_sichern(quelle)


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
    """Nach dem Original: Seite fotografieren (nur HTML) und jede Zitatstelle markieren."""
    if not getattr(settings, "AKTE_BROWSER_AKTIV", True):
        return
    from .tasks import fundstelle_sichern, seite_rendern_task

    if art == "html":
        transaction.on_commit(lambda: seite_rendern_task.delay(quelle.id))
    for beleg_id in quelle.belege.exclude(zitat_woertlich="").values_list("id", flat=True):
        transaction.on_commit(lambda b=beleg_id: fundstelle_sichern.delay(b))


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


def _eigene_kopie(quelle: Quelle) -> Sicherung | None:
    return (
        quelle.sicherungen.filter(art__in=[SicherungArt.ORIGINAL, SicherungArt.ANHANG], status=SicherungStatus.FERTIG)
        .order_by("-erstellt_am").first()
    )


def fundstelle_jetzt(beleg) -> str:
    """Markierte Fundstelle für einen Beleg. Liefert ``pdf``, ``browser`` (dort weitermachen) oder ``nichts``."""
    quelle = beleg.quelle
    if not beleg.zitat_woertlich.strip():
        return "nichts"
    kopie = _eigene_kopie(quelle)
    if kopie and kopie.mime == "application/pdf":
        from .rendern import fundstelle_pdf

        bild = fundstelle_pdf(speicher.lesen(kopie.schluessel), beleg.zitat_woertlich)
        if bild:
            s = _ablegen(quelle, SicherungArt.FUNDSTELLE, bild)
            Sicherung.objects.filter(pk=s.pk).update(beleg=beleg)
        else:
            s = _fehler(quelle, SicherungArt.FUNDSTELLE, "Zitat im PDF nicht gefunden.")
            Sicherung.objects.filter(pk=s.pk).update(beleg=beleg)
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
        s = _fehler(quelle, SicherungArt.FUNDSTELLE, f"Fundstelle nicht fotografiert: {str(fehler)[:180]}")
    else:
        s = _ablegen(quelle, SicherungArt.FUNDSTELLE, bild) if bild else _fehler(
            quelle, SicherungArt.FUNDSTELLE, "Zitat auf der Seite nicht gefunden."
        )
    Sicherung.objects.filter(pk=s.pk).update(beleg=beleg)


def video_lokal_melden(quelle: Quelle, pfad: str, sha256: str, groesse: int, dateiname: str, zeitmarke: str) -> Sicherung:
    """Der Video-Helfer auf dem eigenen Rechner meldet: das Video liegt im lokalen Archiv, mit Prüfsumme."""
    return Sicherung.objects.create(
        quelle=quelle, art=SicherungArt.VIDEO_LOKAL, status=SicherungStatus.FERTIG, sha256=sha256[:64],
        bytes=max(0, int(groesse)), mime="video/mp4", dateiname=dateiname[:200], fremd_url=pfad[:1000],
        fehler=(f"Zeitmarke {zeitmarke}" if zeitmarke else "")[:300], gesichert_am=timezone.now(),
    )
