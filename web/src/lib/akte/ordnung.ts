// Ordnung auf der Wand: nichts verdeckt etwas anderes.

export interface Rechteck {
  x: number
  y: number
  b: number
  h: number
}

const RASTER = 20

export function trifft(a: Rechteck, b: Rechteck, luft = 0): boolean {
  return a.x < b.x + b.b + luft && b.x < a.x + a.b + luft && a.y < b.y + b.h + luft && b.y < a.y + a.h + luft
}

/**
 * Nach dem Ziehen: liegt die Karte auf einer anderen, rutscht sie auf den nächsten
 * freien Platz — in wachsenden Ringen um die Stelle, an der sie losgelassen wurde.
 */
export function freierPlatz(ziel: Rechteck, andere: Rechteck[], luft = 30): { x: number; y: number } {
  const frei = (x: number, y: number) => !andere.some((o) => trifft({ ...ziel, x, y }, o, luft))
  if (frei(ziel.x, ziel.y)) return { x: ziel.x, y: ziel.y }
  for (let ring = 1; ring < 80; ring++) {
    const d = ring * RASTER
    const kandidaten: [number, number][] = []
    for (let s = -ring; s <= ring; s++) {
      kandidaten.push([ziel.x + s * RASTER, ziel.y - d], [ziel.x + s * RASTER, ziel.y + d])
      kandidaten.push([ziel.x - d, ziel.y + s * RASTER], [ziel.x + d, ziel.y + s * RASTER])
    }
    kandidaten.sort((a, b) => Math.hypot(a[0] - ziel.x, a[1] - ziel.y) - Math.hypot(b[0] - ziel.x, b[1] - ziel.y))
    const treffer = kandidaten.find(([x, y]) => frei(x, y))
    if (treffer) return { x: treffer[0], y: treffer[1] }
  }
  return { x: ziel.x, y: ziel.y }
}

export interface Etikett {
  id: string
  x: number // Mittelpunkt
  y: number
  b: number
  h: number
}

/**
 * Faden-Beschriftungen weichen einander und den Karten aus: der Reihe nach von oben
 * nach unten, jede rückt auf den nächsten freien Platz über oder unter ihrer Fadenmitte.
 * Liefert den senkrechten Versatz je Etikett.
 */
export function etikettenVersatz(etiketten: Etikett[], luft = 4, hindernisse: Rechteck[] = []): Map<string, number> {
  // Karten sind feste Hindernisse: eine Beschriftung verdeckt nie einen Kartentitel.
  const gesetzt: Rechteck[] = [...hindernisse]
  const versatz = new Map<string, number>()
  const folge = [...etiketten].sort((a, b) => a.y - b.y || a.x - b.x)
  for (const e of folge) {
    // Nächster freier Platz über oder unter der Fadenmitte, abwechselnd in 8-px-Schritten.
    let dy = 0
    for (let schritt = 0; schritt < 160; schritt++) {
      const kandidat = schritt === 0 ? 0 : (schritt % 2 ? 1 : -1) * Math.ceil(schritt / 2) * 8
      const r: Rechteck = { x: e.x - e.b / 2, y: e.y - e.h / 2 + kandidat, b: e.b, h: e.h }
      if (!gesetzt.some((g) => trifft(r, g, luft))) {
        dy = kandidat
        break
      }
    }
    gesetzt.push({ x: e.x - e.b / 2, y: e.y - e.h / 2 + dy, b: e.b, h: e.h })
    versatz.set(e.id, dy)
  }
  return versatz
}

/** Grobe Breite einer Beschriftung in Flächen-Pixeln (13 px Schrift, Zeitraum dahinter). */
export function etikettBreite(text: string): number {
  return Math.min(220, 24 + text.length * 7)
}

/** Höhe einer Beschriftung: sie bricht bei 220 px um, je Zeile 17 px, dazu der Stempel bei Verdacht/Meinung. */
export function etikettHoehe(text: string, mitStempel: boolean): number {
  const zeilen = Math.max(1, Math.ceil((24 + text.length * 7) / 220))
  return zeilen * 17 + 8 + (mitStempel ? 28 : 0)
}

/** Schriftgröße so, dass das längste Wort in die Karte passt (Anton ≈ 0,5 em je Zeichen, 196 px Innenbreite). */
export function passendeGroesse(name: string, wunsch: number): number {
  const laengstes = Math.max(...name.split(/\s+/).map((w) => w.length), 1)
  return Math.min(wunsch, Math.floor(196 / (laengstes * 0.5)))
}

export type BildArt = "zeichen" | "unbeschnitten" | "fuellend"

/** Wie ein Kartenbild sitzt, abgelesen am Nachweis:
 *  Logo, Siegel, Wappen ganz und auf hellem Grund (breite Schriftzüge würden sonst zu „licr“ beschnitten);
 *  CC BY-SA / BY-ND unbeschnitten (Hausregel); alles andere füllt das Feld. */
export function bildArt(nachweis?: string | null): BildArt {
  const n = nachweis ?? ""
  if (/^(Logo|Siegel|Wappen):/.test(n)) return "zeichen"
  if (/BY-(SA|ND)/.test(n)) return "unbeschnitten"
  return "fuellend"
}
