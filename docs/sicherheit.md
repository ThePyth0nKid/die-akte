# Sicherheit und Beweiskraft

Was die Akte schützt, was eine gültige Beweiskette beweist – und was nicht. Stand: Version 0.1.

## Grundannahmen

* **Lokal zuerst.** Die Akte läuft auf dem Rechner der Redaktion. Der Port ist an `127.0.0.1` gebunden; von außen ist
  sie nicht erreichbar, solange du das nicht bewusst änderst ([betrieb.md](betrieb.md)).
* **Menschen und Werkzeuge sind getrennt.** Menschen melden sich mit Passwort an (JWT im httpOnly-Cookie).
  Werkzeuge und Agenten benutzen ein Token (`manage.py akte_token`). Der Server unterscheidet beide.
* **Der Server signiert nie für einen Menschen.** Der private Schlüssel eines Menschen entsteht im Browser
  (WebCrypto, Ed25519, nicht exportierbar) und verlässt ihn nie.

## Was Leser sehen

Mitglieder und Besucher ohne Konto bekommen eine eigene Lese-Ansicht, nie die Werkstatt. Standard
(`AKTE_LESEANSICHT=nur_gepruefte`):

* nur Karten, die ein Mensch freigegeben hat und die seit der Unterschrift unverändert sind,
* nur Fäden, die die Prüfung des Boards bestehen: freigegeben, unverändert, kein sperrender Befund,
* Personen mit vollem Namen erst, wenn ein Mensch die Karte samt „öffentliche Person“ unterschrieben hat; sonst
  Initialen, ohne Kennung, die sich über Boards verknüpfen ließe,
* keine Notizen, Fragen, Fahrten, Befunde, Verfasser; Meinungs-Zettel nur von Menschen.

`alles_belegte` zeigt jeden belegten Faden, auch Entwürfe. Das ist für geschlossene Runden gedacht, nicht für die
Öffentlichkeit.

## Was Werkzeuge und Agenten nicht können

Mit einem Token (CLI, MCP-Server) lässt der Server **nicht** zu (403 bzw. 409):

* den Status setzen oder freigeben, Freigegebenes ändern oder löschen, die Quelle eines freigegebenen Fadens ändern,
* ein Board öffentlich schalten, seine Prüfregeln ändern, ein Board löschen,
* ein **veröffentlichtes** Board (öffentlich oder Mitglieder-Board) ändern: keine Karten, Zettel, Rahmen, Mappen,
  kein Ausblenden; erlaubt bleiben Anordnung und Fahrten, die Leser nicht als Inhalt sehen,
* eine Person zur öffentlichen Person machen (ein Vorschlag beim Anlegen bleibt bis zur Unterschrift verdeckt),
* Meinungs-Zettel schreiben, ändern oder löschen,
* einen Schlüssel anmelden, eine Freigabe oder einen Widerruf unterschreiben.

Der MCP-Server bietet diese Werkzeuge gar nicht erst an; die Sperre liegt trotzdem im Server, damit sie auch gilt,
wenn jemand die API direkt aufruft. Tests: `backend/akte/tests/test_menschenrecht.py`, `test_beweisschicht.py`.

## Die Beweiskette

