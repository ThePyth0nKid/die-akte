# akte-mcp

MCP-Server, Python-Client und Kommandozeile für **Die Akte**, eine Ermittler-Wand mit Belegpflicht.
Lizenz: MIT (das Akte-Programm selbst steht unter AGPL-3.0).

## Was es kann

- **Ohne Token: nur lesen.** Boards, Wände, Karten und belegte Fäden einer Akte, soweit sie ohne Konto
  sichtbar sind. So kann jeder mit Claude eine öffentliche Akte befragen.
- **Mit Token: zuarbeiten.** Karten, Quellen, Fäden mit Belegen, Rahmen, Fahrten und Zettel als **Entwurf**
  anlegen, Zitate an der Quelle prüfen lassen, Pakete erst im Probelauf importieren.
- **Nie:** freigeben, löschen, öffentlich schalten. Das tut ein Mensch in der Oberfläche der Akte.

## Einrichten in Claude Code

```sh
claude mcp add akte \
  -e AKTE_BASIS=http://localhost:8080 \
  -e AKTE_TOKEN=<token aus: manage.py akte_token <konto>> \
  -- uvx --from "git+https://github.com/ThePyth0nKid/die-akte@v0.1.0#subdirectory=mcp" akte-mcp
```

Ohne `AKTE_TOKEN` läuft der Server im Lesemodus.

## Kommandozeile

```sh
uv tool install "git+https://github.com/ThePyth0nKid/die-akte@v0.1.0#subdirectory=mcp"
export AKTE_BASIS=http://localhost:8080 AKTE_TOKEN=…
akte boards
akte import paket.json          # Probelauf
akte import paket.json --echt   # schreibt (als Entwurf)
```
