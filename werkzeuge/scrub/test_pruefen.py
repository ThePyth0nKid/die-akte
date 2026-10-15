# SPDX-License-Identifier: MIT
"""Tests für den Scrub-Prüfer: Treffer, Ausnahmen und was im Log erscheinen darf."""
from __future__ import annotations

import importlib.util
import struct
import sys
import zlib
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


def test_erlaubt_marke_gilt_nur_fuer_weiche_oeffentliche_regeln(tmp_path):
    regeln = _oeffentlich() + scrub._regeln_lesen("geheimwort", True, "privat")
    datei = tmp_path / "c.txt"
    ip = ".".join(["10", "1", "2", "3"])
    datei.write_text(f"{ip} geheimwort  # scrub:erlaubt\n{SCHLUESSEL}  # scrub:erlaubt\n", encoding="utf-8")
    funde = scrub.dateien_pruefen([datei], tmp_path, regeln)
    # Zeile 1: die IP-Regel schweigt, die private Regel nicht. Zeile 2: ein Schlüssel ist HART.
    assert sorted((f.zeile, f.regel.privat) for f in funde) == [(1, True), (2, False)]


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


# Schlüsselförmige Testwerte, zur Laufzeit zusammengesetzt, damit diese Datei selbst sauber bleibt.
NEUE_SCHLUESSEL = ["r" + "e_" + "Ab3" + "x" * 30, "sk" + "-proj-" + "A" * 30, "AI" + "za" + "B" * 35,
                   "sk" + "_live_" + "C" * 24, "h" + "f_" + "D" * 34, "gl" + "pat-" + "E" * 20]


def test_neue_schluesselmuster_und_hart_trotz_marke(tmp_path):
    datei = tmp_path / "k.txt"
    datei.write_text("\n".join(f"wert = {k}  # scrub:erlaubt" for k in NEUE_SCHLUESSEL) + "\n", encoding="utf-8")
    funde = scrub.dateien_pruefen([datei], tmp_path, _oeffentlich())
    assert sorted(f.zeile for f in funde) == list(range(1, len(NEUE_SCHLUESSEL) + 1))
    harmlos = tmp_path / "h.py"
    harmlos.write_text("re_evaluate_signatures_later = 1\nkeyword = 'senat'\n", encoding="utf-8")
    assert scrub.dateien_pruefen([harmlos], tmp_path, _oeffentlich()) == []


def test_gross_klein_auch_bei_umlauten(tmp_path):
    datei = tmp_path / "u.txt"
    datei.write_text("FRAU MÜLLER\n", encoding="utf-8")
    assert len(scrub.dateien_pruefen([datei], tmp_path, scrub._regeln_lesen("müller", True, "privat"))) == 1


def test_zip_und_docx_werden_durchsucht(tmp_path):
    import zipfile

    datei = tmp_path / "bericht.docx"
    with zipfile.ZipFile(datei, "w") as z:
        z.writestr("word/document.xml", f"<w:t>{SCHLUESSEL}</w:t>")
    funde = scrub.dateien_pruefen([datei], tmp_path, _oeffentlich())
    assert any(f.ort == "bericht.docx!word/document.xml" for f in funde)


def test_utf16_ohne_bom(tmp_path):
    datei = tmp_path / "le.txt"
    datei.write_bytes(f"token = {SCHLUESSEL}\n".encode("utf-16-le"))
    assert len(scrub.dateien_pruefen([datei], tmp_path, _oeffentlich())) == 1


def test_fehlende_sperrliste_bricht_ab(monkeypatch, tmp_path):
    monkeypatch.setenv("OSS_SCRUB_SPERRLISTE", str(tmp_path / "gibt-es-nicht.txt"))
    with pytest.raises(SystemExit):
        scrub.regeln_laden()


