// Gerenderte Aufnahme: Kamera je Format, Zeitplan einer Fahrt und das Bild zu jeder Millisekunde.
// Alles hier ist eine reine Funktion — dieselbe Zeit ergibt immer dasselbe Bild.

import type { Rechteck } from "./ordnung"

export type FormatKennung = "16x9" | "9x16" | "1x1" | "oben"

export interface Format {
  b: number
  h: number
  /** Sichere Ränder in Pixeln: dort steht kein Kartentitel. */
  rand: { o: number; u: number; l: number; r: number }
  /** Kartentitel mindestens so hoch (Ziel) und Untergrenze vor dem Schwenk, in Pixeln; höchster Zoom. */
  titelMin: number
  titelNot: number
  zoomMax: number
}

export const FORMATE: Record<FormatKennung, Format> = {
  "16x9": { b: 1920, h: 1080, rand: { o: 54, u: 54, l: 96, r: 96 }, titelMin: 40, titelNot: 32, zoomMax: 2.4 },
  // Hochformat: oben und unten je 8 % für Plattform-Oberfläche und Texte. Auf dem Telefon muss es näher ran:
  // große Titel, lieber von Karte zu Karte schwenken als zwei kleine Karten mit viel Dunkel drumherum.
  "9x16": { b: 1080, h: 1920, rand: { o: 154, u: 154, l: 54, r: 54 }, titelMin: 56, titelNot: 50, zoomMax: 3.6 },
  "1x1": { b: 1080, h: 1080, rand: { o: 54, u: 54, l: 54, r: 54 }, titelMin: 48, titelNot: 40, zoomMax: 3.0 },
  // Obere Hälfte bei 50/50: unten grenzt das Kamerabild an, dort etwas mehr Luft.
  oben: { b: 1080, h: 960, rand: { o: 40, u: 48, l: 54, r: 54 }, titelMin: 44, titelNot: 38, zoomMax: 2.8 },
}

export const FORMAT_KENNUNGEN = Object.keys(FORMATE) as FormatKennung[]

/** Anteil der sicheren Fläche, den die Fokus-Karten an ihrer begrenzenden Kante füllen. */
export const FUELLUNG = 0.84
export const ZOOM_MIN = 0.08
/** Querformat-Werte (Tests, Server-Spiegel in kamera.py); jedes Format hat eigene in FORMATE. */
export const ZOOM_MAX = FORMATE["16x9"].zoomMax
/** Kartentitel so hoch im Endbild (Ziel). */
export const TITEL_MIN_PX = FORMATE["16x9"].titelMin
/**
 * Untergrenze, bevor die Kamera lieber schwenkt: Zusammenhang in einem Bild ist mehr wert als
 * 8 px Schrift — vier Karten nebeneinander bleiben im Querformat ein Bild (Titel ≈ 34 px).
 */
export const TITEL_NOT_PX = FORMATE["16x9"].titelNot
/** Zuschlag je Seite für die gedrehten Karten (±2°) und die Nadel. */
const ZUSCHLAG = 14

export interface Kamera {
  cx: number
  cy: number
  zoom: number
}

export interface FokusKarte extends Rechteck {
  /** Schriftgröße des Kartentitels in Wand-Pixeln. */
  titelPx: number
}

export function sichereFlaeche(f: Format): Rechteck {
  return { x: f.rand.l, y: f.rand.o, b: f.b - f.rand.l - f.rand.r, h: f.h - f.rand.o - f.rand.u }
}

export function umriss(rechtecke: Rechteck[], zuschlag = ZUSCHLAG): Rechteck {
  const x0 = Math.min(...rechtecke.map((r) => r.x)) - zuschlag
  const y0 = Math.min(...rechtecke.map((r) => r.y)) - zuschlag
  const x1 = Math.max(...rechtecke.map((r) => r.x + r.b)) + zuschlag
  const y1 = Math.max(...rechtecke.map((r) => r.y + r.h)) + zuschlag
  return { x: x0, y: y0, b: x1 - x0, h: y1 - y0 }
}

const klemme = (z: number, f: Format) => Math.min(f.zoomMax, Math.max(ZOOM_MIN, z))

