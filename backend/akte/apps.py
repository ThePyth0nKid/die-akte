from django.apps import AppConfig


class AkteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "akte"
    verbose_name = "Ultra-Akte — Ermittler-Wand"

    def ready(self):
        from . import checks  # noqa: F401 — Systemprüfungen anmelden (Board-Kennung „einrichten“)

        # Jede Änderung an Inhalten der Wand macht den Cache der Lese-Ansicht ohne Konto ungültig (lesecache.py).
        from django.db.models.signals import m2m_changed, post_delete, post_save

        from . import lesecache
        from .models import (
            Beleg, Board, BoardKarte, Entitaet, Ereignis, Mappe, Quelle, Rahmen, Sicherung, Ueberstimmung, Verbindung,
            Zettel,
        )

        # Ereignis, Überstimmung und Sicherung gehören dazu: Freigaben und Beweise ändern, was Leser sehen dürfen.
        for modell in (Beleg, Board, BoardKarte, Entitaet, Ereignis, Mappe, Quelle, Rahmen, Sicherung, Ueberstimmung,
                       Verbindung, Zettel):
            post_save.connect(lesecache.veraltet, sender=modell, dispatch_uid=f"akte-lesecache-save-{modell.__name__}")
            post_delete.connect(lesecache.veraltet, sender=modell, dispatch_uid=f"akte-lesecache-del-{modell.__name__}")
        m2m_changed.connect(lesecache.veraltet, sender=Board.ausgeblendete_verbindungen.through,
                            dispatch_uid="akte-lesecache-ausgeblendet")
        # Nur für die Live-Aktualisierung der Werkstatt (Stand der Wand): Leser sehen Fahrten und Beweisstücke nicht.
        from .models import BoardBeweis, Fahrt, Station

        for modell in (BoardBeweis, Fahrt, Station):
            post_save.connect(lesecache.werkstatt_veraltet, sender=modell,
                              dispatch_uid=f"akte-werkstatt-save-{modell.__name__}")
            post_delete.connect(lesecache.werkstatt_veraltet, sender=modell,
                                dispatch_uid=f"akte-werkstatt-del-{modell.__name__}")

        # Beweisschicht: jede fertige Sicherung wird nach dem Speichern ein signiertes Ereignis der Kette.
        from django.db import transaction

        from . import beweisschicht
        from .models import Sicherung, SicherungArt

        def _sicherung_fertig(sender, instance, created, **kwargs):
            # Nur, was der Server selbst gesehen hat. Ein lokal gemeldetes Video (Prüfsumme vom Helfer, Datei nie
            # auf dem Server) unterschreibt das Gerät nicht.
            if (created and instance.status == "fertig" and (instance.sha256 or instance.fremd_url)
                    and instance.art != SicherungArt.VIDEO_LOKAL):
                transaction.on_commit(lambda: beweisschicht.sicherung_eintragen(instance))

        # weak=False: eine verschachtelte Funktion hielte sonst niemand am Leben, der Empfänger verschwände still.
        post_save.connect(_sicherung_fertig, sender=Sicherung, weak=False, dispatch_uid="akte-beweis-sicherung")