Format: [`atlas-trace-v1`](https://github.com/ThePyth0nKid/atlas) (Prüfer unter Apache-2.0).

* Jedes Ereignis ist ein kanonisch kodiertes CBOR-Dokument (RFC 8949 § 4.2.1) mit Arbeitsbereich, Kennung,
  Zeitstempel, Schlüssel-ID, Vorgänger-Hash und Nutzlast; signiert mit **Ed25519**, adressiert über **BLAKE3**.
* Die Kette ist **linear**: genau ein Anfang, jedes Ereignis hat genau einen Vorgänger (`--require-strict-chain`).
* Das **Schlüsselbündel** (alle öffentlichen Schlüssel) ist über seinen Hash an den Trace gebunden; wer einen
  Schlüssel austauscht, bricht den Hash.
* **Rollen** stecken in der Schlüssel-ID: `akte-mensch:<fingerabdruck>`, `akte-geraet:<fingerabdruck>`,
  `akte-agent:<name>`. Freigaben, Überstimmungen und Widerrufe gelten nur mit einem Menschenschlüssel. Die IDs tragen
  keine Kontonamen: Das Schlüsselbündel ist öffentlich.
* **Nutzlast** einer Freigabe ist nur `{type, objekt, inhalt_zusage}`. Objekt-ID, Inhalt, offene Hinweise und
  Überstimmungen samt Begründung stecken in der Zusage `sha256(salz ‖ kanonisches JSON)`.
* **Offenlegung:** Der Export legt Inhalt und Salz nur für die jüngste Freigabe von Objekten offen, die öffentlich
  sichtbar sind, dazu die Sicherungen ihrer Quellen – nie für Inhalte mit dem vollen Namen einer Privatperson.
  Begründungen von Überstimmungen werden dabei veröffentlicht; die Oberfläche sagt das vor jeder Unterschrift.
* **Widerruf** ist ein signiertes Ereignis (`akte.widerruf`, Knopf „Regeln“ → „Deine Schlüssel“). Jedes spätere
  Ereignis eines widerrufenen Schlüssels ist für jeden Prüfer ungültig, gemessen an der Abstammung in der Kette.
* **Schwärzen** (`manage.py akte_schwaerzen`) löscht Salz und Inhalt eines Ereignisses, etwa nach einer
  Unterlassungsverfügung. Die Kette bleibt gültig, der Export nennt das Ereignis unter `geschwaerzt`, und das Objekt
  verschwindet aus der Lese-Ansicht, bis ein Mensch neu unterschreibt.

### Eine gültige Kette beweist

* **Unverändertheit:** Kein Ereignis, kein offengelegter Inhalt und kein Schlüssel wurde nachträglich verändert,
  eingefügt, umsortiert oder entfernt (innerhalb des exportierten Traces).
* **Urheberschaft:** Jede Freigabe stammt von dem Schlüssel, dessen ID sie trägt, und dieser ist ein Menschenschlüssel.
* **Bezug:** Die Freigabe eines Fadens deckt genau diesen Inhalt – Enden, Aussage, Konfidenz, Zeitraum, Anhörung,
  Belege mit Zitat, Quellen mit Datum, Archiv und Güte sowie der SHA-256 der gesicherten Originale. Ändert sich
  etwas, auch an einer Karte oder Quelle, ist der Faden wieder Entwurf bzw. „verändert seit Freigabe“ und für Leser
  unsichtbar, bis ein Mensch neu unterschreibt. Die Akte vergleicht das bei jedem Lesen, nicht nur beim Speichern.

### Sie beweist nicht

* **Wahrheit.** Eine Unterschrift sagt, wer wann was freigegeben hat, nicht, dass es stimmt.
* **Identität hinter einem Schlüssel.** `akte-mensch:<fingerabdruck>` sagt nur, dass ein Mensch dieser Instanz
  unterschrieben hat. Wer prüfen will, wer das ist, braucht den Fingerabdruck auf einem zweiten Weg (z. B.
  veröffentlicht im Impressum).
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
  (`AKTE_CLIENT_IP_HEADER`, `AKTE_VERTRAUTE_PROXYS`). Die Anmeldung bremst Fehlversuche je Konto.
* **Sitzungen:** Refresh-Tokens rotieren; ein benutzter oder abgemeldeter Token steht auf einer Sperrliste.
  Ändernde Anfragen an die Oberfläche müssen aus ihr selbst kommen (`Sec-Fetch-Site`/`Origin`), dazu
  `SameSite=Lax`-Cookies, `frame-ancestors 'none'`, `nosniff`. Die Django-Verwaltung ist über den Eingang nicht
  erreichbar.
* **archive.org** bekommt keine Adressen mit Zugangsdaten und nichts aus dem eigenen Netz; ganz aus mit
  `AKTE_ARCHIV_AKTIV=false`.
* **Beweis-Speicher:** Kopien werden vollständig geschrieben und erst dann sichtbar; beim Lesen wird die Prüfsumme
  verglichen, eine veränderte Kopie wird nie ausgeliefert.
* **Privatpersonen:** öffentlich nur mit Initialen, ohne Kennung, die sich über Boards verknüpfen ließe; Verdacht und
  Familie über sie sperren von Haus aus.
* **Geräteschlüssel:** Datei mit Rechten 600 im Datenordner, nie in der Datenbank, nie im Export. Er unterschreibt
  nur, was der Server selbst gesehen hat; ein lokal gemeldetes Video (Prüfsumme vom Helfer) unterschreibt er nicht.
* **Kein Geheimnis im Repo:** gitleaks und eine Sperrliste prüfen jeden Commit (`werkzeuge/scrub/`, `.githooks/`).

## Bekannte Grenzen von 0.1

* Der Browser bestätigt die Freigabe mit einer Zusammenfassung, rechnet die zu signierenden Bytes aber nicht selbst
  nach; er vertraut darin dem eigenen, lokalen Server. Weil die Nutzlast nur die Zusage trägt und das Salz erst mit
  der Offenlegung kommt, kann er auch nicht prüfen, dass die Zusage genau den angezeigten Inhalt bindet. Ein
  manipulierter Server könnte also etwas anderes unterschreiben lassen; spätestens die Offenlegung im Export würde
  dann nicht zum gezeigten Stand passen. Nachrechnen im Browser (kanonisches JSON, Zusage, Signing-Input) ist für
  eine spätere Version vorgesehen.
* Wer Zugang zur Datenbank oder zur Django-Verwaltung hat, kann einen Status ohne Unterschrift auf „freigegeben“
  setzen. Die Lese-Ansicht zeigt solche Objekte (es gibt keine Unterschrift, mit der sie nicht übereinstimmen), die
  Kette enthält für sie aber keine Freigabe. Werkzeuge und Agenten können das nicht.
* Ein verlorener Browser-Schlüssel lässt sich nur mit einem anderen eigenen Schlüssel widerrufen; der Browser legt
  dafür bei der nächsten Anmeldung einen neuen an.
* Der Atlas-Prüfer im Browser kennt nur den nachsichtigen Modus; die strikte Kette prüft `akte pruefe-signaturen`.

## Sicherheitslücken melden

Bitte vertraulich über „Security → Report a vulnerability“ auf GitHub, nicht als öffentliches Issue.
