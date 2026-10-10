---
name: akte-fuehren
description: 'An einer Akte (Ermittler-Wand mit Belegpflicht) arbeiten: Karten für Personen, Firmen, Behörden, Gesetze anlegen, belegte Fäden mit Quelle und wörtlichem Zitat ziehen, Zitate an der Quelle prüfen lassen, Themen-Rahmen setzen, Kamerafahrten für Videos bauen und offene Befunde melden. Nutze diesen Skill bei „Akte“, „Wand“, „Board“, „Ermittler-Board“, „Faden ziehen“, „Verbindung belegen“, „Fahrt für Kapitel“, und immer, wenn die MCP-Werkzeuge von akte-mcp im Spiel sind. Freigeben tut immer ein Mensch.'
---

# An der Akte arbeiten

Die Akte ist eine Ermittler-Wand: Karten (Personen, Firmen, Behörden, Gesetze …), Fäden zwischen ihnen und zu jedem
Faden Belege – Quelle, wörtliches Zitat, Fundstelle. Du arbeitest über den MCP-Server `akte-mcp` (oder die CLI
`akte`). Alles, was du anlegst, ist ein **Entwurf**. Freigeben, Löschen und Öffentlich-Schalten kannst du nicht; das
tut ein Mensch in der Oberfläche mit seiner Unterschrift.

## 1. Harte Grenzen

1. **Kein Faden ohne Quelle.** Ein belegter Faden trägt mindestens einen Beleg.
2. **`zitat_woertlich` ist nur Originalwortlaut der Quelle** – nie eine Zusammenfassung, nie ein eigener Satz, nie
   ein Satz aus einem Skript. Fehlt der Wortlaut: Zitat leer lassen und in `fundstelle` sagen, warum.
3. **Aussageart ehrlich:** `belegt` nur mit Beleg; `verdacht` gegen Personen braucht Anhörung und zwei unabhängige
   Quellen; `meinung` nur, wenn die Redaktion es als ihre Einschätzung markiert hat.
4. **Verfahrensstand statt Absicht:** beantragt ≠ genehmigt, Entwurf ≠ Gesetz, Festnahme ≠ Anklage,
   erwähnt ≠ Kontakt ≠ schuldig. Keine Charakterwörter.
5. **Privatpersonen** (`oeffentliche_person = false`) nie mit Verdacht oder Familie verbinden; öffentlich erscheinen
   sie nur mit Initialen.
6. **Befunde melden, nicht wegreden.** Die Prüfung berät, der Mensch entscheidet.

## 2. Ablauf für ein Thema

1. **Bestand lesen:** `boards_liste`, `wand_lesen <board>`, `suche`. Nichts doppelt anlegen.
2. **Quellen zuerst:** `quelle_anlegen` mit Titel, URL, Herausgeber, Güte (`primaer` = Originaldokument, Gericht,
   Behörde, Register; `sekundaer` = Bericht darüber) und `abgerufen_am`. Die Akte sichert das Original mit Prüfsumme.
3. **Karten:** `karte_anlegen` mit Typ und – bei Personen – ausdrücklich `oeffentliche_person`.
4. **Fäden:** `faden_ziehen` mit kurzer Beschreibung (2–6 Wörter), Startdatum, `aktuell` oder Ende und Belegen
   `[{quelle, zitat_woertlich, fundstelle}]`. Die Antwort enthält offene Befunde.
5. **Zitate prüfen:** `zitat_pruefen` für jeden Beleg mit Zitat. „nicht gefunden“ heißt: Wortlaut abweichend,
   falsche Quelle oder die Quelle ist eine Webseite ohne Browser-Sicherung – der Redaktion melden.
6. **Ordnen:** `gruppen_setzen {Titel: [Kartennamen]}` (mit `farbe: "#RRGGBB"` wird ein Rahmen zum Schild), dann
   `aufraeumen`.
7. **Prüfen:** `pruefung <board>` und die offenen Befunde in einer Liste an die Redaktion.
8. **Größere Mengen:** `import_paket` – immer erst mit `dry_run: true`, Ergebnis zeigen, dann mit
   `dry_run: false, bestaetigt: true`.

## 3. Kamerafahrten für Videos

Eine Fahrt ist eine Folge von Stationen: `fokus` (Kartennamen; leer = ganze Wand), `stichwort`, optional `dauer_ms`,
`zoom`, `text` (Sprechtext), `beweis` (Quellentitel) und `zitat` (genau der Wortlaut eines Belegs dieser Quelle).
Eine Station je Gedanke des Skripts. `fahrt_anlegen` ersetzt eine Fahrt mit gleichem Titel. Gerendert wird lokal
(`render/aufnahme.py`).

## 4. Fallen

1. **Skriptsatz als Zitat.** Der häufigste Fehler: ein eigener oder zusammengefasster Satz landet in
   `zitat_woertlich`. Nur Zeilen, die wörtlich in der Quelle stehen.
2. **Auslassungen „[…]“** verbinden oft Stellen auf zwei Seiten. Lieber zwei kurze Belege als ein langes Zitat mit
   Lücken; jedes Stück mindestens etwa 25 Zeichen.
3. **Zahlen aus Zweitquellen.** Beträge und Daten möglichst aus dem Originaldokument (Drucksache, Register, Urteil).
4. **Namensgleichheit.** Vor dem Anlegen suchen; bei Personen eine eindeutige Kurzbeschreibung (Rolle, Ort, Jahr).
5. **Archiv drosselt.** Fehlt eine Archivkopie, erst später `sichern` – nicht die Regel abschalten.
6. **„Erwähnt“ ist kein Faden.** Dass zwei Namen im selben Dokument stehen, belegt keine Verbindung.
7. **Fotos nur mit Lizenz.** Bild-URL und Nachweis (Urheber, Lizenz) gehören zusammen; sonst kein Bild.
8. **Nie freigeben wollen.** Wenn etwas „fertig“ ist, sagst du es der Redaktion; die unterschreibt.

Mehr: `docs/belegregeln.md` (Regeln und Stufen), `docs/mcp.md` (Werkzeuge), `docs/sicherheit.md` (Beweiskette).