def test_tags_werden_geprueft(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for k, v in (("user.name", "Test"), ("user.email", "test@example.org"), ("commit.gpgsign", "false"),
                 ("tag.gpgsign", "false")):
        _git(repo, "config", k, v)
    (repo / "a.txt").write_text("sauber\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "eins")
    _git(repo, "tag", "-a", "v1", "-m", f"Stand mit {SCHLUESSEL}")
    monkeypatch.chdir(repo)
    assert [f.ort for f in scrub.historie_pruefen(_oeffentlich())] == ["tags"]


def test_verlinkter_ordner_ist_nicht_geprueft(tmp_path):
    ziel = tmp_path / "ziel"
    ziel.mkdir()
    (tmp_path / "staging").mkdir()
    try:
        (tmp_path / "staging" / "link").symlink_to(ziel, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks brauchen hier Rechte")
    funde = scrub.dateien_pruefen(scrub.ordner_dateien(tmp_path / "staging"), tmp_path / "staging", _oeffentlich())
    assert [f.regel is scrub.UNGEPRUEFT for f in funde] == [True]



def _rev(cwd, *args):
    import subprocess

    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _repo_mit_autor(tmp_path, nachricht_zwei="zwei mit geheimwort"):
    """Zwei Commits mit Autor „Erika Geheimwort“; Committer bleibt „Test“, wie bei GitHub-Merges."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for k, v in (("user.name", "Test"), ("user.email", "test@example.org"), ("commit.gpgsign", "false")):
        _git(repo, "config", k, v)
    autor = "--author=Erika Geheimwort <test@example.org>"
    (repo / "a.txt").write_text("sauber\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", autor, "-m", "eins")
    erster = _rev(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-q", "--allow-empty", autor, "-m", nachricht_zwei)
    zweiter = _rev(repo, "rev-parse", "HEAD")
    return repo, erster, zweiter


def _ausnahmen(tmp_path, monkeypatch, *commits):
    datei = tmp_path / "ausnahmen.txt"
    datei.write_text("# Kommentar\n" + "".join(f"{c} autor-name  # Grund\n" for c in commits), encoding="utf-8")
    monkeypatch.setattr(scrub, "AUSNAHMEN", datei)


def test_ausnahme_nimmt_nur_den_autorennamen_aus(tmp_path, monkeypatch, capsys):
    repo, erster, zweiter = _repo_mit_autor(tmp_path)
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.chdir(repo)
    regeln = scrub._regeln_lesen("geheimwort", True, "privat")

    monkeypatch.setattr(scrub, "AUSNAHMEN", tmp_path / "gibt-es-nicht.txt")
    assert sorted((f.ort, f.zeile) for f in scrub.historie_pruefen(regeln)) == sorted(
        [(f"{erster[:12]}:kopf", 1), (f"{zweiter[:12]}:kopf", 1), (f"{zweiter[:12]}:kopf", 5)])

    _ausnahmen(tmp_path, monkeypatch, erster, zweiter)
    funde = scrub.historie_pruefen(regeln)
    # Der Name ist ausgenommen, die Nachricht des zweiten Commits bleibt ein Fund (Zeile 5 = %B).
    assert [(f.ort, f.zeile) for f in funde] == [(f"{zweiter[:12]}:kopf", 5)]
    assert f"autor-name von {erster[:12]} nicht geprüft" in capsys.readouterr().err


def test_ausnahme_fuer_einen_commit_gibt_keinen_anderen_frei(tmp_path, monkeypatch):
    repo, erster, zweiter = _repo_mit_autor(tmp_path, nachricht_zwei="zwei")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.chdir(repo)
    _ausnahmen(tmp_path, monkeypatch, erster)
    funde = scrub.historie_pruefen(scrub._regeln_lesen("geheimwort", True, "privat"))
    assert [(f.ort, f.zeile) for f in funde] == [(f"{zweiter[:12]}:kopf", 1)]


def test_ausnahme_gilt_nur_fuer_commits_auf_main(tmp_path, monkeypatch, capsys):
    repo, erster, zweiter = _repo_mit_autor(tmp_path, nachricht_zwei="zwei")
    monkeypatch.chdir(repo)
    regeln = scrub._regeln_lesen("geheimwort", True, "privat")
    _ausnahmen(tmp_path, monkeypatch, erster, zweiter)

    # Ohne origin/main gilt keine Ausnahme: beide Namen bleiben Funde.
    assert sorted(f.ort for f in scrub.historie_pruefen(regeln)) == sorted(
        [f"{erster[:12]}:kopf", f"{zweiter[:12]}:kopf"])
    assert "gilt nicht" in capsys.readouterr().err

    # origin/main auf dem ersten Commit: Der zweite (etwa ein Commit aus einem Pull Request) bleibt ein Fund.
    _git(repo, "update-ref", "refs/remotes/origin/main", erster)
    assert [f.ort for f in scrub.historie_pruefen(regeln)] == [f"{zweiter[:12]}:kopf"]


def test_ausnahme_deckt_nie_mail_oder_committer(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for k, v in (("user.name", "Test"), ("user.email", "geheimwort@example.org"), ("commit.gpgsign", "false")):
        _git(repo, "config", k, v)
    (repo / "a.txt").write_text("sauber\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "eins")
    commit = _rev(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _ausnahmen(tmp_path, monkeypatch, commit)
    monkeypatch.chdir(repo)
    funde = scrub.historie_pruefen(scrub._regeln_lesen("geheimwort", True, "privat"))
    assert [f.zeile for f in funde] == [2, 4]  # Autor-Mail und Committer-Mail


def test_unbenutzte_ausnahme_wird_gemeldet(tmp_path, monkeypatch, capsys):
    repo, _, _ = _repo_mit_autor(tmp_path, nachricht_zwei="zwei")
    monkeypatch.chdir(repo)
    _ausnahmen(tmp_path, monkeypatch, "f" * 40)
    scrub.historie_pruefen(scrub._regeln_lesen("nichts-davon", True, "privat"))
    assert f"Ausnahme für {'f' * 12} trifft keinen Commit" in capsys.readouterr().err


@pytest.mark.parametrize("zeile", ["eae8f07 autor-name", "e" * 40 + " autor-mail", "e" * 40, "E" * 40 + " autor-name",
                                   "e" * 40 + " autor-name autor-name", "e" * 64 + " autor-name"])
def test_kaputte_ausnahme_bricht_ab(tmp_path, zeile):
    datei = tmp_path / "ausnahmen.txt"
    datei.write_text(zeile + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        scrub._ausnahmen_lesen(datei)


def test_ausnahmen_im_repo_liegen_auf_main():
    ausnahmen = scrub._ausnahmen_lesen(scrub.AUSNAHMEN)  # bricht bei kaputten Zeilen ab
    assert all(felder <= set(scrub.AUSNAHME_FELDER) for felder in ausnahmen.values())
    wurzel = scrub.repo_wurzel()
    if _rev(wurzel, "rev-parse", "--is-shallow-repository") == "true":
        pytest.skip("flacher Klon")
    for commit in ausnahmen:
        _rev(wurzel, "cat-file", "-e", f"{commit}^{{commit}}")  # Commit existiert
        try:
            _rev(wurzel, "rev-parse", "--verify", "-q", scrub.AUSNAHME_BASIS)
        except Exception:
            pytest.skip(f"{scrub.AUSNAHME_BASIS} fehlt")
        _rev(wurzel, "merge-base", "--is-ancestor", commit, scrub.AUSNAHME_BASIS)


def test_committer_ausnahme_nimmt_nur_den_committer_namen_aus(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    # Wie ein Rebase-Merge über GitHub: Autor sauber, Committer mit Profilnamen.
    for k, v in (("user.name", "Erika Geheimwort"), ("user.email", "test@example.org"), ("commit.gpgsign", "false")):
        _git(repo, "config", k, v)
    (repo / "a.txt").write_text("sauber\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "--author=Test <test@example.org>", "-m", "eins")
    commit = _rev(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.chdir(repo)
    regeln = scrub._regeln_lesen("geheimwort", True, "privat")

    datei = tmp_path / "ausnahmen.txt"
    datei.write_text(f"{commit} autor-name\n", encoding="utf-8")
    monkeypatch.setattr(scrub, "AUSNAHMEN", datei)
    assert [f.zeile for f in scrub.historie_pruefen(regeln)] == [3]  # Autor-Ausnahme deckt den Committer nicht

    datei.write_text(f"{commit} committer-name\n", encoding="utf-8")
    assert scrub.historie_pruefen(regeln) == []


def test_beide_felder_fuer_einen_commit(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for k, v in (("user.name", "Erika Geheimwort"), ("user.email", "test@example.org"), ("commit.gpgsign", "false")):
        _git(repo, "config", k, v)
    (repo / "a.txt").write_text("sauber\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "eins mit geheimwort")
    commit = _rev(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    datei = tmp_path / "ausnahmen.txt"
    datei.write_text(f"{commit} autor-name\n{commit} committer-name\n", encoding="utf-8")
    monkeypatch.setattr(scrub, "AUSNAHMEN", datei)
    monkeypatch.chdir(repo)
    assert [f.zeile for f in scrub.historie_pruefen(scrub._regeln_lesen("geheimwort", True, "privat"))] == [5]
# ─── Bilder: Metadaten ja, Pixeldaten nein ──────────────────────────────────────────────────────────────────

# Ein Laufwerkspfad, zusammengesetzt, damit diese Datei selbst sauber bleibt.
PFAD = ("Ablage " + "D" + ":/" + "Projekte/geheim/bild.psd").encode()


def _png_teil(art: bytes, inhalt: bytes, crc: int | None = None) -> bytes:
    pruef = zlib.crc32(art + inhalt) if crc is None else crc
    return len(inhalt).to_bytes(4, "big") + art + inhalt + pruef.to_bytes(4, "big")


def _png(*teile: bytes, hinten: bytes = b"") -> bytes:
    kopf = _png_teil(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + kopf + b"".join(teile) + _png_teil(b"IEND", b"") + hinten


def _bloecke(daten: bytes) -> bytes:
    return b"".join(bytes([len(daten[i:i + 255])]) + daten[i:i + 255] for i in range(0, len(daten), 255)) + b"\0"


def _gif(*teile: bytes, ende: bytes = b"\x3b") -> bytes:
    return b"GIF89a" + struct.pack("<HHBBB", 1, 1, 0, 0, 0) + b"".join(teile) + ende


GIF_BILD = b"\x2c" + struct.pack("<HHHHB", 0, 0, 1, 1, 0) + b"\x02" + _bloecke(PFAD)


def _riff(art: bytes, inhalt: bytes) -> bytes:
    return art + len(inhalt).to_bytes(4, "little") + inhalt + (b"\0" if len(inhalt) & 1 else b"")


def _webp(*teile: bytes, groesse_falsch: bool = False) -> bytes:
    koerper = b"WEBP" + b"".join(teile)
    return b"RIFF" + (len(koerper) + groesse_falsch).to_bytes(4, "little") + koerper


def _funde(tmp_path, name: str, daten: bytes, max_mb: int = 50):
    datei = tmp_path / name
    datei.write_bytes(daten)
    return scrub.dateien_pruefen([datei], tmp_path, _oeffentlich(), max_mb=max_mb)


def test_bild_metadaten_werden_geprueft(tmp_path):
    xmp = b"<x:xmpmeta><rdf:Description>" + PFAD + b"</rdf:Description></x:xmpmeta>"
    magie = bytes([1]) + bytes(range(255, -1, -1)) + b"\0"  # XMP in GIF: roh, dahinter 258 Bytes Ausgleich
    bilder = {
        "text.png": _png(_png_teil(b"tEXt", b"Quelle\0" + PFAD)),
        "gepackt.png": _png(_png_teil(b"zTXt", b"Quelle\0\0" + zlib.compress(PFAD))),
        "itxt.png": _png(_png_teil(b"iTXt", b"XML:com.adobe.xmp\0\x01\0de\0\0" + zlib.compress(xmp))),
        "exif.png": _png(_png_teil(b"eXIf", b"MM\0*" + PFAD)),
        "unbekannt.png": _png(_png_teil(b"prVt", PFAD)),
        "kommentar.gif": _gif(b"\x21\xfe" + _bloecke(PFAD)),
        "xmp.gif": _gif(b"\x21\xff" + _bloecke(b"XMP DataXMP")[:-1] + xmp + magie),
        "xmp.webp": _webp(_riff(b"VP8L", b"\0" * 8), _riff(b"XMP ", xmp)),
        "exif-im-bild.webp": _webp(_riff(b"ANMF", bytes(16) + _riff(b"VP8L", b"\0") + _riff(b"EXIF", PFAD))),
    }
    for name, daten in bilder.items():
        assert [f.regel.nummer for f in _funde(tmp_path, name, daten)] != [], name


def test_pixeldaten_werden_nicht_geprueft(tmp_path):
    bilder = {
        "pixel.png": _png(_png_teil(b"PLTE", PFAD[:15]), _png_teil(b"IDAT", PFAD)),
        "pixel.gif": _gif(GIF_BILD),
        "pixel.webp": _webp(_riff(b"VP8X", bytes(10)), _riff(b"ALPH", PFAD), _riff(b"VP8L", PFAD)),
        "animiert.webp": _webp(_riff(b"ANIM", bytes(6)), _riff(b"ANMF", bytes(16) + _riff(b"VP8 ", PFAD))),
    }
    for name, daten in bilder.items():
        assert _funde(tmp_path, name, daten) == [], name


def test_unsauberes_bild_wird_ganz_geprueft(tmp_path):
    idat = _png_teil(b"IDAT", PFAD)
    bilder = {
        "hinten.png": _png(idat, hinten=b"\0"),
        "pruefsumme.png": _png(_png_teil(b"IDAT", PFAD, crc=0)),
        "ohne-ende.png": _png(idat)[:-12],
        "ohne-ende.gif": _gif(GIF_BILD, ende=b""),
        "hinten.gif": _gif(GIF_BILD, ende=b"\x3b\0"),
        "groesse.webp": _webp(_riff(b"VP8L", PFAD), groesse_falsch=True),
        "abgeschnitten.webp": _webp(_riff(b"VP8L", PFAD))[:-2],
    }
    for name, daten in bilder.items():
        funde = _funde(tmp_path, name, daten)
        assert funde and all(f.regel is not scrub.UNGEPRUEFT for f in funde), name


def test_zu_grosser_gepackter_bildtext_ist_ein_fund(tmp_path):
    bombe = _png(_png_teil(b"zTXt", b"Kommentar\0\0" + zlib.compress(b"\0" * (2 * 1024 * 1024))))
    funde = _funde(tmp_path, "bombe.png", bombe, max_mb=1)
    assert [f.regel is scrub.UNGEPRUEFT for f in funde] == [True]
    kaputt = _png(_png_teil(b"zTXt", b"Kommentar\0\0kein zlib"))
    assert [f.regel is scrub.UNGEPRUEFT for f in _funde(tmp_path, "kaputt.png", kaputt)] == [True]
    # Ein zweiter gepackter Strom hinter dem ersten bliebe ungelesen.
    zwei = _png(_png_teil(b"zTXt", b"Kommentar\0\0" + zlib.compress(b"harmlos") + zlib.compress(PFAD)))
    assert [f.regel is scrub.UNGEPRUEFT for f in _funde(tmp_path, "zwei.png", zwei)] == [True]


def test_bild_mit_zu_vielen_teilen_wird_ganz_geprueft(tmp_path):
    viele = _png(*[_png_teil(b"tEXt", b"a\0b")] * (scrub.MAX_BILD_TEILE + 1), _png_teil(b"IDAT", PFAD))
    assert _funde(tmp_path, "viele.png", viele) != []
