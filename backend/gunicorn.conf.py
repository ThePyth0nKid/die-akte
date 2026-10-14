"""Gunicorn-Einstellungen der Akte (wird aus dem Arbeitsordner /app automatisch gelesen).

Nur ein Haken: Wenn der Worker bereit ist, holt die Akte im Thread-Betrieb nach, was ein Neustart aus der
Warteschlange der Beweissicherung verloren hat (``akte.sicherung.nachholen_beim_start``). Alle übrigen Schalter
setzt ``start.sh`` auf der Befehlszeile.
"""


def post_worker_init(worker):  # noqa: ARG001 — Haken von Gunicorn
    try:
        from akte.sicherung import nachholen_beim_start

        nachholen_beim_start()
    except Exception:  # noqa: BLE001 — Nachholen darf den Start nie verhindern
        import logging

        logging.getLogger("akte").exception("Akte: Nachholen beim Start gescheitert")
