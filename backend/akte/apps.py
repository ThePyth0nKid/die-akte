from django.apps import AppConfig


class AkteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "akte"
    verbose_name = "Die Akte — Ermittler-Wand"

    def ready(self):
        # Jede Änderung an Inhalten der Wand macht den Cache der Lese-Ansicht ohne Konto ungültig (lesecache.py).
        from django.db.models.signals import m2m_changed, post_delete, post_save

        from . import lesecache
        from .models import Beleg, Board, BoardKarte, Entitaet, Mappe, Quelle, Rahmen, Verbindung, Zettel

        for modell in (Beleg, Board, BoardKarte, Entitaet, Mappe, Quelle, Rahmen, Verbindung, Zettel):
            post_save.connect(lesecache.veraltet, sender=modell, dispatch_uid=f"akte-lesecache-save-{modell.__name__}")
            post_delete.connect(lesecache.veraltet, sender=modell, dispatch_uid=f"akte-lesecache-del-{modell.__name__}")
        m2m_changed.connect(lesecache.veraltet, sender=Board.ausgeblendete_verbindungen.through,
                            dispatch_uid="akte-lesecache-ausgeblendet")
