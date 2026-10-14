"""Der Testlauf (schneller Hash, keine Drosseln, Wegwerf-Schlüssel) gilt nur mit ausdrücklichem AKTE_TESTLAUF=1 UND
laufendem Test (PR15, CR12). Geprüft in eigenen Prozessen, weil die Einstellungen nur einmal je Prozess laden."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

BACKEND = Path(__file__).resolve().parents[2]


def _testlauf(code_vorher: str, **umgebung) -> str:
    env = {k: v for k, v in os.environ.items() if k not in ("AKTE_TESTLAUF", "PYTEST_VERSION", "DJANGO_SETTINGS_MODULE")}
    code = f"{code_vorher}\nfrom aktesite import settings\nprint(settings.TESTLAUF)"
    with tempfile.TemporaryDirectory(prefix="akte-testlauf-") as daten:
        env.update({"DJANGO_DEBUG": "1", "AKTE_DATEN": daten, **umgebung})
        lauf = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True,
                              timeout=120)
    assert lauf.returncode == 0, lauf.stderr
    return lauf.stdout.strip()


class TestlaufTest(SimpleTestCase):
    def test_pytest_allein_reicht_nicht(self):
        self.assertEqual(_testlauf("import pytest", PYTEST_VERSION="9"), "False")

    def test_schalter_allein_reicht_nicht(self):
        # z. B. AKTE_TESTLAUF=1 versehentlich in der .env des Betriebs
        self.assertEqual(_testlauf("", AKTE_TESTLAUF="1"), "False")

    def test_schalter_und_pytest(self):
        self.assertEqual(_testlauf("import pytest", AKTE_TESTLAUF="1", PYTEST_VERSION="9"), "True")

    def test_schalter_und_manage_test(self):
        self.assertEqual(_testlauf("import sys; sys.argv = ['manage.py', 'test']", AKTE_TESTLAUF="1"), "True")
