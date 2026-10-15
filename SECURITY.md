# Sicherheit

Bitte melde Sicherheitslücken **vertraulich** über GitHub: Reiter „Security“ → „Report a vulnerability“.
Kein öffentliches Issue, keine Details in Commits.

Besonders interessiert sind wir an:

* Wegen, auf denen ein Werkzeug-Token oder ein Agent freigeben, löschen, öffentlich schalten oder unterschreiben kann,
* Fehlern in der Beweiskette (gültig trotz Manipulation, Abweichung vom Atlas-Format),
* Wegen, das erste Konto ohne den Einrichtungscode anzulegen oder nach der Einrichtung ein weiteres Konto über
  `/akte/einrichten` zu erzeugen,
* Stellen, an denen die Starter (`start/`) einen Token, den Einrichtungscode oder ein Passwort ausgeben oder in
  Dateien außerhalb von `.env` und der Claude-Einstellung schreiben,
* Abrufen interner Adressen über die Beweissicherung (SSRF),
* Lecks von Privatpersonen in öffentlichen Ansichten oder im Export.

Was eine gültige Kette beweist und was nicht: [docs/sicherheit.md](docs/sicherheit.md).
