"""Hintergrund-Aufgaben der Akte.

Gestartet werden sie über ``hintergrund.starten``: ohne Redis in einem Arbeiter-Thread des API-Prozesses, mit Redis
auf der Celery-Queue ``default`` bzw. ``akte_browser`` (eigener Dienst mit Chromium). Kein automatisches Wiederholen:
ein Fehler steht als Sicherung mit Status „Fehler“ in der Akte, und die Redaktion stößt per „Neu sichern“ erneut an.

Auch ein unerwarteter Fehler (Programmfehler, Zeitgrenze) landet so in der Akte (``_fehler_festhalten``): Die
Oberfläche zeigt ihn an der Quelle, statt dass er nur im Log steht.
"""

import functools
import logging

from celery import shared_task

from .models import Quelle, SicherungArt

logger = logging.getLogger(__name__)


def _fehler_sichern(art: str, bezug: str, objekt_id: int, fehler: Exception) -> None:
    from .models import Beleg, Sicherung, SicherungStatus

    text = f"Unerwarteter Fehler bei der Sicherung ({type(fehler).__name__}). Bitte erneut sichern."
    try:
        if bezug == "beleg":
            beleg = Beleg.objects.select_related("quelle").filter(pk=objekt_id).first()
            if beleg is not None:
                Sicherung.objects.create(quelle=beleg.quelle, beleg=beleg, art=art, status=SicherungStatus.FEHLER,
                                         fehler=text)
        else:
            quelle = Quelle.objects.filter(pk=objekt_id).first()
            if quelle is not None:
                Sicherung.objects.create(quelle=quelle, art=art, status=SicherungStatus.FEHLER, fehler=text)
    except Exception:  # noqa: BLE001 — festhalten darf selbst nie scheitern
        logger.exception("Akte: Fehler der Aufgabe nicht als Sicherung festgehalten")


def _fehler_festhalten(art: str, bezug: str = "quelle"):
    """Jede Ausnahme der Aufgabe wird geloggt und als Sicherung mit Status „Fehler“ an der Quelle festgehalten."""

    def deko(funktion):
        @functools.wraps(funktion)
        def huelle(objekt_id, *rest):
            try:
                return funktion(objekt_id, *rest)
            except Exception as fehler:  # noqa: BLE001
                logger.exception("Akte: Aufgabe %s für %s %s gescheitert", funktion.__name__, bezug, objekt_id)
                _fehler_sichern(art, bezug, objekt_id, fehler)
                return None

        return huelle

    return deko


@shared_task(queue="default", soft_time_limit=240, time_limit=300)
@_fehler_festhalten(SicherungArt.ORIGINAL)
def quelle_sichern(quelle_id: int) -> None:
    from .sicherung import quelle_sichern_jetzt

    quelle = Quelle.objects.filter(pk=quelle_id).first()
    if quelle:
        quelle_sichern_jetzt(quelle)


@shared_task(queue="default", soft_time_limit=180, time_limit=240)
@_fehler_festhalten(SicherungArt.ARCHIVE_ORG)
def archiv_nachholen(quelle_id: int, versuch: int = 0) -> None:
    from .sicherung import archive_org_sichern

    quelle = Quelle.objects.filter(pk=quelle_id).first()
    if quelle and quelle.url:
        archive_org_sichern(quelle, versuch)


@shared_task(queue="default", soft_time_limit=60, time_limit=90)
def nachholen_charge(art: str, runde: int = 0) -> None:
    """Nächste Charge des Nachholens (``sicherung.nachholen_charge_jetzt``). Läuft im selben Arbeiter wie ihre
    Aufträge und steht hinter ihnen: Wenn sie dran ist, ist die vorige Charge durch."""
    from .sicherung import nachholen_charge_jetzt

    nachholen_charge_jetzt(art, runde)


# ─── Browser-Aufgaben: eigener Dienst „akte-sicherung“ mit Chromium, Queue akte_browser ──

@shared_task(queue="akte_browser", soft_time_limit=150, time_limit=180)
@_fehler_festhalten(SicherungArt.SCREENSHOT)
def seite_rendern_task(quelle_id: int) -> None:
    from .sicherung import seite_sichern

    quelle = Quelle.objects.filter(pk=quelle_id).first()
    if quelle and quelle.url:
        seite_sichern(quelle)


@shared_task(queue="default", soft_time_limit=120, time_limit=150)
@_fehler_festhalten(SicherungArt.FUNDSTELLE, "beleg")
def fundstelle_sichern(beleg_id: int) -> None:
    """PDF-Fundstellen gleich hier (pdfium, kein Browser); Webseiten weiter an den Browser-Dienst."""
    from django.conf import settings

    from . import hintergrund
    from .models import Beleg
    from .sicherung import fundstelle_jetzt

    beleg = Beleg.objects.select_related("quelle").filter(pk=beleg_id).first()
    if beleg and fundstelle_jetzt(beleg) == "browser" and getattr(settings, "AKTE_BROWSER_AKTIV", False):
        hintergrund.starten(fundstelle_browser, beleg_id)


@shared_task(queue="akte_browser", soft_time_limit=150, time_limit=180)
@_fehler_festhalten(SicherungArt.FUNDSTELLE, "beleg")
def fundstelle_browser(beleg_id: int) -> None:
    from .models import Beleg
    from .sicherung import fundstelle_im_browser

    beleg = Beleg.objects.select_related("quelle").filter(pk=beleg_id).first()
    if beleg:
        fundstelle_im_browser(beleg)