/** Zoom, bei dem der Umriss die sichere Fläche zu `fuellung` ausfüllt. */
function passenderZoom(u: Rechteck, f: Format, fuellung: number): number {
  const s = sichereFlaeche(f)
  return fuellung * Math.min(s.b / u.b, s.h / u.h)
}

function kameraAuf(u: Rechteck, zoom: number): Kamera {
  return { cx: u.x + u.b / 2, cy: u.y + u.h / 2, zoom }
}

/** Die ganze Wand, leicht eingerückt; Titelregel gilt hier nicht. */
export function ueberblick(alle: Rechteck[], f: Format): Kamera {
  if (!alle.length) return { cx: 0, cy: 0, zoom: 1 }
  const u = umriss(alle, 40)
  return kameraAuf(u, klemme(passenderZoom(u, f, 0.94), f))
}

/**
 * Kamera(s) für eine Station. Normalfall: eine Kamera, die Fokus-Karten füllen die sichere
 * Fläche zu 84 %. Wären die Titel dabei kleiner als das Format verlangt (hohes Format, Karten nebeneinander),
 * schwenkt die Kamera stattdessen nah von Gruppe zu Gruppe.
 */
export function rahmeStation(karten: FokusKarte[], f: Format, beiwerk: Rechteck[] = []): Kamera[] {
  if (!karten.length) return []
  // Beiwerk (Beschriftungen der beleuchteten Fäden) gehört ins Bild, zählt aber nicht für die Titelregel.
  const u = umriss([...karten, ...beiwerk])
  const s = sichereFlaeche(f)
  const zFuell = klemme(passenderZoom(u, f, FUELLUNG), f)
  const zTitel = Math.min(f.zoomMax, f.titelMin / Math.min(...karten.map((k) => k.titelPx)))
  if (zFuell >= zTitel) return [kameraAuf(u, zFuell)]
  // Passt alles noch bei Titel-Zoom in die sichere Fläche, dann eben knapper gerahmt.
  if (u.b * zTitel <= s.b && u.h * zTitel <= s.h) return [kameraAuf(u, zTitel)]
  // Ganz knapp daneben: ein Bild mit etwas kleineren Titeln statt eines Schwenks.
  const zGanz = klemme(passenderZoom(u, f, 1), f)
  if (zGanz * Math.min(...karten.map((k) => k.titelPx)) >= f.titelNot) return [kameraAuf(u, zGanz)]
  // Schwenk: eine Kette von Nachbar zu Nachbar (auch über zwei Reihen), daraus Gruppen,
  // die bei Titel-Zoom passen.
  const folge = nachbarKette(karten, u.b * zTitel > s.b)
  const gruppen: FokusKarte[][] = []
  for (const k of folge) {
    const letzte = gruppen[gruppen.length - 1]
    if (letzte) {
      const probe = umriss([...letzte, k])
      if (probe.b * zTitel <= s.b * FUELLUNG && probe.h * zTitel <= s.h * FUELLUNG) {
        letzte.push(k)
        continue
      }
    }
    gruppen.push([k])
  }
  // Ein gemeinsamer Zoom, damit es beim Schwenken nicht pumpt.
  const zoom = klemme(Math.max(zTitel, Math.min(...gruppen.map((g) => passenderZoom(umriss(g), f, FUELLUNG)))), f)
  return gruppen.map((g) => kameraAuf(umriss(g), zoom))
}

/** Reihenfolge für den Schwenk: vom ersten Karte (links bzw. oben) immer zur nächstgelegenen. */
function nachbarKette(karten: FokusKarte[], waagrecht: boolean): FokusKarte[] {
  const mitte = (k: FokusKarte) => [k.x + k.b / 2, k.y + k.h / 2]
  const rest = [...karten].sort((a, b) => (waagrecht ? a.x - b.x || a.y - b.y : a.y - b.y || a.x - b.x))
  const folge = [rest.shift()!]
  while (rest.length) {
    const [lx, ly] = mitte(folge[folge.length - 1])
    let beste = 0
    let abstand = Infinity
    rest.forEach((k, i) => {
      const [x, y] = mitte(k)
      const d = Math.hypot(x - lx, y - ly)
      if (d < abstand) { abstand = d; beste = i }
    })
    folge.push(rest.splice(beste, 1)[0])
  }
  return folge
}

