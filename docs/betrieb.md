# Betrieb

Standard ist **lokal auf einem Rechner** (`compose.yaml`, Port nur an `127.0.0.1`). Dieses Kapitel ist für alle, die
mehr wollen: Seitenbilder von Webseiten, Postgres, Zugriff für ein Team.

## Einstellungen (`.env`)

| Variable | Bedeutung |
|---|---|
| `DJANGO_SECRET_KEY` | Pflicht, langer Zufallswert (die Startdateien legen ihn an) |
| `AKTE_PORT`, `AKTE_TITEL` | Port auf deinem Rechner, Titel im Browser |
| `AKTE_OEFFENTLICH_AKTIV` | Lesen ohne Konto für Boards mit „öffentlich“ (leer = aus) |
| `AKTE_MITGLIEDER_BOARDS` | Boards, die jedes angemeldete Konto lesen darf |
| `AKTE_LESEANSICHT` | `nur_gepruefte` (Standard: nur Unterschriebenes, das die Prüfung besteht) oder `alles_belegte` |
| `AKTE_REGELN` | Stufen der Prüfregeln für alle Boards ([belegregeln.md](belegregeln.md)); je Board über „Regeln“ in der Oberfläche |
| `AKTE_BEWEISSCHICHT`, `AKTE_SIGNIERTE_FREIGABE` | Beweiskette und Freigabe mit Unterschrift (Standard: an) |
| `AKTE_S3_BUCKET`, `AKTE_S3_ENDPOINT_URL`, `AKTE_S3_ACCESS_KEY_ID`, `AKTE_S3_SECRET_ACCESS_KEY` | Beweise in einem **privaten** S3-kompatiblen Speicher statt im Datenordner |
| `AKTE_ARCHIV_AKTIV` | Quellen zusätzlich bei archive.org hinterlegen (Standard: an; die URL wird dort öffentlich) |
| `AKTE_ARCHIVE_ORG_SCHLUESSEL` | archive.org-Schlüssel `zugang:geheim` (sonst drosselt archive.org anonym) |
| `COOKIE_SECURE` | `true`, sobald die Akte über HTTPS läuft |
| `AKTE_BROWSER_AKTIV` | Seitenbilder und Fundstellen in Webseiten (braucht Chromium, siehe unten) |
| `AKTE_ABRUF_KENNUNG` | Kennung beim Abruf fremder Seiten, bitte mit Kontaktadresse deiner Instanz |
| `AKTE_CLIENT_IP_HEADER`, `AKTE_VERTRAUTE_PROXYS` | echte Besucher-IP hinter einem Proxy |

## Seitenbilder und Webseiten-Fundstellen

PDF-Fundstellen funktionieren immer. Für Webseiten braucht die Akte Chromium (Playwright). Lokal ohne Docker:
`pip install -r backend/requirements-browser.txt && playwright install chromium`, dann `AKTE_BROWSER_AKTIV=1`.
Mit Docker kommt ein eigener Browser-Worker mit Redis und Celery dazu (in Arbeit für 0.2).

## Postgres statt SQLite

`DATABASE_URL=postgres://akte:<passwort>@db:5432/akte` setzen und einen Postgres-Dienst ergänzen. SQLite reicht für
eine Redaktion auf einem Rechner.

## Für ein Team im Netz

Nur mit HTTPS davor (z. B. Caddy mit eigener Domain), dann:

* Port-Bindung in `compose.yaml` anpassen und `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` setzen,
* `COOKIE_SECURE` nicht mehr auf `false`,
* `AKTE_VERTRAUTE_PROXYS` auf die Zahl deiner Proxys,
* AGPL § 13: Der Quelltext-Link unten auf der Board-Übersicht muss auf deine Fassung zeigen
  (`NEXT_PUBLIC_AKTE_QUELLTEXT_URL`).

## Befehle für die Redaktion

```sh
docker compose exec api python manage.py akte_einrichten --benutzer <name> [--token] [--admin]
docker compose exec api python manage.py akte_demo [--neu] [--oeffentlich]
docker compose exec api python manage.py akte_schwaerzen --faden <id>   # Inhalt aus der Kette schwärzen
```

`--admin` gibt zusätzlich Zugang zur Django-Verwaltung. Über den Eingang (Caddy) ist `/admin` bewusst nicht
erreichbar; wer sie braucht, startet das Backend ohne Docker (`manage.py runserver`) auf dem eigenen Rechner.

## Sichern

Alles liegt im Volume `akte-daten`: Datenbank, Beweise, **Geräteschlüssel** (`schluessel/geraet_ed25519.pem`).
Ohne Geräteschlüssel lassen sich neue Sicherungen nicht mehr mit demselben Schlüssel signieren; die alte Kette bleibt
prüfbar. Sichern:

```sh
docker run --rm -v die-akte_akte-daten:/daten -v "$PWD":/ziel alpine tar czf /ziel/akte-sicherung.tgz -C /daten .
```
