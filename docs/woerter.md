# Fachwörter, in Alltagssprache

Die Wörter, die in der Akte und in dieser Anleitung vorkommen. Kurz, ohne Technik-Deutsch.

## Auf deinem Rechner

**Terminal, PowerShell.** Ein Fenster, in das du Befehle tippst statt zu klicken. Unter Windows heißt es PowerShell
(Windows-Taste, „PowerShell“ tippen, Enter), am Mac „Terminal“. Ein Befehl steht immer in einer Zeile; Enter führt
ihn aus.

**Ordner, in dem du arbeitest.** Jedes Terminal steht in einem Ordner. `cd $HOME\Recherche` wechselt in deinen
Ordner `Recherche`. Claude Code arbeitet in dem Ordner, in dem du es startest.

**Pfad (PATH).** Die Liste der Ordner, in denen Windows nach Programmen sucht. Steht ein Programm nicht darin, meldet
PowerShell „wurde nicht als Name eines Cmdlet … erkannt“, obwohl es installiert ist. Ein neues Fenster liest die
Liste neu.

**Docker.** Ein Programm, das andere Programme abgeschottet laufen lässt, jedes in seiner eigenen kleinen Kiste. Die
Akte besteht aus drei solchen Kisten. Du installierst Docker Desktop einmal und musst danach nichts daran
einstellen.

**Container.** Eine dieser Kisten. Die Akte hat drei: `api` (die Datenbank und die Regeln), `web` (die Wand im
Browser) und `proxy` (die eine Tür nach außen, nur für deinen Rechner).

**WSL.** Ein Linux in Windows, das Docker unter Windows braucht. Windows installiert es beim ersten Start von Docker
nach; dafür kommt das schwarze Fenster, das eine Taste will.

**localhost, Port.** `localhost` ist dein eigener Rechner. `http://localhost:8080` heißt: die Akte auf deinem
Rechner, Eingang Nummer 8080. Andere Rechner kommen da nicht hin.

**uv.** Ein kleines Hilfsprogramm, das Python-Programme lädt und startet. Claude Code startet damit den
Akte-Baustein. Der Starter installiert es, wenn es fehlt.

## Claude und Agenten

**Claude Code.** Claude als Programm im Terminal. Es kann Dateien lesen, Befehle ausführen, im Netz suchen und über
Werkzeuge mit anderen Programmen arbeiten, zum Beispiel mit der Akte.

**Agent.** Eine KI, die selbst Schritte ausführt statt nur zu antworten. Claude Code ist ein Agent: Du gibst einen
Auftrag, es sucht, liest, legt an und meldet zurück.

**Werkzeug (Tool).** Eine Fähigkeit, die ein Programm einem Agenten gibt. Die Akte gibt Claude zum Beispiel
„Wand lesen“, „Karte anlegen“, „Zitat prüfen“. Ein Werkzeug zum Freigeben gibt es bewusst nicht.

**MCP.** Die gemeinsame Sprache, über die Claude Code Werkzeuge anderer Programme benutzt (Model Context Protocol).
In Claude Code zeigt `/mcp`, welche Verbindungen es gibt.

**Token.** Ein langer, geheimer Schlüssel, mit dem sich Claude bei deiner Akte ausweist. Mit Token darf Claude
Entwürfe anlegen, aber nichts freigeben. Der Starter trägt ihn ein, ohne ihn anzuzeigen. Nicht weitergeben.

**Auto-Modus.** In der Grundeinstellung fragt Claude Code nicht vor jedem Schritt nach. Was Claude in der Akte darf,
legt trotzdem die Akte fest.

## Auf der Wand

**Wand, Board.** Dasselbe: eine Ermittler-Wand zu einem Thema, etwa „Chatkontrolle“. In Adressen steht ein
Kurzname, zum Beispiel `demo-musterhafen`.

**Karte.** Eine Person, Firma, Behörde, ein Gesetz oder ein anderes Ding auf der Wand.

**Faden.** Eine Verbindung zwischen zwei Karten, zum Beispiel „lobbyiert für“ oder „beauftragt“. Ein Faden ist eine
Aussage und braucht deshalb Belege.

**Beleg.** Das, was einen Faden stützt: eine Quelle, ein wörtliches Zitat daraus und die Fundstelle.

**Quelle.** Das Dokument, aus dem ein Beleg stammt: eine Webseite, ein PDF, ein Registereintrag, eine Drucksache.
Am stärksten ist das Original (zum Beispiel das Register selbst), schwächer ein Bericht darüber.

**Zitat (wörtlich).** Ein Satz genau so, wie er in der Quelle steht. Keine Zusammenfassung, kein eigener Satz.

**Fundstelle.** Wo das Zitat in der Quelle steht: Seite, Absatz, markierter Ausschnitt.

**Aussageart.** Wie sicher ein Faden ist: *belegt* (mit Beleg), *Verdacht* (braucht Anhörung und zwei unabhängige
Quellen) oder *Meinung* (ausdrücklich als Einschätzung markiert).

**Befund.** Ein Hinweis der Prüfung, was einem Faden noch fehlt, etwa „kein Startdatum“. Manche Befunde sperren:
Dann bleibt der Faden unsichtbar, bis ein Mensch ihn mit Begründung freigibt.

**Regeln.** Wie streng die Prüfung ist. Jede Regel steht auf *aus*, *Hinweis* oder *sperrt*; einstellbar im Knopf
„Regeln“ auf der Wand.

**Entwurf.** Alles, was Claude anlegt, und alles, was nach einer Änderung noch nicht neu unterschrieben ist. Entwürfe
sieht nur die Redaktion.

**Freigabe, Unterschrift.** Ein Mensch prüft einen Entwurf und gibt ihn frei. Dabei unterschreibt sein Browser mit
einem Schlüssel, der nur in diesem Browser liegt. Leser sehen nur, was unterschrieben ist.

**Redaktion.** Die Konten, die an der Akte arbeiten dürfen. Dein erstes Konto gehört dazu.

**Einrichtungscode.** Ein Code aus acht Zeichen wie `K7QM-3XPA`, den der Starter einmal erzeugt. Damit legst du im
Browser dein erstes Konto an; der Starter trägt ihn dort selbst ein. Kein Fenster zeigt ihn an, auch ein KI-Agent
bekommt ihn so nicht zu sehen. Danach hat er keine Wirkung mehr, und der Starter löscht ihn.

## Beweise

**Beweissicherung.** Die Akte lädt jede Quelle selbst herunter und hebt eine Kopie auf, mit einer Prüfsumme
(einem Fingerabdruck der Datei). Ändert jemand die Seite später, bleibt deine Kopie.

**archive.org.** Ein öffentliches Archiv im Netz, die „Wayback Machine“. Auf Wunsch meldet die Akte dort jede
Quelle; dann gibt es eine unabhängige Kopie, und jeder kann sehen, welche Seiten gesichert wurden. Standard: aus.

**Hash-Kette.** Ein Protokoll, in dem jeder Eintrag den Fingerabdruck des vorigen trägt. Wer nachträglich etwas
ändert, bricht die Kette. Jeder kann sie prüfen, ohne dem Server zu trauen.