/** So viel Platz (px) braucht eine Zahlen- oder Zitatkarte unten im Bild (Anton groß, Text, Quelle). */
export const EINBLENDUNG_PLATZ_PX = 300

/**
 * Kameras für eine Station mit Einblendung unten: die sichere Fläche endet über der Karte, auch beim Schwenk.
 * Die Kameras werden in der verkleinerten Fläche gerechnet und so verschoben, dass sie im ganzen Bild
 * oberhalb der Einblendung sitzen.
 */
export function rahmeUeberEinblendung(karten: FokusKarte[], f: Format, beiwerk: Rechteck[] = [], platzPx = EINBLENDUNG_PLATZ_PX): Kamera[] {
  const knapp: Format = { ...f, rand: { ...f.rand, u: f.rand.u + platzPx } }
  // viewportVon zentriert in der vollen sicheren Fläche; deren Mitte liegt platzPx/2 tiefer als die der knappen.
  return rahmeStation(karten, knapp, beiwerk).map((k) => ({ ...k, cy: k.cy + platzPx / 2 / k.zoom }))
}

/** React-Flow-Viewport für eine Kamera: der Punkt (cx, cy) liegt in der Mitte der sicheren Fläche. */
export function viewportVon(k: Kamera, f: Format): { x: number; y: number; zoom: number } {
  const s = sichereFlaeche(f)
  return { x: s.x + s.b / 2 - k.cx * k.zoom, y: s.y + s.h / 2 - k.cy * k.zoom, zoom: k.zoom }
}

// ─── Bewegung ───────────────────────────────────────────────────────────────

export const sanft = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)
export const weich = (t: number) => -(Math.cos(Math.PI * t) - 1) / 2
const k01 = (t: number) => Math.min(1, Math.max(0, t))

/**
 * Kameraflug nach van Wijk & Nuij: bei weiten Wegen zieht die Kamera kurz auf und
 * fliegt dann ein, statt quer über die Wand zu wischen. `breite` = sichtbare Wandbreite.
 */
export function flug(von: Kamera, nach: Kamera, bildBreite: number, rho = 1.3): (t: number) => Kamera {
  const rho2 = rho * rho
  const rho4 = rho2 * rho2
  const w0 = bildBreite / von.zoom
  const w1 = bildBreite / nach.zoom
  const dx = nach.cx - von.cx
  const dy = nach.cy - von.cy
  const d2 = dx * dx + dy * dy
  if (d2 < 1e-6) {
    const S = Math.log(w1 / w0) / rho
    return (t) => ({ cx: von.cx + t * dx, cy: von.cy + t * dy, zoom: bildBreite / (w0 * Math.exp(rho * t * S)) })
  }
  const d1 = Math.sqrt(d2)
  const b0 = (w1 * w1 - w0 * w0 + rho4 * d2) / (2 * w0 * rho2 * d1)
  const b1 = (w1 * w1 - w0 * w0 - rho4 * d2) / (2 * w1 * rho2 * d1)
  const r0 = Math.log(Math.sqrt(b0 * b0 + 1) - b0)
  const r1 = Math.log(Math.sqrt(b1 * b1 + 1) - b1)
  const S = (r1 - r0) / rho
  return (t) => {
    if (t >= 1) return { ...nach }
    const s = t * S
    const u = (w0 / (rho2 * d1)) * (Math.cosh(r0) * Math.tanh(rho * s + r0) - Math.sinh(r0))
    const w = (w0 * Math.cosh(r0)) / Math.cosh(rho * s + r0)
    return { cx: von.cx + u * dx, cy: von.cy + u * dy, zoom: bildBreite / w }
  }
}

// ─── Zeitplan einer Fahrt ───────────────────────────────────────────────────

export interface Einblendung {
  gross: string
  klein?: string
  quelle?: string
  /** Ganze Fläche abdunkeln (Pointe), statt die Karte über die Wand zu legen. */
  voll?: boolean
}

