# akte-mcp

MCP-Server, Python-Client und Kommandozeile für **Die Akte**, eine Ermittler-Wand mit Belegpflicht.
Lizenz: MIT (das Akte-Programm selbst steht unter AGPL-3.0).

## Was es kann

- **Ohne Token: nur lesen.** Boards, Wände, Karten und belegte Fäden einer Akte, soweit sie ohne Konto
  sichtbar sind. So kann jeder mit Claude eine öffentliche Akte befragen.
- **Mit Token: zuarbeiten.** Karten, Quellen, Fäden mit Belegen und Zeitraum, Rahmen, Fahrten und Zettel als
  **Entwurf** anlegen, Zitate an der Quelle prüfen lassen (`zitat_pruefen`: Antwort nach höchstens 30 s,
  `gefunden` / `nicht_gefunden` / `nicht_pruefbar` mit Grund), Pakete erst im Probelauf importieren.
- **Nie:** freigeben, löschen, öffentlich schalten, Einstellungen ändern. Das tut ein Mensch in der Oberfläche.

## Einrichten in Claude Code

Am einfachsten über den Starter der Akte (`AGENT-VERBINDEN`). Von Hand, eine Zeile (Windows und Mac/Linux gleich,
Python 3.12, kein Git nötig; `DEIN-TOKEN` aus `manage.py akte_token KONTO`):

```sh
claude mcp add --scope user akte -e AKTE_BASIS=http://localhost:8080 -e AKTE_TOKEN=DEIN-TOKEN -- uvx --python 3.12 --from "https://github.com/ThePyth0nKid/die-akte/archive/refs/tags/v0.2.0-rc.1.zip#subdirectory=mcp" akte-mcp
```

Ohne `AKTE_TOKEN` läuft der Server im Lesemodus.

## Kommandozeile

```sh
uv tool install --python 3.12 "https://github.com/ThePyth0nKid/die-akte/archive/refs/tags/v0.2.0-rc.1.zip#subdirectory=mcp"
export AKTE_BASIS=http://localhost:8080 AKTE_TOKEN=…
akte boards
akte import paket.json          # Probelauf
akte import paket.json --echt   # schreibt (als Entwurf)
```
