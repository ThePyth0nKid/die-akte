# Mitmachen

Danke, dass du helfen willst.

## Ablauf

1. Issue aufmachen oder ein bestehendes nehmen.
2. Branch, Änderung, Tests:
   * Backend: `cd backend && DJANGO_DEBUG=1 python manage.py test`
   * Web: `cd web && npm ci && npx tsc --noEmit && npx vitest run`
   * MCP und Beweis: `cd mcp && pytest`, `cd beweis && pytest`
   * Starter (mit Attrappen, ohne Docker): `powershell -NoProfile -ExecutionPolicy Bypass -File .github\scripts\starter-pruefen.ps1`
     unter Windows, `bash .github/scripts/starter-pruefen.sh` unter macOS und Linux. Was dabei zu beachten ist:
     [AGENTS.md](AGENTS.md), Abschnitt „Am Code der Akte arbeiten“.
3. Git-Hooks einschalten: `git config core.hooksPath .githooks` (gitleaks und Sperrliste vor jedem Commit).
4. Pull Request mit kurzer Begründung.

## Grundsätze

* **Der Mensch entscheidet.** Nichts darf einem Werkzeug oder Agenten erlauben, freizugeben, zu löschen, öffentlich
  zu schalten oder zu unterschreiben.
* **Keine echten Personen** in Tests, Beispielen und Demos. Erfundene Namen (Freie Stadt Musterhafen …).
* **Byte-Gleichheit mit Atlas** bleibt: Änderungen an `beweis/` brauchen grüne Kreuzprüfung.
* Deutsch in Code-Kommentaren und Oberfläche; Englisch in README.en.md.
* **Der Name ist „Ultra-Akte“**: in Titeln, im Logo, in der Oberfläche, in den Bannern der Starter und bei der ersten
  Nennung auf jeder Seite. Danach darf im Text „die Akte“ stehen. Befehle und technische Namen bleiben `akte`
  (Befehl, Ordner `Akte`, `START-AKTE`, MCP-Eintrag `akte`, Docker-Projekt `die-akte`), weil Daten daran hängen.

## Lizenz der Beiträge

Mit einem Beitrag stimmst du zu, dass er unter der Lizenz des jeweiligen Ordners steht (siehe `REUSE.toml`) und dass
der Betreuer ihn zusätzlich unter anderen Bedingungen nutzen darf (z. B. in eigenen Diensten). Bitte jeden Commit mit
`git commit -s` zeichnen (Developer Certificate of Origin).
