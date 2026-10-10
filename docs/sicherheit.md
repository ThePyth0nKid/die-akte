# Sicherheit und Beweiskraft

Was die Akte schützt, was eine gültige Beweiskette beweist – und was nicht. Stand: Version 0.1.

## Grundannahmen

* **Lokal zuerst.** Die Akte läuft auf dem Rechner der Redaktion. Der Port ist an `127.0.0.1` gebunden; von außen ist
  sie nicht erreichbar, solange du das nicht bewusst änderst ([betrieb.md](betrieb.md)).
* **Menschen und Werkzeuge sind getrennt.** Menschen melden sich mit Passwort an (JWT im httpOnly-Cookie).
  Werkzeuge und Agenten benutzen ein Token (`manage.py akte_token`). Der Server unterscheidet beide.
* **Der Server signiert nie für einen Menschen.** Der private Schlüssel eines Menschen entsteht im Browser
  (WebCrypto, Ed25519, nicht exportierbar) und verlässt ihn nie.

## Was Werkzeuge und Agenten nicht können

Mit einem Token (CLI, MCP-Server) lässt der Server **nicht** zu (403 bzw. 409):

* den Status setzen oder freigeben, Freigegebenes ändern oder löschen,
* ein Board öffentlich schalten oder seine Prüfregeln ändern,
* einen Schlüssel anmelden oder eine Freigabe unterschreiben.

Der MCP-Server bietet diese Werkzeuge gar nicht erst an; die Sperre liegt trotzdem im Server, damit sie auch gilt,
wenn jemand die API direkt aufruft. Tests: `backend/akte/tests/test_menschenrecht.py`, `test_beweisschicht.py`.

## Die Beweiskette

Format: [`atlas-trace-v1`](https://github.com/ThePyth0nKid/atlas) (Prüfer unter Apache-2.0).

* Jedes Ereignis ist ein kanonisch kodiertes CBOR-Dokument (RFC 8949 § 4.2.1) mit Arbeitsbereich, Kennung,
  Zeitstempel, Schlüssel-ID, Vorgänger-Hash und Nutzlast; signiert mit **Ed25519**, adressiert über **BLAKE3**.
* Die Kette ist **linear**: genau ein Anfang, jedes Ereignis hat genau einen Vorgänger (`--require-strict-chain`).
* Das **Schlüsselbündel** (alle öffentlichen Schlüssel) ist über seinen Hash an den Trace gebunden; wer einen
  Schlüssel austauscht, bricht den Hash.
* **Rollen** stecken in der Schlüssel-ID: `akte-mensch:<konto>#<fingerabdruck>`, `akte-geraet:<instanz>`,
  `akte-agent:<name>`. Freigaben, Überstimmungen und Widerrufe gelten nur mit einem Menschenschlüssel.
* **Inhalte** stehen als Zusage `sha256(salz ‖ kanonisches JSON)` in der Kette. Der Export legt Inhalt und Salz nur
  für Objekte offen, die öffentlich sichtbar sind – und nie für Inhalte mit dem vollen Namen einer Privatperson.

### Eine gültige Kette beweist

* **Unverändertheit:** Kein Ereignis, kein offengelegter Inhalt und kein Schlüssel wurde nachträglich verändert,
  eingefügt, umsortiert oder entfernt (innerhalb des exportierten Traces).
* **Urheberschaft:** Jede Freigabe stammt von dem Schlüssel, dessen ID sie trägt, und dieser ist ein Menschenschlüssel.
* **Bezug:** Die Freigabe eines Fadens deckt genau diesen Inhalt – Enden, Aussage, Zeitraum, Belege mit Zitat und
  der SHA-256 der gesicherten Originale. Ändert sich etwas, meldet die Akte „verändert seit Freigabe“.

### Sie beweist nicht

* **Wahrheit.** Eine Unterschrift sagt, wer wann was freigegeben hat, nicht, dass es stimmt.
* **Identität hinter einem Schlüssel.** `akte-mensch:anna#…` ist ein Kontoname auf *dieser* Instanz. Wer prüfen will,
  wer das ist, braucht den Fingerabdruck auf einem zweiten Weg (z. B. veröffentlicht im Impressum).
* **Zeitpunkt gegenüber Dritten.** Die Zeitstempel setzt der Server. Gegen einen Betreiber, der rückdatiert, hilft nur
  eine Verankerung bei einer unabhängigen Stelle (Sigstore Rekor, RFC-3161-Zeitstempel). Das ist **geplant** und noch
  nicht Teil von 0.1.
* **Vollständigkeit über den Export hinaus.** Wer einen älteren Export zurückhält und einen neueren zeigt, fällt nur
  auf, wenn jemand beide vergleicht (gleiche Anfänge, neuere Kette verlängert die ältere) – oder mit Verankerung.

## Weitere Schutzmaßnahmen

* **Abruf fremder Seiten (SSRF):** Die Beweissicherung lädt nur `http(s)` auf Port 80/443, prüft jede aufgelöste
  Adresse und jede Weiterleitung gegen private, lokale und reservierte Netze und begrenzt Größe und Zeit
  (`backend/akte/abruf.py`, Tests in `test_sicherung.py`).
* **Drossel ohne Konto:** zählt die Verbindungsadresse; Proxy-Köpfen wird nur nach Einstellung geglaubt
  (`AKTE_CLIENT_IP_HEADER`, `AKTE_VERTRAUTE_PROXYS`).
* **Privatpersonen:** öffentlich nur mit Initialen, ohne Kennung, die sich über Boards verknüpfen ließe; Verdacht und
  Familie über sie sperren von Haus aus.
* **Geräteschlüssel:** Datei mit Rechten 600 im Datenordner, nie in der Datenbank, nie im Export.
* **Kein Geheimnis im Repo:** gitleaks und eine Sperrliste prüfen jeden Commit (`werkzeuge/scrub/`, `.githooks/`).

## Bekannte Grenzen von 0.1

* Ein Schlüssel-Widerruf wird bisher nur in der Datenbank vermerkt; als Ereignis in der Kette (prüfbar für Dritte)
  ist er in `akte-beweis` vorgesehen, in der Oberfläche noch nicht.
* Der Browser bestätigt die Freigabe mit einer Zusammenfassung, rechnet die zu signierenden Bytes aber nicht selbst
  nach; er vertraut darin dem eigenen, lokalen Server.
* Der Atlas-Prüfer im Browser kennt nur den nachsichtigen Modus; die strikte Kette prüft `akte pruefe-signaturen`.

## Sicherheitslücken melden

Bitte vertraulich über „Security → Report a vulnerability“ auf GitHub, nicht als öffentliches Issue.
