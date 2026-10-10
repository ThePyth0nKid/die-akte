# Videos aus der Wand

Eine **Fahrt** ist eine Folge von Stationen: welche Karten im Fokus stehen, wie lange, mit welchem Stichwort,
optional ein Beweisstück mit Zitat. Der Renderer fotografiert die Wand Bild für Bild (25 fps) in einem unsichtbaren
Browser – das Bild ist eine reine Funktion der Zeit, also wiederholbar.

## Einrichten

```sh
cd render && npm ci && npx playwright install chromium     # einmalig; ffmpeg muss installiert sein
export AKTE_BASIS=http://127.0.0.1:8080 AKTE_TOKEN=<token> AKTE_WEB_LOGIN=<konto> AKTE_WEB_PASSWORT=<passwort>
```

## Nur Bild

```sh
python render/aufnahme.py rendern <board> "<Titel der Fahrt>" --format 16x9,9x16 [--4k] [--unschaerfe]
```

Ergebnis in `./ausgabe/<datum>_akte-<board>-<fahrt>/`: MP4 (H.264, CRF 16, 25 fps), ein Standbild je Station und der
Auftrag als JSON. Formate: `16x9`, `9x16`, `1x1`, `oben` (1080×960 für geteilte Hochkant-Videos).

## Mit Stimme und Musik

Eine YAML ist Fahrt und Sprechtext zugleich:

```yaml
titel: Wer wertet Musterhafens Daten aus?
format: "16:9"
stationen:
  - fokus: []
    text: Eine Stadt, ein Auftrag, eine Firma.
  - fokus: ["Senat der Freien Stadt Musterhafen", "Nordlicht Analytik GmbH"]
    text: Der Senat vergibt die Auswertung der Verkehrsdaten.
    beweis: "Drucksache 9/1234 – Antwort des Senats"
    zitat: "Der Senat beauftragt die Nordlicht Analytik GmbH mit der Auswertung der Verkehrsdaten."
```

```sh
cp render/ton.beispiel.yaml ton.yaml            # eigene ElevenLabs-Stimm-IDs eintragen
export ELEVENLABS_API_KEY=…                      # nie in Dateien
python render/aufnahme.py video <board> kapitel.yaml --stimme erzaehler --ziel ausgabe/kapitel-1
```

Ablauf: Fahrt anlegen → Stimme mit Zeitmarken (die Kamera kommt beim ersten Wort an) → Musik → Bild → Mischung
(Stimme −16, Musik −30 mit Ducking, Summe −14 LUFS, True Peak −1,5 dB). Effektklänge nur mit eigener Klangbank
(`--klaenge <ordner mit _BANK.json>`) und geklärter Lizenz. `python render/vertonen.py gegenprobe <ordner>` liest
Zahlen und Namen mit Whisper gegen.

## Live fahren (OBS)

Im Aufnahme-Dialog „Live fahren“: → / Leertaste weiter, ← zurück, Esc Ende. Den Knopf „Video rendern“ gibt es, wenn
`node render/render_dienst.cjs` läuft (nur auf `127.0.0.1`).