export interface PlanEingabe {
  kameras: Kamera[]
  /** Entitäts-IDs im Scheinwerfer, null = alles hell (Überblick). */
  fokus: number[] | null
  stichwort: string
  beweis: { quelle: number; zitat?: string } | null
  /** Dauer der Anfahrt aus der Station (dauer_ms). */
  fahrtMs: number
  einblendung?: Einblendung | null
  /** Im Takt der Stimme: hier beginnt der Satz, und genau dann steht die Kamera. */
  ankunftMs?: number
  /** O-Ton-Einspieler: Länge des Ausschnitts und Standbild danach (ms). */
  einspieler?: {
    dauerMs: number; freezeMs: number; quelle: string; untertitel?: string
    /** Dasselbe Werk lief schon vorher: die 5-s-Regel für die Quelle gilt nur beim ersten Auftritt. */
    quelleGezeigt?: boolean
  } | null
}

export interface Einstellungen {
  halteMs: number
  /** Wie lange das Beweisblatt ganz steht. */
  beweisMs: number
  /** Drift beim Halten: Zoomzuwachs (0,03 = 3 %). */
  drift: number
  bildBreite: number
  /** Im Takt der Stimme: Länge der Tonspur; die letzte Station hält bis hierhin. */
  endeMs?: number
}

export const STANDARD: Omit<Einstellungen, "bildBreite"> = { halteMs: 3000, beweisMs: 4500, drift: 0.03 }

const SCHEINWERFER_MS = 500
const FADEN_ZUG_MS = 800
const SCHWENK_MS = 1100
const SCHWENK_HALT_MIN_MS = 1200
const BEWEIS_REIN_MS = 700
const BEWEIS_RAUS_MS = 500
const BEWEIS_VORLAUF_MS = 400
const MIN_FAHRT_MS = 1000
const AUSKLANG_MS = 600
/** Im Takt der Stimme: der Flug nimmt höchstens diesen Anteil der Lücke zwischen zwei Satzanfängen. */
const FLUG_ANTEIL = 0.45
const FLUG_MIN_MS = 650
const EINBLENDUNG_MS = 380
/** Einspieler: kurz nach der Ankunft rein, nach dem Standbild weich raus. */
const EINSPIELER_VORLAUF_MS = 300
const EINSPIELER_BLENDE_MS = 350
export const EINSPIELER_FPS = 25

/** Die Quellenangabe eines O-Tons steht mindestens so lange (Hausregel zum Zitatrecht). */
export const QUELLE_MIN_MS = 5000

/** Standbild so lang, dass Clip + Standbild die Quelle mindestens 5 s zeigen (beim ersten Auftritt des Werks). */
export function einspielerFreeze(dauerMs: number, freezeMs: number, quelleGezeigt = false): number {
  return quelleGezeigt ? freezeMs : Math.max(freezeMs, QUELLE_MIN_MS - dauerMs)
}

/** Wie lange eine Station mit Einspieler mindestens steht (frei und beim Vertonen gleich gerechnet). */
export function einspielerStationMs(dauerMs: number, freezeMs: number, quelleGezeigt = false): number {
  return EINSPIELER_VORLAUF_MS + dauerMs + einspielerFreeze(dauerMs, freezeMs, quelleGezeigt) + EINSPIELER_BLENDE_MS + 150
}

function einspielerFenster(s: PlanEingabe, ankunft: number, ende: number) {
  if (!s.einspieler) return null
  const t0 = ankunft + Math.min(EINSPIELER_VORLAUF_MS, (ende - ankunft) * 0.1)
  const laufBis = Math.min(ende, t0 + s.einspieler.dauerMs)
  const freeze = einspielerFreeze(s.einspieler.dauerMs, s.einspieler.freezeMs, s.einspieler.quelleGezeigt)
  return { t0, laufBis, t1: Math.min(ende, laufBis + freeze + EINSPIELER_BLENDE_MS) }
}

type Bewegung =
  | { art: "flug"; t0: number; t1: number; f: (t: number) => Kamera }
  | { art: "halten"; t0: number; t1: number; kamera: Kamera; richtung: number; drift: number }

export interface PlanStation {
  start: number
  ankunft: number
  ende: number
  /** Zeit für das Standbild: Mitte des ersten Haltens. */
  standbild: number
  eingabe: PlanEingabe
  fokusVorher: number[] | null
  beweis: { t0: number; t1: number } | null
  einblendung: { t0: number; t1: number } | null
  /** Einspieler: t0 = erstes Bild des Clips, laufBis = letztes bewegtes Bild, t1 = Ende inkl. Standbild. */
  einspieler: { t0: number; laufBis: number; t1: number } | null
}

