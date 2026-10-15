"""Einstellungen für ``python -m pytest`` (pytest-django, siehe ``pytest.ini``).

Setzt ``AKTE_TESTLAUF=1`` ausdrücklich, bevor die eigentlichen Einstellungen geladen werden; ``settings.py`` erkennt
den Testlauf nur mit diesem Schalter UND laufendem pytest. Im Betrieb wird diese Datei nie geladen.
"""

import os

os.environ["AKTE_TESTLAUF"] = "1"

from .settings import *  # noqa: E402,F401,F403
from .settings import TESTLAUF  # noqa: E402

if not TESTLAUF:  # pragma: no cover – nur, wenn jemand diese Datei außerhalb von pytest lädt
    raise RuntimeError("aktesite.settings_pytest ist nur für pytest gedacht.")
