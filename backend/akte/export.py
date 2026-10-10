"""Obsidian-Export — die Akte als Vault: eine Markdown-Datei je Entität.

Die Datenbank bleibt die Wahrheit; der Vault ist eine Kopie zum Lesen, Suchen und
Versionieren. Jeder Faden steht als ``[[Link]]`` mit Zeitraum, Aussageart und
Quellen in der Notiz beider Enden, damit Obsidians Graph dieselbe Wand zeigt.
Je Board eine Übersichtsseite unter ``Akte/Boards/`` mit Karten, Mappen und „Liegt in“,
damit der Mappen-Baum der Wand auch im Vault durchklickbar ist.
"""

import io
import re
import zipfile

from .models import Board, Entitaet, Verbindung

_VERBOTEN = re.compile(r'[\\/:*?"<>|#^\[\]]')


def dateiname(e: Entitaet) -> str:
    return _VERBOTEN.sub("", e.name).strip() or e.slug


def board_dateiname(b: Board) -> str:
    return _VERBOTEN.sub("", b.titel).strip() or b.slug


def board_namen(boards) -> dict[int, str]:
    """Eindeutige Dateinamen je Board (gleicher Titel → Slug in Klammern), wie bei den Entitäten."""
    namen, vergeben = {}, set()
    for b in boards:
        name = board_dateiname(b)
        if name.lower() in vergeben:
            name = f"{name} ({b.slug})"
        vergeben.add(name.lower())
        namen[b.id] = name
    return namen


def _alias(titel: str) -> str:
    return titel.replace("|", "/").replace("]", ")").replace("[", "(")


def board_seite(b: Board, namen: dict[int, str], bnamen: dict[int, str] | None = None) -> str:
    """Übersicht eines Boards: Karten, Mappen (Unter-Boards) und die Boards, in denen es als Mappe liegt."""
    bnamen = bnamen or {}
    datei = lambda x: bnamen.get(x.id) or board_dateiname(x)  # noqa: E731
    zeilen = ["---", f"slug: {b.slug}", "art: board", "---", "", f"# {b.titel}", ""]
    if b.beschreibung.strip():
        zeilen += [b.beschreibung.strip(), ""]
    mappen = [m.ziel for m in b.mappen.all()]
    if mappen:
        zeilen += ["## Mappen", ""] + [f"- [[Boards/{datei(z)}|{_alias(z.titel)}]]" for z in mappen] + [""]
    eltern = [m.board for m in b.in_mappen.all()]
    if eltern:
        zeilen += ["## Liegt in", ""] + [f"- [[Boards/{datei(e)}|{_alias(e.titel)}]]" for e in eltern] + [""]
    karten = sorted((k.entitaet for k in b.karten.all()), key=lambda e: e.name.lower())
    if karten:
        zeilen += ["## Karten", ""] + [f"- [[{namen.get(e.id) or dateiname(e)}]]" for e in karten] + [""]
    return "\n".join(zeilen)


def _zeitraum(v: Verbindung) -> str:
    start = v.start.isoformat() if v.start else "?"
    if v.aktuell:
        return f"seit {start}"
    if v.ende:
        return f"{start} – {v.ende.isoformat()}"
    return start


def _yaml_text(wert: str) -> str:
    return '"' + wert.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notiz(e: Entitaet, faeden: list[Verbindung], namen: dict[int, str] | None = None) -> str:
    namen = namen or {}
    zeilen = [
        "---",
        f"typ: {e.typ}",
        f"slug: {e.slug}",
        f"status: {e.status}",
    ]
    if e.wikidata_qid:
        zeilen.append(f"wikidata: {e.wikidata_qid}")
    if e.tags:
        zeilen.append("tags: [" + ", ".join(_yaml_text(str(t)) for t in e.tags) + "]")
    if e.kurzbeschreibung:
        zeilen.append(f"beschreibung: {_yaml_text(e.kurzbeschreibung)}")
    zeilen += ["---", "", f"# {e.name}", ""]
    if e.notiz_md.strip():
        zeilen += [e.notiz_md.strip(), ""]

    if faeden:
        zeilen += ["## Verbindungen", ""]
        for v in faeden:
            anderer = v.nach if v.von_id == e.id else v.von
            richtung = "→" if v.von_id == e.id else "←"
            text = v.beschreibung or v.get_typ_display()
            zeilen.append(
                f"- {richtung} [[{namen.get(anderer.id) or dateiname(anderer)}]] · {text} · {_zeitraum(v)} · "
                f"**{v.get_aussageart_display()}**"
            )
            for beleg in v.belege.all():
                q = beleg.quelle
                ziel = q.url or q.datei_url
                marke = "★" if q.guete == "primaer" else "☆"
                zeilen.append(f"    - {marke} [{q.titel}]({ziel})" if ziel else f"    - {marke} {q.titel}")
                if beleg.zitat_woertlich:
                    zeilen.append(f"      > {beleg.zitat_woertlich}")
        zeilen.append("")
    return "\n".join(zeilen)


def vault_zip() -> bytes:
    entitaeten = list(Entitaet.objects.all())
    faeden = list(
        Verbindung.objects.select_related("von", "nach").prefetch_related("belege__quelle")
    )
    je_entitaet: dict[int, list[Verbindung]] = {}
    for v in faeden:
        je_entitaet.setdefault(v.von_id, []).append(v)
        je_entitaet.setdefault(v.nach_id, []).append(v)

    # Namen zuerst vergeben, damit Links auf umbenannte Doppelgänger stimmen.
    namen: dict[int, str] = {}
    vergeben: set[str] = set()
    for e in entitaeten:
        name = dateiname(e)
        if name.lower() in vergeben:
            name = f"{name} ({e.slug})"
        vergeben.add(name.lower())
        namen[e.id] = name

    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
        for e in entitaeten:
            ordner = e.get_typ_display().split(" ")[0]
            z.writestr(f"Akte/{ordner}/{namen[e.id]}.md", notiz(e, je_entitaet.get(e.id, []), namen))
        boards = list(Board.objects.prefetch_related("karten__entitaet", "mappen__ziel", "in_mappen__board"))
        bnamen = board_namen(boards)
        for b in boards:
            z.writestr(f"Akte/Boards/{bnamen[b.id]}.md", board_seite(b, namen, bnamen))
    return puffer.getvalue()