export interface Plan {
  dauerMs: number
  bildBreite: number
  stationen: PlanStation[]
  bewegungen: Bewegung[]
}

const gleicheKameras = (a: Kamera[], b: Kamera[]) =>
  a.length === b.length &&
  a.every((k, i) => Math.abs(k.cx - b[i].cx) < 1 && Math.abs(k.cy - b[i].cy) < 1 && Math.abs(k.zoom - b[i].zoom) < 0.01)

/**
 * Zeitplan einer Fahrt, in zwei Takten:
 * - frei: Anfahrt aus `dauer_ms`, dann `halteMs` (länger bei Beweisblatt);
 * - im Takt der Stimme (jede Station hat `ankunftMs`): die Kamera fliegt in der Lücke vor dem Satz
 *   und steht beim ersten Wort; sie hält, bis der nächste Flug beginnt.
 * Zeigt die nächste Station dasselbe Bild, fliegt die Kamera nicht, sondern driftet weiter.
 */
export function zeitplan(eingaben: PlanEingabe[], e: Einstellungen): Plan {
  const liste = eingaben.filter((s) => s.kameras.length)
  const getaktet = liste.length > 0 && liste.every((s) => typeof s.ankunftMs === "number")
  return getaktet ? zeitplanImTakt(liste, e) : zeitplanFrei(liste, e)
}

/** Nur bei Einzelbildern: dieselbe Kamera wie vorher heißt weiterdriften statt neu anfahren. */
const weiterDriften = (vorher: PlanEingabe | undefined, s: PlanEingabe) =>
  !!vorher && vorher.kameras.length === 1 && s.kameras.length === 1 && gleicheKameras(vorher.kameras, s.kameras)

function planBauer(e: Einstellungen) {
  const bewegungen: Bewegung[] = []
  const halten = (t0: number, t1: number, kamera: Kamera, richtung: number) => {
    const drift = e.drift * ((t1 - t0) / 3000)
    bewegungen.push({ art: "halten", t0, t1, kamera, richtung, drift })
    return driftKamera(kamera, 1, richtung, drift, e.bildBreite)
  }
  const fliegen = (t0: number, t1: number, von: Kamera, nach: Kamera, rho?: number) => {
    bewegungen.push({ art: "flug", t0, t1, f: flug(von, nach, e.bildBreite, rho) })
  }
  return { bewegungen, halten, fliegen }
}

/** Frei: Anfahrt aus `dauer_ms`, dann `halteMs` (länger bei Beweisblatt); jeder Schwenk-Halt lang genug zum Lesen. */
function zeitplanFrei(liste: PlanEingabe[], e: Einstellungen): Plan {
  const { bewegungen, halten, fliegen } = planBauer(e)
  const stationen: PlanStation[] = []
  let t = 0
  let letzte: Kamera | null = null
  let fokusVorher: number[] | null = null
  liste.forEach((s, i) => {
    const start = t
    const weiter = weiterDriften(liste[i - 1], s)
    if (letzte && i > 0 && !weiter) {
      const dauer = Math.max(MIN_FAHRT_MS, s.fahrtMs)
      fliegen(t, t + dauer, letzte, s.kameras[0])
      t += dauer
    }
    const ankunft = t
    const beweisDauer = s.beweis ? BEWEIS_VORLAUF_MS + BEWEIS_REIN_MS + e.beweisMs + BEWEIS_RAUS_MS + 300 : 0
    const einspielerDauer = s.einspieler ? einspielerStationMs(s.einspieler.dauerMs, s.einspieler.freezeMs, s.einspieler.quelleGezeigt) : 0
    const anzahl = s.kameras.length
    const jeHalt = Math.max(SCHWENK_HALT_MIN_MS, (Math.max(e.halteMs, beweisDauer, einspielerDauer) - (anzahl - 1) * SCHWENK_MS) / anzahl)
    let kamera = weiter && letzte ? letzte : s.kameras[0]
    const richtung = i % 2 ? -1 : 1
    const standbild = t + jeHalt / 2
    for (let k = 0; k < anzahl; k++) {
      if (k > 0) {
        fliegen(t, t + SCHWENK_MS, kamera, s.kameras[k], 0.6)
        t += SCHWENK_MS
        kamera = s.kameras[k]
      }
      kamera = halten(t, t + jeHalt, kamera, richtung)
      t += jeHalt
    }
    const beweis = s.beweis
      ? { t0: ankunft + BEWEIS_VORLAUF_MS, t1: ankunft + BEWEIS_VORLAUF_MS + BEWEIS_REIN_MS + e.beweisMs + BEWEIS_RAUS_MS }
      : null
    const einblendung = s.einblendung?.gross ? { t0: ankunft + 120, t1: Math.min(t, Math.max(ankunft + 900, t - 200)) } : null
    stationen.push({ start, ankunft, ende: t, standbild, eingabe: s, fokusVorher, beweis, einblendung, einspieler: einspielerFenster(s, ankunft, t) })
    letzte = kamera
    fokusVorher = s.fokus
  })
  if (letzte) {
    halten(t, t + AUSKLANG_MS, letzte, 1)
    t += AUSKLANG_MS
  }
  return { dauerMs: t, bildBreite: e.bildBreite, stationen, bewegungen }
}

