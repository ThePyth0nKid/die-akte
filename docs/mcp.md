# Die Akte mit Claude Code (MCP)

`akte-mcp` verbindet Claude Code (oder jeden anderen MCP-Client) mit deiner Akte.

## Einrichten

```sh
docker compose exec api python manage.py akte_token <dein-konto>
claude mcp add akte -e AKTE_BASIS=http://localhost:8080 -e AKTE_TOKEN=<token> \
  -- uvx --from "git+https://github.com/ThePyth0nKid/die-akte@v0.1.0#subdirectory=mcp" akte-mcp
```

Ohne `AKTE_TOKEN` startet der Server im **Lesemodus**: nur Boards, die ohne Konto sichtbar sind.

## Werkzeuge

| Werkzeug | Modus | Zweck |
|---|---|---|
| `boards_liste` | beide | Boards mit Mappen-Baum |
| `wand_lesen` | beide | Karten, Fäden mit Belegen und Befunden, Rahmen, Zettel, Fahrten |
| `suche` | beide | Karten nach Name oder Beschreibung |
| `weg` | beide | kürzester Weg über Fäden zwischen zwei Karten |
| `pruefung` | Token | offene Befunde je Faden |
| `quelle_anlegen` | Token | Quelle (stößt die Beweissicherung an) |
| `karte_anlegen` | Token | Karte als Entwurf, optional auf ein Board |
| `faden_ziehen` | Token | Faden mit Belegen als Entwurf; gibt Befunde zurück |
| `beleg_hinzufuegen` | Token | weiterer Beleg an einem Faden |
| `zitat_pruefen` | Token | steht das Zitat wörtlich in der Quelle? |
| `gruppen_setzen`, `aufraeumen` | Token | Themen-Rahmen, Wand ordnen |
| `fahrt_anlegen` | Token | Kamerafahrt für ein Video |
| `zettel_anlegen` | Token | Notiz oder Frage (Meinungs-Zettel schreibt nur ein Mensch) |
| `import_paket` | Token | viele Einträge auf einmal; Probelauf zuerst, schreiben nur mit Bestätigung |
| `sichern` | Token | Beweissicherung neu anstoßen |

Es gibt **kein** Werkzeug zum Freigeben, Löschen oder Öffentlich-Schalten – und der Server lehnt es für Tokens ab.
Die Ressource `akte://regeln` enthält die Belegregeln in Kurzform.

## Gute Arbeitsweise

1. Erst lesen (`boards_liste`, `wand_lesen`, `suche`).
2. Quellen anlegen, dann Fäden mit Belegen (Zitat = Originalwortlaut).
3. `zitat_pruefen` für jeden Beleg mit Zitat.
4. `pruefung` und offene Befunde der Redaktion melden, nicht wegdiskutieren.
5. Freigeben tut ein Mensch in der Oberfläche – mit seiner Unterschrift.

Für größere Recherchen empfiehlt sich das Verfahren aus dem Plugin `recherche` (Recherche-Agenten, unabhängiger
Faktenprüfer vor dem Import, Entscheidungstabelle für den Menschen).
