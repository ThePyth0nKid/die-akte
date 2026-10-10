"""Celery-App, nur für den optionalen Betrieb mit Redis und eigenem Worker (docs/betrieb.md).

Lokal ohne Redis laufen die Aufgaben im Prozess (``CELERY_TASK_ALWAYS_EAGER``).
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aktesite.settings")

app = Celery("aktesite")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.task_default_queue = "default"
app.conf.task_queues = {
    "default": {"exchange": "default", "routing_key": "default"},
    # Seiten fotografieren braucht Chromium; nur der Browser-Worker abonniert diese Queue.
    "akte_browser": {"exchange": "akte_browser", "routing_key": "akte_browser"},
}
