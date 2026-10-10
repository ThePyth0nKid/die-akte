# SPDX-License-Identifier: MIT
"""Tests für den Scrub-Prüfer: Treffer, Ausnahmen und was im Log erscheinen darf."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("scrub_pruefen", Path(__file__).with_name("pruefen.py"))
scrub = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = scrub  # für dataclasses nötig
_spec.loader.exec_module(scrub)

# Ein Schlüssel-förmiger Testwert, zusammengesetzt, damit diese Datei selbst sauber bleibt.
SCHLUESSEL = "gh" + "p_" + "A" * 36


def _oeffentlich():
    return scrub.regeln_laden(nur_oeffentlich=True)[0]


def test_oeffentliche_regel_trifft_und_wird_maskiert(tmp_path, capsys):
    datei = tmp_path / "a.txt"
    datei.write_text(f"token = {SCHLUESSEL}\n", encoding="utf-8")
    funde = scrub.dateien_pruefen([datei], tmp_path, _oeffentlich())
    assert len(funde) == 1
    scrub.ausgeben(funde, zeigen=False)
    ausgabe = capsys.readouterr().out
    assert SCHLUESSEL not in ausgabe and "Zeichen" in ausgabe
    scrub.ausgeben(funde, zeigen=True)
    assert SCHLUESSEL in capsys.readouterr().out


def test_platzhalterpfad_ist_erlaubt(tmp_path):
    datei = tmp_path / "b.md"
    datei.write_text("Lege die Datei unter C:/Users/<name>/studio.toml ab.\n", encoding="utf-8")
    assert scrub.dateien_pruefen([datei], tmp_path, _oeffentlich()) == []


def test_erlaubt_marke_gilt_nur_fuer_oeffentliche_regeln(tmp_path):
    regeln = _oeffentlich() + scrub._regeln_lesen("geheimwort", True, "privat")
    datei = tmp_path / "c.txt"
    datei.write_text(f"{SCHLUESSEL} geheimwort  # scrub:erlaubt\n", encoding="utf-8")
    funde = scrub.dateien_pruefen([datei], tmp_path, regeln)
    assert [f.regel.privat for f in funde] == [True]


def test_private_regex_fehler_verraet_kein_muster():
    with pytest.raises(SystemExit) as fehler:
        scrub._regeln_lesen("geheim(", True, "privat")
    assert "geheim" not in str(fehler.value)


def test_zu_gross_oder_unlesbar_ist_ein_fund(tmp_path):
    datei = tmp_path / "gross.bin"
    datei.write_bytes(b"x")
    funde = scrub.dateien_pruefen([datei], tmp_path, _oeffentlich(), max_mb=0)
    assert [f.regel is scrub.UNGEPRUEFT for f in funde] == [True]
    weg = tmp_path / "gibt-es-nicht.txt"
    assert scrub.dateien_pruefen([weg], tmp_path, _oeffentlich())[0].regel is scrub.UNGEPRUEFT


def test_utf16_und_zerlegte_umlaute_werden_erkannt(tmp_path):
    utf16 = tmp_path / "notiz.txt"
    utf16.write_bytes(f"token = {SCHLUESSEL}\n".encode("utf-16"))
    assert len(scrub.dateien_pruefen([utf16], tmp_path, _oeffentlich())) == 1
    regeln = scrub._regeln_lesen("Müller", True, "privat")
    zerlegt = tmp_path / "z.txt"
    zerlegt.write_bytes("Frau Mu\u0308ller".encode("utf-8"))
    assert len(scrub.dateien_pruefen([zerlegt], tmp_path, regeln)) == 1


def test_pfad_prueft_alles_ausser_git(tmp_path):
    for ordner in ("build", "node_modules", "dist", ".git"):
        (tmp_path / ordner).mkdir()
        (tmp_path / ordner / "a.txt").write_text("x", encoding="utf-8")
    namen = {p.parent.name for p in scrub.ordner_dateien(tmp_path)}
    assert namen == {"build", "node_modules", "dist"}
    assert {p.parent.name for p in scrub.ordner_dateien(tmp_path, {"node_modules"})} == {"build", "dist"}


def test_privater_treffer_im_dateinamen_bleibt_verdeckt(tmp_path, capsys):
    regeln = _oeffentlich() + scrub._regeln_lesen("geheimwort", True, "privat")
    datei = tmp_path / "geheimwort-notizen.txt"
    datei.write_text(f"token = {SCHLUESSEL}\n", encoding="utf-8")
    funde = scrub.dateien_pruefen([datei], tmp_path, regeln)
    assert len(funde) == 2
    scrub.ausgeben(funde, zeigen=False)
    ausgabe = capsys.readouterr().out
    assert "geheimwort" not in ausgabe and "verdeckt" in ausgabe


def _git(cwd, *args):
    import subprocess

    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_historie_liest_jeden_blob_einmal_und_verweigert_flache_klone(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for k, v in (("user.name", "Test"), ("user.email", "test@example.org"), ("commit.gpgsign", "false")):
        _git(repo, "config", k, v)
    (repo / "a.txt").write_text(f"token = {SCHLUESSEL}\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "eins")
    (repo / "b.txt").write_text("sauber\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "zwei")
    monkeypatch.chdir(repo)
    funde = scrub.historie_pruefen(_oeffentlich())
    assert [f.ort.split(":", 1)[1] for f in funde] == ["a.txt"]  # derselbe Blob in zwei Commits: ein Fund

    flach = tmp_path / "flach"
    _git(tmp_path, "clone", "-q", "--depth", "1", repo.as_uri(), str(flach))
    monkeypatch.chdir(flach)
    with pytest.raises(SystemExit) as fehler:
        scrub.historie_pruefen(_oeffentlich())
    assert "Flacher Klon" in str(fehler.value)


def test_privater_pfad_bleibt_in_jedem_commit_verdeckt(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for k, v in (("user.name", "Test"), ("user.email", "test@example.org"), ("commit.gpgsign", "false")):
        _git(repo, "config", k, v)
    datei = repo / "geheimwort.txt"
    for n in range(2):
        datei.write_text(f"token{n} = {SCHLUESSEL}{n}\n", encoding="utf-8")
        _git(repo, "add", "geheimwort.txt")
        _git(repo, "commit", "-q", "-m", f"c{n}")
    monkeypatch.chdir(repo)
    regeln = _oeffentlich() + scrub._regeln_lesen("geheimwort", True, "privat")
    funde = scrub.historie_pruefen(regeln)
    assert len({f.ort for f in funde if f.zeile}) == 2  # zwei verschiedene Blobs, zwei Commits
    scrub.ausgeben(funde, zeigen=False)
    assert "geheimwort" not in capsys.readouterr().out


def test_windows_1252_trifft_umlaut_regel(tmp_path):
    datei = tmp_path / "alt.txt"
    datei.write_bytes("Frau Müller".encode("cp1252"))
    assert len(scrub.dateien_pruefen([datei], tmp_path, scrub._regeln_lesen("Müller", True, "privat"))) == 1
