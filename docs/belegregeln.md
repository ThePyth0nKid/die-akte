# Belegregeln und Prüfung

Die Prüfung **berät**, der Mensch **entscheidet**. Jede Regel ist einzeln einstellbar:

| Stufe | Wirkung |
|---|---|
| `aus` | wird nicht geprüft |
| `hinweis` | erscheint als Befund, hält nichts auf |
| `sperrt` | hält einen Faden aus der öffentlichen Ansicht, bis ein Mensch ihn mit Begründung überstimmt |

## Regeln

| Code | Prüft | Standard |
|---|---|---|
| `ohne_quelle` | Faden ohne Beleg | hinweis |
| `quelle_ohne_adresse` | Quelle ohne Link und ohne Datei | hinweis |
| `quelle_ohne_abruf` | Quelle ohne Abrufdatum | hinweis |
| `quelle_ohne_archiv` | Quelle ohne Archivkopie | hinweis |
| `verdacht_ohne_anhoerung` | Verdacht gegen eine Person ohne Anhörung | hinweis |
| `verdacht_zu_duenn` | Verdacht mit weniger als zwei unabhängigen Quellen | hinweis |
| `ohne_start` | Faden ohne Startdatum | hinweis |
| `zeitraum_widerspruch` | „Aktuell“ und Enddatum zugleich | hinweis |
| `zeitraum_offen` | weder „aktuell“ noch Enddatum | hinweis |
| `zeitraum_verkehrt` | Ende vor dem Start | hinweis |
| `verdacht_privatperson` | Verdacht gegen eine Privatperson | **sperrt** |
| `familie_privatperson` | Familienbande einer Privatperson | **sperrt** |

Dazu kommen **Zustandsregeln**, die immer sperren und sich nicht überstimmen lassen, weil sie beschreiben, ob ein
Mensch unterschrieben hat: `faden_nicht_freigegeben`, `karte_nicht_freigegeben`, `veraendert_seit_freigabe`.

## Einstellen

Für alle Boards in `.env` (JSON):

```
AKTE_REGELN={"quelle_ohne_archiv": "sperrt", "zeitraum_offen": "aus"}
```

Für ein Board über die API (nur ein Mensch, kein Token; ein Schalter in der Oberfläche folgt):

```
PATCH /api/v1/akte/boards/<slug>/   {"regeln": {"ohne_quelle": "sperrt"}}
```

Die spätere Ebene gewinnt: Standard → `AKTE_REGELN` → Board. `GET /api/v1/akte/boards/<slug>/pruefung/` zeigt die
gültigen Stufen und alle Befunde.

## Überstimmen

Beim Freigeben eines Fadens fragt die Akte für jeden sperrenden Befund nach einer Begründung. Die Begründung wird
Teil der Unterschrift (als Zusage in der Kette, offengelegt mit dem Faden). Ändert sich der Faden, verfallen die
Überstimmungen mit der Freigabe.

## Leitplanken für Recherche (Empfehlung)

* Kein Faden ohne Quelle; `zitat_woertlich` ist nur der Originalwortlaut, nie eine Zusammenfassung.
* Erwähnt ≠ Kontakt ≠ schuldig. Vorwürfe nur mit Gericht, Behörde oder Vergleich als Quelle.
* Verfahrensstand statt Absicht: beantragt ≠ genehmigt, Entwurf ≠ Gesetz, Festnahme ≠ Anklage.
* Keine Charakterwörter; Meinung als Meinung kennzeichnen (Zettel „Meinung“, Aussageart `meinung`).
* Privatpersonen nie mit Verdacht oder Familie verbinden; öffentlich nur Initialen.

Das ersetzt keine anwaltliche Prüfung.