/** Kürzester Halt, bevor die Kamera wieder losfliegt, und kürzester Flug, der noch als Bewegung lesbar ist. */
const TAKT_HALT_MIN_MS = 300
const TAKT_FLUG_MIN_MS = 200

/**
 * Im Takt der Stimme: alle Zeiten sind absolut. Die Kamera steht bei `ankunftMs` jeder Station (die erste ab 0),
 * der Flug nimmt einen Teil der Lücke davor und ist nie länger als die Lücke; ein Schwenk teilt sich die
 * Haltezeit, statt sie zu sprengen. So läuft nichts auf, egal wie kurz die Sätze sind.
 */
function zeitplanImTakt(liste: PlanEingabe[], e: Einstellungen): Plan {
  const letzteAnkunft = liste[liste.length - 1].ankunftMs!
  const endeMs = e.endeMs ?? letzteAnkunft + e.halteMs
  if (endeMs <= letzteAnkunft) {
    throw new Error(`Die Tonspur (${endeMs} ms) endet vor dem letzten Satz (${letzteAnkunft} ms) — zeiten.json passt nicht.`)
  }
  const ankunft = liste.map((s, i) => (i === 0 ? 0 : s.ankunftMs!))
  for (let i = 1; i < ankunft.length; i++) {
    if (ankunft[i] <= ankunft[i - 1]) throw new Error(`Station ${i + 1} beginnt nicht nach Station ${i}.`)
  }
  const flugMs = liste.map((s, i) => {
    if (i === 0 || weiterDriften(liste[i - 1], s)) return 0
    const luecke = ankunft[i] - ankunft[i - 1]
    const wunsch = Math.min(Math.max(FLUG_MIN_MS, s.fahrtMs * 0.8), Math.max(FLUG_MIN_MS, luecke * FLUG_ANTEIL))
    // Steht davor ein O-Ton, darf der Flug dessen Clip, Standbild und Quelle nicht anschneiden.
    const vorher = liste[i - 1].einspieler
    const belegt = vorher ? einspielerStationMs(vorher.dauerMs, vorher.freezeMs, vorher.quelleGezeigt) : TAKT_HALT_MIN_MS
    const hoechstens = luecke - belegt
    // Ist die Lücke sehr knapp, fliegt die Kamera kürzer, aber sie kommt pünktlich an.
    return Math.round(hoechstens >= TAKT_FLUG_MIN_MS ? Math.min(wunsch, hoechstens) : Math.max(0, luecke * 0.5))
  })
  const dauerMs = endeMs + AUSKLANG_MS
  const { bewegungen, halten, fliegen } = planBauer(e)
  const stationen: PlanStation[] = []
  let letzte: Kamera | null = null
  let fokusVorher: number[] | null = null
  liste.forEach((s, i) => {
    const start = ankunft[i] - flugMs[i]
    const ende = i + 1 < liste.length ? ankunft[i + 1] - flugMs[i + 1] : dauerMs
    if (letzte && flugMs[i] > 0) fliegen(start, ankunft[i], letzte, s.kameras[0])
    const weiter = i > 0 && flugMs[i] === 0 && weiterDriften(liste[i - 1], s)
    let kamera = weiter && letzte ? letzte : s.kameras[0]
    const halt = ende - ankunft[i]
    const anzahl = s.kameras.length
    // Schwenk passt immer in die Haltezeit: die Schwenks werden kürzer, wenn es knapp ist.
    const schwenk = anzahl > 1 ? Math.min(SCHWENK_MS, (halt * 0.3) / (anzahl - 1)) : 0
    const jeHalt = (halt - (anzahl - 1) * schwenk) / anzahl
    const richtung = i % 2 ? -1 : 1
    let t = ankunft[i]
    const standbild = t + jeHalt / 2
    for (let k = 0; k < anzahl; k++) {
      if (k > 0) {
        fliegen(t, t + schwenk, kamera, s.kameras[k], 0.6)
        t += schwenk
        kamera = s.kameras[k]
      }
      const bis = k === anzahl - 1 ? ende : t + jeHalt
      kamera = halten(t, bis, kamera, richtung)
      t = bis
    }
    // Blatt und Einblendung bleiben innerhalb der Station, damit sie weich ausblenden, statt abzureißen.
    const beweis = s.beweis ? { t0: ankunft[i] + Math.min(300, halt * 0.1), t1: Math.max(ankunft[i] + Math.min(300, halt * 0.1) + 1, ende - 150) } : null
    const einblendung = s.einblendung?.gross
      ? { t0: ankunft[i] + Math.min(120, halt * 0.1), t1: Math.min(ende, Math.max(ankunft[i] + 900, ende - 200)) }
      : null
    stationen.push({
      start, ankunft: ankunft[i], ende, standbild, eingabe: s, fokusVorher, beweis, einblendung,
      einspieler: einspielerFenster(s, ankunft[i], ende),
    })
    letzte = kamera
    fokusVorher = s.fokus
  })
  return { dauerMs, bildBreite: e.bildBreite, stationen, bewegungen }
}

