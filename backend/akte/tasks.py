"""Hintergrund-Aufgaben der Akte.

Läuft auf der Queue ``default`` (vom bestehenden Worker konsumiert). Das Rendern von
Seiten mit einem Browser kommt später auf eine eigene Queue und einen eigenen Dienst.
Kein automatisches Wiederholen: ein Fehler steht als Sicherung mit Status „Fehler“
in der Akte, und die Redaktion stößt per „Neu sichern“ erneut an.
"""

from celery import shared_task

from .models import Quelle


@shared_task(queue="default", soft_time_limit=240, time_limit=300)
def quelle_sichern(quelle_id: int) -> None:
    from .sicherung import quelle_sichern_jetzt

    quelle = Quelle.objects.filter(pk=quelle_id).first()
    if quelle:
        quelle_sichern_jetzt(quelle)


@shared_task(queue="default", soft_time_limit=180, time_limit=240)
def archiv_nachholen(quelle_id: int, versuch: int) -> None:
    from .sicherung import archive_org_sichern

    quelle = Quelle.objects.filter(pk=quelle_id).first()
    if quelle and quelle.url:
        archive_org_sichern(quelle, versuch)


# ─── Browser-Aufgaben: eigener Dienst „akte-sicherung“ mit Chromium, Queue akte_browser ──

@shared_task(queue="akte_browser", soft_time_limit=150, time_limit=180)
def seite_rendern_task(quelle_id: int) -> None:
    from .sicherung import seite_sichern

    quelle = Quelle.objects.filter(pk=quelle_id).first()
    if quelle and quelle.url:
        seite_sichern(quelle)


@shared_task(queue="default", soft_time_limit=120, time_limit=150)
def fundstelle_sichern(beleg_id: int) -> None:
    """PDF-Fundstellen gleich hier (pdfium, kein Browser); Webseiten weiter an den Browser-Dienst."""
    from .models import Beleg
    from .sicherung import fundstelle_jetzt

    from django.conf import settings

    beleg = Beleg.objects.select_related("quelle").filter(pk=beleg_id).first()
    if beleg and fundstelle_jetzt(beleg) == "browser" and getattr(settings, "AKTE_BROWSER_AKTIV", False):
        fundstelle_browser.delay(beleg_id)


@shared_task(queue="akte_browser", soft_time_limit=150, time_limit=180)
def fundstelle_browser(beleg_id: int) -> None:
    from .models import Beleg
    from .sicherung import fundstelle_im_browser

    beleg = Beleg.objects.select_related("quelle").filter(pk=beleg_id).first()
    if beleg:
        fundstelle_im_browser(beleg)
