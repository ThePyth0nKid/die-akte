# Sicherheit

Bitte melde Sicherheitslücken **vertraulich** über GitHub: Reiter „Security“ → „Report a vulnerability“.
Kein öffentliches Issue, keine Details in Commits.

Besonders interessiert sind wir an:

* Wegen, auf denen ein Werkzeug-Token oder ein Agent freigeben, löschen, öffentlich schalten oder unterschreiben kann,
* Fehlern in der Beweiskette (gültig trotz Manipulation, Abweichung vom Atlas-Format),
* Abrufen interner Adressen über die Beweissicherung (SSRF),
* Lecks von Privatpersonen in öffentlichen Ansichten oder im Export.

Was eine gültige Kette beweist und was nicht: [docs/sicherheit.md](docs/sicherheit.md).