function driftKamera(k: Kamera, p: number, richtung: number, drift: number, bildBreite: number): Kamera {
  const w = weich(k01(p))
  return {
    cx: k.cx + richtung * w * 0.012 * (bildBreite / k.zoom),
    cy: k.cy,
    zoom: k.zoom * (1 + drift * w),
  }
}

// ─── Das Bild zu einer Zeit ─────────────────────────────────────────────────

export interface Bild {
  kamera: Kamera
  station: number
  /** Scheinwerfer: Übergang von `alt` nach `neu`, p von 0 bis 1. */
  fokus: { alt: number[] | null; neu: number[] | null; p: number }
  /** Fortschritt, mit dem neu beleuchtete Fäden sich ziehen. */
  fadenZug: number
  beweis: { quelle: number; zitat?: string; rein: number; raus: number } | null
  stichwort: { text: string; deckkraft: number }
  einblendung: (Einblendung & { rein: number; raus: number }) | null
  /** Welches Bild des Einspielers (1 …), Ein-/Ausblenden, Quellenmarke. */
  einspieler: { station: number; bild: number; rein: number; raus: number; quelle: string; untertitel?: string } | null
}

export function bildZu(plan: Plan, zeit: number): Bild {
  const t = Math.min(Math.max(0, zeit), plan.dauerMs)
  const bew = plan.bewegungen.find((b) => t >= b.t0 && t < b.t1) ?? plan.bewegungen[plan.bewegungen.length - 1]
  let kamera: Kamera = { cx: 0, cy: 0, zoom: 1 }
  if (bew) {
    const p = bew.t1 > bew.t0 ? k01((t - bew.t0) / (bew.t1 - bew.t0)) : 1
    kamera = bew.art === "flug"
      ? bew.f(sanft(p))
      : driftKamera(bew.kamera, p, bew.richtung, bew.drift, plan.bildBreite)
  }
  let i = plan.stationen.findIndex((s) => t >= s.start && t < s.ende)
  if (i < 0) i = plan.stationen.length - 1
  const s = plan.stationen[i]
  if (!s) {
    return { kamera, station: -1, fokus: { alt: null, neu: null, p: 1 }, fadenZug: 1, beweis: null, stichwort: { text: "", deckkraft: 0 }, einblendung: null, einspieler: null }
  }
  const fokusP = i === 0 ? 1 : weich(k01((t - s.start) / SCHEINWERFER_MS))
  const zugStart = s.start + (s.ankunft - s.start) * 0.5
  const fadenZug = i === 0 ? 1 : sanft(k01((t - zugStart) / FADEN_ZUG_MS))
  const beweis = s.beweis && s.eingabe.beweis && t >= s.beweis.t0 && t < s.beweis.t1
    ? {
      ...s.eingabe.beweis,
      rein: sanft(k01((t - s.beweis.t0) / BEWEIS_REIN_MS)),
      raus: sanft(k01((t - (s.beweis.t1 - BEWEIS_RAUS_MS)) / BEWEIS_RAUS_MS)),
    }
    : null
  const stichDeck = s.eingabe.stichwort
    ? Math.min(weich(k01((t - s.ankunft + 200) / 400)), 1 - weich(k01((t - s.ende + 400) / 400)))
    : 0
  const einblendung = s.einblendung && s.eingabe.einblendung && t >= s.einblendung.t0 && t < s.einblendung.t1
    ? {
      ...s.eingabe.einblendung,
      rein: sanft(k01((t - s.einblendung.t0) / EINBLENDUNG_MS)),
      raus: sanft(k01((t - (s.einblendung.t1 - EINBLENDUNG_MS)) / EINBLENDUNG_MS)),
    }
    : null
  const ep = s.einspieler
  const einspieler = ep && s.eingabe.einspieler && t >= ep.t0 - EINSPIELER_BLENDE_MS && t < ep.t1
    ? {
      station: i,
      // Bild für Bild aus dem Ausschnitt; nach dem Ende steht das letzte Bild (Standbild).
      bild: Math.max(1, Math.min(Math.round(s.eingabe.einspieler.dauerMs / (1000 / EINSPIELER_FPS)), Math.floor((Math.max(0, t - ep.t0)) / (1000 / EINSPIELER_FPS)) + 1)),
      rein: sanft(k01((t - (ep.t0 - EINSPIELER_BLENDE_MS)) / EINSPIELER_BLENDE_MS)),
      raus: sanft(k01((t - (ep.t1 - EINSPIELER_BLENDE_MS)) / EINSPIELER_BLENDE_MS)),
      quelle: s.eingabe.einspieler.quelle,
      untertitel: s.eingabe.einspieler.untertitel,
    }
    : null
  return {
    kamera, station: i, fokus: { alt: s.fokusVorher, neu: s.eingabe.fokus, p: fokusP }, fadenZug, beweis,
    stichwort: { text: s.eingabe.stichwort, deckkraft: stichDeck }, einblendung, einspieler,
  }
}

/** Wie hell eine Karte im Scheinwerfer ist (0 = gedimmt, 1 = voll). */
export function licht(fokus: Bild["fokus"], id: number): number {
  const an = (menge: number[] | null) => (menge === null || menge.includes(id) ? 1 : 0)
  return an(fokus.alt) + (an(fokus.neu) - an(fokus.alt)) * fokus.p
}

/** Wie stark ein Faden hervorgehoben ist (beide Enden im Scheinwerfer, nicht im Überblick). */
export function fadenLicht(fokus: Bild["fokus"], von: number, nach: number): { hell: number; hervor: number; neu: boolean } {
  const hervor = (menge: number[] | null) => (menge !== null && menge.includes(von) && menge.includes(nach) ? 1 : 0)
  const hell = (menge: number[] | null) => (menge === null || (menge.includes(von) && menge.includes(nach)) ? 1 : 0)
  return {
    hell: hell(fokus.alt) + (hell(fokus.neu) - hell(fokus.alt)) * fokus.p,
    hervor: hervor(fokus.alt) + (hervor(fokus.neu) - hervor(fokus.alt)) * fokus.p,
    neu: hervor(fokus.neu) === 1 && hervor(fokus.alt) === 0,
  }
}
