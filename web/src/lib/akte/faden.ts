// Reine Helfer der Wand: wie ein Faden hängt und aussieht, wie [[Links]] gelesen werden.

import type { Aussageart, Verbindung } from "./typen"

export const FARBEN = {
  grund: "#0A0A0F",
  papier: "#EDE6D8",
  tinte: "#F2F7FB",
  tinteDunkel: "#141318",
  gedaempft: "#8A94A0",
  linie: "#222636",
  rot: "#FF1744",
  gold: "#f0c674",
  ocker: "#FFB300",
} as const

export type RahmenStil = { rand: string; flaeche: string; strich: "dashed" | "solid"; titel: string; plakette: string | null }

/** Rahmen ohne Farbe: goldene Strichlinie. Mit Farbe (#RRGGBB) wird er zum Schild: durchgezogener Rand,
 *  Titel weiß auf einer Plakette in dieser Farbe. Alles andere gilt als keine Farbe (kein CSS aus der Datenbank). */
export function rahmenStil(farbe?: string | null): RahmenStil {
  if (farbe && /^#[0-9a-fA-F]{6}$/.test(farbe)) {
    return { rand: farbe, flaeche: `${farbe}14`, strich: "solid", titel: "#FFFFFF", plakette: farbe }
  }
  return { rand: `${FARBEN.gold}88`, flaeche: `${FARBEN.gold}08`, strich: "dashed", titel: FARBEN.gold, plakette: null }
}

export interface FadenStil {
  farbe: string
  strich: string | undefined
  breite: number
  stempel: string | null
}

export function fadenStil(art: Aussageart): FadenStil {
  switch (art) {
    case "verdacht":
      return { farbe: FARBEN.rot, strich: "10 8", breite: 2.5, stempel: "VERDACHT" }
    case "meinung":
      return { farbe: FARBEN.ocker, strich: "2 6", breite: 2.5, stempel: "MEINUNG" }
    default:
      return { farbe: FARBEN.rot, strich: undefined, breite: 3, stempel: null }
  }
}

/**
 * Ein Faden hängt durch wie eine echte Schnur zwischen zwei Stecknadeln:
 * quadratische Kurve, deren Mittelpunkt um einen Teil der Länge nach unten sackt.
 */
export function durchhang(
  sx: number, sy: number, tx: number, ty: number, staerke = 0.12,
): { pfad: string; mitteX: number; mitteY: number } {
  const laenge = Math.hypot(tx - sx, ty - sy)
  const sack = Math.min(laenge * staerke, 120)
  const kx = (sx + tx) / 2
  const ky = (sy + ty) / 2 + sack
  // Punkt der Kurve bei t = 0,5 — dort sitzt das Etikett.
  const mitteX = 0.25 * sx + 0.5 * kx + 0.25 * tx
  const mitteY = 0.25 * sy + 0.5 * ky + 0.25 * ty
  return { pfad: `M ${sx},${sy} Q ${kx},${ky} ${tx},${ty}`, mitteX, mitteY }
}

/**
 * Zeitraum eines Fadens in Kurzform: „seit 2003“, „2003–2016“, „2026“. Leer, wenn der Start fehlt oder das Startjahr schon
 * im Text des Fadens steht (`text`), und bei gleichem Anfangs- und Endjahr nur ein Jahr (sonst stünde
 * „2026–2026“ oder „(2019–2026) 2019–2026“ im Video).
 */
export function zeitraum(v: Pick<Verbindung, "start" | "ende" | "aktuell">, text?: string): string {
  const jahr = (d: string | null) => (d ? d.slice(0, 4) : "")
  const von = jahr(v.start)
  const bis = jahr(v.ende)
  // ohne Text (Listen, Lese-Ansicht): fehlender Start bleibt „?“ wie bisher; an einem Etikett lieber nichts
  if (!von) return text === undefined ? (bis ? `?–${bis}` : "?") : ""
  const steht = (j: string) => !!text && new RegExp(`(?<!\\d)${j}(?!\\d)`).test(text)
  if (steht(von) && (!bis || bis === von || steht(bis) || v.aktuell)) return ""
  if (v.aktuell) return `seit ${von}`
  if (bis && bis !== von) return `${von}–${bis}`
  return von
}

export type NotizTeil = { art: "text"; text: string } | { art: "link"; ziel: string; text: string }

/** Zerlegt Obsidian-Text in Text und [[Ziel|Anzeige]]-Links. */
export function wikilinks(md: string): NotizTeil[] {
  const teile: NotizTeil[] = []
  const muster = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g
  let zuletzt = 0
  for (const treffer of md.matchAll(muster)) {
    const i = treffer.index ?? 0
    if (i > zuletzt) teile.push({ art: "text", text: md.slice(zuletzt, i) })
    const ziel = treffer[1].trim()
    teile.push({ art: "link", ziel, text: (treffer[2] ?? ziel).trim() })
    zuletzt = i + treffer[0].length
  }
  if (zuletzt < md.length) teile.push({ art: "text", text: md.slice(zuletzt) })
  return teile
}
