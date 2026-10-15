# Betrieb

Standard ist **lokal auf einem Rechner** (`compose.yaml`, Port nur an `127.0.0.1`). Dieses Kapitel beschreibt die
Starter, die Einstellungen, Sichern und neue Versionen, und was du brauchst, wenn du mehr willst: Seitenbilder von
Webseiten, Postgres, Zugriff für ein Team. Befehle stehen zuerst für Windows (PowerShell), dann für macOS und Linux.

## Die Starter

Alle Starter liegen im Ordner `start`. Unter Windows steckt die Arbeit in `akte.ps1`; die `.cmd`-Dateien rufen ihn
nur auf. Unter macOS und Linux ist es `akte.sh`.

| Was | Windows (Doppelklick) | Windows (PowerShell, im Akte-Ordner) | macOS, Linux |
|---|---|---|---|
| Starten | `START-AKTE` | `powershell -NoProfile -ExecutionPolicy Bypass -File start\akte.ps1 start` | `bash start/akte.sh start` |
| Anhalten | `STOP-AKTE` | `powershell -NoProfile -ExecutionPolicy Bypass -File start\akte.ps1 stop` | `bash start/akte.sh stop` |
| Zustand | – | `powershell -NoProfile -ExecutionPolicy Bypass -File start\akte.ps1 status` | `bash start/akte.sh status` |
| Claude verbinden | `AGENT-VERBINDEN` | `powershell -NoProfile -ExecutionPolicy Bypass -File start\akte.ps1 agent` | `bash start/akte.sh agent` |
| Demo laden | – | `powershell -NoProfile -ExecutionPolicy Bypass -File start\akte.ps1 demo` | `bash start/akte.sh demo` |

`-ExecutionPolicy Bypass` ist nötig, weil Windows `.ps1`-Dateien sonst nicht ausführt. Schalter: `-Still` (keine
Rückfragen, kein Warten auf Enter; für Agenten), `-Json` (bei `status`: eine Zeile JSON), `-Konto NAME` (bei
`agent`), `-OhneBrowser`. Unter macOS und Linux heißen sie `--still`, `--json`, `--konto NAME`, `--ohne-browser`.

