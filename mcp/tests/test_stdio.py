"""Der Server startet als eigener Prozess über stdio, so wie Claude Code ihn aufruft."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.integration


def _befehl() -> tuple[str, list[str]]:
    gefunden = shutil.which("akte-mcp", path=os.path.dirname(sys.executable))
    return (gefunden, []) if gefunden else (sys.executable, ["-m", "akte_mcp.server"])


def test_stdio_start_und_werkzeugliste(backend):
    befehl, argumente = _befehl()
    parameter = StdioServerParameters(command=befehl, args=argumente,
                                      env={**os.environ, "AKTE_BASIS": backend["basis"], "AKTE_TOKEN": ""})

    async def lauf():
        async with stdio_client(parameter) as (lesen, schreiben):
            async with ClientSession(lesen, schreiben) as sitzung:
                info = await sitzung.initialize()
                werkzeuge = {t.name for t in (await sitzung.list_tools()).tools}
                return info.serverInfo.name, info.instructions or "", werkzeuge

    name, anweisung, werkzeuge = asyncio.run(lauf())
    assert name == "ultra-akte"
    assert "Freigeben tut ein Mensch" in anweisung
    assert werkzeuge == {"boards_liste", "wand_lesen", "suche", "weg"}


def test_ohne_basis_bricht_mit_hinweis_ab():
    befehl, argumente = _befehl()
    import subprocess

    umgebung = {k: v for k, v in os.environ.items() if k != "AKTE_BASIS"}
    lauf = subprocess.run([befehl, *argumente], env=umgebung, capture_output=True, text=True, timeout=60)
    assert lauf.returncode == 2
    assert "AKTE_BASIS fehlt" in lauf.stderr
