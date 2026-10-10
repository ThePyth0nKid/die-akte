"""Gemeinsame Vorrichtungen: ein echtes Backend der Akte als Unterprozess mit Wegwerf-Datenbank.

Das Backend braucht seine eigenen Abhängigkeiten (Django …). Gesucht wird ein Python, das sie hat:
``AKTE_BACKEND_PYTHON``, sonst ``backend/.venv``, sonst der laufende Interpreter.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

WURZEL = Path(__file__).resolve().parents[2]
BACKEND = WURZEL / "backend"


def _backend_python() -> str | None:
    kandidaten = [os.environ.get("AKTE_BACKEND_PYTHON", ""),
                  str(BACKEND / ".venv" / "Scripts" / "python.exe"), str(BACKEND / ".venv" / "bin" / "python"),
                  sys.executable]
    for k in kandidaten:
        if k and Path(k).exists():
            ok = subprocess.run([k, "-c", "import django, rest_framework"], capture_output=True).returncode == 0
            if ok:
                return k
    return None


def _freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def backend(tmp_path_factory):
    python = _backend_python()
    if not python:
        pytest.skip("Kein Python mit den Backend-Abhängigkeiten gefunden (AKTE_BACKEND_PYTHON setzen).")
    daten = tmp_path_factory.mktemp("akte-daten")
    umgebung = {**os.environ, "AKTE_DATEN": str(daten), "DJANGO_DEBUG": "1", "AKTE_SICHERUNG_AKTIV": "0",
                "AKTE_BROWSER_AKTIV": "0", "AKTE_PASSWORT": "integration-passwort-lang",
                "AKTE_OEFFENTLICH_AKTIV": "1", "PYTHONIOENCODING": "utf-8"}
    manage = [python, "manage.py"]
    for befehl in (["migrate", "--noinput"], ["createcachetable"]):
        subprocess.run(manage + befehl, cwd=BACKEND, env=umgebung, check=True, capture_output=True)
    ausgabe = subprocess.run(manage + ["akte_einrichten", "--benutzer", "werkzeug", "--token"], cwd=BACKEND,
                             env=umgebung, check=True, capture_output=True, text=True, encoding="utf-8").stdout
    token = re.findall(r"^[0-9a-f]{40}$", ausgabe, re.M)[-1]
    port = _freier_port()
    prozess = subprocess.Popen(manage + ["runserver", "--noreload", f"127.0.0.1:{port}"], cwd=BACKEND, env=umgebung,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    basis = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                requests.get(f"{basis}/api/v1/akte/boards/", timeout=1)
                break
            except requests.ConnectionError:
                time.sleep(0.2)
        else:
            pytest.fail("Backend ist nicht hochgekommen.")
        yield {"basis": basis, "token": token, "python": python, "env": umgebung}
    finally:
        prozess.terminate()
        prozess.wait(timeout=10)