Was `start` tut: prüfen, ob der Ordner entpackt ist; Docker finden und Docker Desktop starten, falls nötig (bis zu
3 Minuten warten); `.env` anlegen mit geheimem Schlüssel und, nur für eine Akte ohne Daten-Volume, einem
Einrichtungscode; die Rechte von `.env` auf dein Konto beschränken; einen freien Port suchen, falls 8080 belegt ist
(er landet als `AKTE_PORT` in `.env`); `docker compose up -d --build --wait`; den Browser öffnen, solange das erste
Konto fehlt auf `/akte/einrichten#code=…` (Code schon eingetragen), sonst auf `/akte`. Steht das erste Konto, löscht
`start` (wie `agent`) den Einrichtungscode aus `.env`. Die Rückgabewerte stehen im
[README](../README.md#wenn-etwas-schiefgeht).

Der Einrichtungscode steht in keiner Konsole, auch nicht im Fenster nach einem Doppelklick auf `START-AKTE` (bzw.
`start-akte.command`); der Doppelklick öffnet den Browser genauso mit `#code=…`. Geht kein Browser auf, nennt der
Starter den Notweg `akte_einrichten` (siehe unten), der keinen Code braucht. `-Fenster` aus den `.cmd`-Dateien lässt
das Fenster am Ende nur dann auf Enter warten, wenn Ein- und Ausgabe ein echtes Konsolenfenster sind.

`status -Json` liefert genau diese Felder (bei einem unerwarteten Fehler stattdessen `{"fehler": "…"}` mit
Rückgabewert 1):

```
{"docker":"fehlt|aus|laeuft","akte":"aus|laeuft","url":"…","einrichtung_offen":true,"einrichtung_grund":"offen","agent_verbunden":false}
```

`einrichtung_grund` ist `offen`, `kein_code` (kein Konto, aber auch kein Code: Notweg `akte_einrichten`),
`eingerichtet` oder `null` (Akte läuft nicht).

Umgebungsvariablen für Sonderfälle: `AKTE_PORT` (gewinnt wie bei `docker compose` über `.env`), `AKTE_DOCKER` (Pfad
zu `docker`), `AKTE_DOCKER_WARTEN` (Sekunden, Standard 180), `AKTE_MCP_QUELLE` (eigene Quelle für den
Akte-Baustein statt der Release-ZIP, z. B. ein Ordner `mcp` auf deinem Rechner), `AKTE_OHNE_BROWSER=1`,
`AKTE_PFAD_NICHT_AENDERN=1` (Windows: Benutzer-Pfad nicht anfassen). Nur für die Prüfskripte: `AKTE_BROWSER`
(Programm statt des Standard-Browsers) wirkt nur zusammen mit `AKTE_STARTER_TEST=1`. Die Starter prüft die CI mit
Attrappen: `.github/scripts/starter-pruefen.ps1` und `.github/scripts/starter-pruefen.sh`; den Host-Filter prüft sie
gegen die echte, in der CI gestartete Akte (`.github/scripts/hostfilter-pruefen.sh`).

## Das erste Konto

Beim allerersten Start (es gibt noch kein Daten-Volume `die-akte_akte-daten`) erzeugt der Starter den
**Einrichtungscode** (`AKTE_EINRICHTUNGSCODE` in `.env`, 8 Zeichen ohne Verwechsler wie 0/O und 1/I) und öffnet den
Browser auf `/akte/einrichten`, den Code im Fragment der Adresse (`#code=…`). Die Seite trägt ihn ins Feld ein und
löscht ihn aus der Adresszeile. Solange es kein aktives Konto der Redaktion (oder einen Superuser) gibt, legt man
dort das erste Konto an, samt der Entscheidung über archive.org. Danach ist der Code wirkungslos, und der Starter
löscht ihn beim nächsten `start` oder `agent` aus `.env`. Der laufende Container kennt ihn trotzdem weiter, bis er
neu erstellt wird: Das tut `START-AKTE` bzw. `docker compose up -d` nach einer Änderung an `.env`, ein Neustart von
PC oder Docker dagegen nicht. Eine Akte, die schon Daten hat, bekommt keinen neuen Code, auch nicht nach einer neuen
Version. Ein leerer Code schaltet diesen Weg ab. Eine Ablaufzeit hat der Code bewusst nicht.

Notweg im Terminal, ohne Browser und ohne Code, etwa wenn kein Browser aufgeht oder die Seite „kein
Einrichtungscode“ meldet. Das Programm fragt nach Benutzername und Passwort; das Passwort bleibt beim Tippen
unsichtbar:

```
docker compose exec api python manage.py akte_einrichten
```

## Einstellungen (`.env`)

| Variable | Bedeutung |
|---|---|
| `DJANGO_SECRET_KEY` | Pflicht, langer Zufallswert (der Starter legt ihn an) |
| `AKTE_EINRICHTUNGSCODE` | Code für das erste Konto im Browser (der Starter legt ihn nur für eine neue Akte an und löscht ihn nach der Einrichtung; leer = aus) |
| `AKTE_PORT`, `AKTE_TITEL` | Port auf deinem Rechner, Titel im Browser |
| `AKTE_HOSTS` | Namen, unter denen die Akte antwortet, durch Leerzeichen getrennt (Standard `localhost 127.0.0.1 ::1 [::1]`); andere bekommen 421. Eigene Domain, IP-Adresse oder Rechnername hier eintragen |
| `DJANGO_ALLOWED_HOSTS` | dieselben Namen für Django, durch Komma getrennt (Standard `localhost,127.0.0.1,[::1]`; `api` setzt `compose.yaml` immer dazu) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Adressen mit `http://` bzw. `https://` und Port, von denen aus man sich anmeldet (Standard `http://localhost:PORT,http://127.0.0.1:PORT` mit `AKTE_PORT`) |
| `AKTE_HINTERGRUND` | `thread` (Standard ohne Redis: Beweissicherung in Threads im API-Prozess), `celery` (mit `REDIS_URL`), `sofort` (nur Tests) |
| `AKTE_THREADS`, `AKTE_WORKER` | Gunicorn: Threads je Worker (im Thread-Betrieb Standard 8) und Zahl der Worker (gilt nur mit Celery; im Thread-Betrieb immer 1) |
| `AKTE_ARCHIV_AKTIV` | Quellen zusätzlich öffentlich bei archive.org hinterlegen. Standard: aus (`false`). Gilt nur, solange in der Oberfläche nichts gewählt ist; die Wahl beim ersten Konto bzw. unter „Regeln“ → „Für die ganze Akte“ gewinnt |
| `AKTE_ARCHIVE_ORG_SCHLUESSEL` | archive.org-Schlüssel `zugang:geheim` (sonst drosselt archive.org anonym) |
| `AKTE_OEFFENTLICH_AKTIV` | Lesen ohne Konto für Boards mit „öffentlich“ (leer = aus) |
| `AKTE_MITGLIEDER_BOARDS` | Boards, die jedes angemeldete Konto lesen darf |
| `AKTE_LESEANSICHT` | `nur_gepruefte` (Standard: nur Unterschriebenes, das die Prüfung besteht) oder `alles_belegte` |
| `AKTE_REGELN` | Stufen der Prüfregeln für alle Boards ([belegregeln.md](belegregeln.md)); je Board über „Regeln“ in der Oberfläche |
| `AKTE_BEWEISSCHICHT`, `AKTE_SIGNIERTE_FREIGABE` | Beweiskette und Freigabe mit Unterschrift (Standard: an) |
| `AKTE_S3_BUCKET`, `AKTE_S3_ENDPOINT_URL`, `AKTE_S3_ACCESS_KEY_ID`, `AKTE_S3_SECRET_ACCESS_KEY` | Beweise in einem **privaten** S3-kompatiblen Speicher statt im Datenordner |
| `COOKIE_SECURE` | `true`, sobald die Akte über HTTPS läuft |
| `AKTE_BROWSER_AKTIV` | Seitenbilder mit markierter Fundstelle in Webseiten (braucht Chromium, siehe unten) |
| `AKTE_ABRUF_KENNUNG` | Kennung beim Abruf fremder Seiten; nur für eine Akte im Netz mit Kontaktadresse |
| `AKTE_CLIENT_IP_HEADER`, `AKTE_VERTRAUTE_PROXYS` | echte Besucher-IP hinter einem Proxy (Docker: 1 für Caddy) |
| `AKTE_DROSSEL_ANON`, `AKTE_DROSSEL_LOGIN`, `AKTE_DROSSEL_LOGIN_KONTO`, `AKTE_DROSSEL_EXPORT`, `AKTE_DROSSEL_STAND`, `AKTE_DROSSEL_EINRICHTUNG_LESEN`, `AKTE_DROSSEL_EINRICHTUNG_GESAMT` | Drosseln, z. B. `10/min`; die Einrichtung hat zusätzlich einen Deckel über alle Absender (Standard 30 Fehlversuche je Stunde) |

## Endpunkte, die Starter und Oberfläche benutzen

| Endpunkt | Wer | Zweck |
|---|---|---|
| `GET /api/v1/auth/einrichtung/` | ohne Anmeldung, locker gedrosselt | `{"offen": true, "grund": "offen"}`, solange das erste Konto fehlt und ein Einrichtungscode gesetzt ist; sonst `grund` `eingerichtet` (geht vor) oder `kein_code` |
| `POST /api/v1/auth/einrichtung/` | ohne Anmeldung, gedrosselt | erstes Konto mit Einrichtungscode anlegen |
| `GET`/`PATCH /api/v1/akte/einstellungen/` | nur Menschen der Redaktion | `{"archiv_org": false}`; Tokens dürfen es nicht ändern |
| `GET /api/v1/akte/boards/SLUG/stand/` | wie das Board | ändert sich bei jeder Änderung an der Wand; die Oberfläche lädt dann neu |
| `POST /api/v1/akte/belege/ID/pruefen/` | Redaktion, auch Tokens | Zitat am Original prüfen, Antwort nach höchstens 30 Sekunden |
| `POST /api/v1/akte/quellen/ID/sichern/` | Redaktion, auch Tokens | Beweissicherung anstoßen; läuft im Hintergrund |

## Seitenbilder und Webseiten-Fundstellen

Ob ein Zitat in einer Quelle steht, prüft die Akte bei PDFs und Webseiten am Text, ohne Browser. Ein Seitenbild mit
markiertem Zitat entsteht bei PDFs immer, bei Webseiten nur mit Chromium (Playwright). Lokal ohne Docker:
`pip install -r backend/requirements-browser.txt && playwright install chromium`, dann `AKTE_BROWSER_AKTIV=1`. Für
Docker ist ein eigener Browser-Worker geplant.

## Beweissicherung im Hintergrund

Neue Quellen sichert die Akte im Hintergrund, die Anfrage wartet nicht darauf. Ohne Redis (Standard,
`AKTE_HINTERGRUND=thread`) laufen dafür drei Arbeiter-Threads im API-Prozess: „kurz“ (Fundstellen), „lang“ (Abruf
des Originals, Browser) und „archiv“ (archive.org, mit der niedrigsten Priorität, damit ein langsames archive.org
nichts aufhält). Damit es genau eine Warteschlange gibt, startet `backend/start.sh` Gunicorn in diesem Betrieb mit
**genau einem Worker** und `AKTE_THREADS` Threads (Standard 8); ein `AKTE_WORKER` größer 1 gilt dann nicht.

Was bei einem Neustart in der Warteschlange lag, holt die Akte beim Start nach (`backend/gunicorn.conf.py`): Quellen
mit Adresse ohne eigene Kopie, ist archive.org an, auch Quellen ohne Archivkopie. Das läuft in Chargen zu 25, bis
alles durch ist. Zuerst kommen Quellen, die noch nie versucht wurden, dann die mit dem am längsten zurückliegenden
Versuch. Ausgenommen sind Quellen, die in der letzten Stunde versucht wurden, die schon dreimal gescheitert sind oder
deren Adresse nie an archive.org gehen darf (Zugangsdaten in der Adresse, nicht öffentlich). „Neu sichern“ im Browser
geht immer. Mehrere Worker nur mit Celery und Redis (`AKTE_HINTERGRUND=celery`, `REDIS_URL`).

## Befehle für die Redaktion

Im Akte-Ordner (Windows: Rechtsklick auf eine freie Stelle → „In Terminal öffnen“). Großgeschriebene Wörter ersetzt
du durch deine Werte.

```
docker compose exec api python manage.py akte_einrichten --benutzer NAME
```

```
docker compose exec api python manage.py akte_einrichten --falls-keins
```

```
docker compose exec api python manage.py changepassword NAME
```

```
docker compose exec api python manage.py akte_token NAME --neu
```

```
docker compose exec api python manage.py akte_konten
```

```
docker compose exec api python manage.py akte_demo --neu
```

```
docker compose exec api python manage.py akte_schwaerzen --faden ID
```

`akte_einrichten` legt ein weiteres Redaktionskonto an (`--token` gibt zusätzlich einen Token aus, `--admin`
Zugang zur Django-Verwaltung); `--falls-keins` tut nichts, wenn es schon ein Redaktionskonto gibt. `changepassword`
setzt ein vergessenes Passwort neu. `akte_token NAME --neu` verwirft den alten Token; danach den Agenten neu
verbinden. Ohne `NAME` nimmt `akte_token` das einzige aktive Konto der Redaktion. `akte_konten` listet die aktiven
Konten, die an der Akte arbeiten dürfen (Redaktion oder Superuser), je Zeile `KONTO:name`; so wählt auch der
Starter. `akte_schwaerzen` schwärzt den Inhalt eines Fadens in der Kette.

Beim Start räumt der Container abgelaufene Einträge der Sitzungs-Sperrliste auf (`flushexpiredtokens`). Über den
Eingang (Caddy) ist `/admin` bewusst nicht erreichbar; wer die Verwaltung braucht, startet das Backend ohne Docker
(`manage.py runserver`) auf dem eigenen Rechner.

## Sichern und Zurückspielen

Alles liegt im Docker-Volume `die-akte_akte-daten`: Datenbank, Beweise, **Geräteschlüssel**
(`schluessel/geraet_ed25519.pem`). Ohne Geräteschlüssel lassen sich neue Sicherungen nicht mehr mit demselben
Schlüssel signieren; die alte Kette bleibt prüfbar. Heb zusätzlich deine `.env` auf.

Sichern, im Akte-Ordner (dieselbe Zeile in PowerShell, macOS und Linux; in Git Bash geht sie nicht):

```
docker run --rm -v die-akte_akte-daten:/daten -v "${PWD}:/ziel" alpine tar czf /ziel/akte-sicherung.tgz -C /daten .
```

Zurückspielen: Akte anhalten (`STOP-AKTE`), dann:

```
docker run --rm -v die-akte_akte-daten:/daten -v "${PWD}:/ziel" alpine sh -c "cd /daten && tar xzf /ziel/akte-sicherung.tgz"
```

Danach wieder starten.

## Neue Version

Die Daten liegen im Volume, nicht im Ordner. Eine neue Version ersetzt nur den Ordner:

1. Akte anhalten: `STOP-AKTE`.
2. Den alten Ordner umbenennen, z. B. `Akte` → `Akte-alt`.
3. Die neue Release-ZIP laden und als `Akte` entpacken (wie beim ersten Mal).
4. Die Datei `.env` aus `Akte-alt` nach `Akte` kopieren. Sie enthält den geheimen Schlüssel deiner Akte.
5. Starten: `START-AKTE`. Docker baut neu.
6. Claude neu verbinden: `AGENT-VERBINDEN`, dann Claude neu starten.

Läuft alles, kannst du `Akte-alt` löschen.

### Neue Version 0.2.0 (von 0.1)

Die Schritte oben gelten. Was sich dabei ändert (alle Änderungen: [aenderungen-0.2.0.md](aenderungen-0.2.0.md)):

* **archive.org ist jetzt standardmäßig aus.** Stand in deiner alten `.env` nichts zu `AKTE_ARCHIV_AKTIV`, landeten
  in 0.1 alle Quell-Adressen bei archive.org; ab 0.2.0 nicht mehr. Willst du das weiter, schalte es als Mensch unter
  „Regeln“ → „Für die ganze Akte“ ein. Beim Einschalten werden ältere Quellen im Hintergrund nachgesichert. Was schon
  bei archive.org liegt, bleibt dort.
* **Host-Filter.** Die Akte antwortet nur noch unter den Namen in `AKTE_HOSTS` (Standard `localhost 127.0.0.1 ::1
  [::1]`), alle anderen bekommen 421. Erreichst du deine Akte unter einer eigenen Domain, einer IP-Adresse im
  Heimnetz (z. B. `192.0.2.10`) oder einem Rechnernamen (z. B. `buero-pc`), trag jeden dieser Namen vor dem Start in
  `.env` ein, und zwar in **beide** Variablen:
  `AKTE_HOSTS="akte.example.org localhost 127.0.0.1 ::1 [::1]"` (Leerzeichen) und
  `DJANGO_ALLOWED_HOSTS=akte.example.org,localhost,127.0.0.1,[::1]` (Komma). Meldest du dich unter diesem Namen an,
  gehört er mit Schema und Port auch in `DJANGO_CSRF_TRUSTED_ORIGINS`, z. B. `https://akte.example.org`. Sonst
  sperrt dich der Filter aus (421) bzw. Django antwortet mit 400. Bisher stand `DJANGO_ALLOWED_HOSTS` fest in
  `compose.yaml`; jetzt gilt der Wert aus `.env`.
* **Wand mit dem Kurznamen `einrichten`:** Unter `/akte/einrichten` liegt jetzt die Seite für das erste Konto. Eine
  Wand mit genau diesem Kurznamen (Adresse) ist dort nicht mehr erreichbar, und neue Wände dürfen ihn nicht mehr
  tragen. Gibt es so eine Wand, meldet die Akte das beim Start im Protokoll (`docker compose logs api`) und nennt den
  Weg, ihr einen anderen Kurznamen zu geben.
* **Hintergrund-Arbeit:** Ohne Redis läuft Gunicorn mit genau einem Worker und 8 Threads
  ([Beweissicherung im Hintergrund](#beweissicherung-im-hintergrund)). Hattest du `AKTE_WORKER` erhöht, gilt das nur
  noch mit Celery.
* **Erstes Konto im Browser:** Eine Akte, die schon ein Konto hat, merkt davon nichts. Eine Akte mit Daten bekommt
  beim Upgrade **keinen** Einrichtungscode. Fehlt dort noch das Konto, nimm den Notweg `akte_einrichten`.
* **Der Einrichtungscode verschwindet** nach der Einrichtung aus `.env` (beim nächsten `start` oder `agent`).
* **`.env` nur für dich:** Der Starter beschränkt beim Start die Rechte der Datei auf dein Konto.
* **Claude neu verbinden** ist diesmal Pflicht: Der Baustein kommt aus der ZIP von v0.2.0 und braucht
  `--python 3.12` (`AGENT-VERBINDEN` trägt beides ein).

## Alles löschen

Erst den Ordner sichern, falls du die Daten noch brauchst. Dann im Akte-Ordner:

```
docker compose down -v
```

`-v` löscht das Volume mit **allen Daten** der Akte, ohne Rückfrage. Danach kannst du den Ordner löschen. Den Eintrag
bei Claude Code entfernst du mit `claude mcp remove akte -s user`.

## Postgres statt SQLite

`DATABASE_URL=postgres://akte:PASSWORT@db:5432/akte` setzen und einen Postgres-Dienst ergänzen. SQLite reicht für
eine Redaktion auf einem Rechner.

## Für ein Team im Netz

Nur mit HTTPS davor (z. B. Caddy mit eigener Domain), dann:

* Port-Bindung in `compose.yaml` anpassen,
* deine Domain in `.env` in `AKTE_HOSTS` (Leerzeichen), `DJANGO_ALLOWED_HOSTS` (Komma) und, mit `https://`, in
  `DJANGO_CSRF_TRUSTED_ORIGINS` eintragen (sonst 421 vom Eingang bzw. 400 von Django),
* `COOKIE_SECURE` nicht mehr auf `false`,
* `AKTE_VERTRAUTE_PROXYS` auf die Zahl deiner Proxys,
* das erste Konto anlegen, **bevor** die Akte aus dem Netz erreichbar ist, oder `AKTE_EINRICHTUNGSCODE` leer lassen
  und `akte_einrichten` benutzen,
* `AKTE_ABRUF_KENNUNG` mit einer Kontaktadresse setzen,
* AGPL § 13: Der Quelltext-Link unten auf der Board-Übersicht muss auf deine Fassung zeigen
  (`NEXT_PUBLIC_AKTE_QUELLTEXT_URL`).
