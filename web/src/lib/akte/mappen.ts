// Mappen auf der Wand: Brotkrumen, Bündel-Aussehen, Eintauchen. Reine Helfer, getestet in mappen.test.ts.

import { VERBINDUNG_NAMEN, type Buendel, type BoardVerweis } from "./typen"

/** Feste Größe einer Aktenmappe auf der Wand (zwei Rasterzellen, wie layout.py MAPPE_B/MAPPE_H). */
export const MAPPE_B = 560
export const MAPPE_H = 380

const SLUG = /^[a-z0-9][a-z0-9-]{0,219}$/

/**
 * Der Weg von oben bis vor die aktuelle Wand, als Slugs. Aus `?von=a,b` (so kam man her);
 * ohne Angabe die erste Eltern-Wand. Unbrauchbare Teile fallen weg.
 */
export function pfadLesen(von: string | null | undefined, eltern: BoardVerweis[] = [], aktuell = ""): string[] {
  const aus = (von ?? "").split(",").map((s) => s.trim()).filter((s) => SLUG.test(s) && s !== aktuell)
  if (aus.length) return [...new Set(aus)].slice(-8)
  return eltern.length ? [eltern[0].slug] : []
}

/** Adresse einer Mappe: der bisherige Weg plus die Wand, auf der man gerade steht. */
export function mappenAdresse(ziel: string, pfad: string[], aktuell: string): string {
  const weg = [...pfad, aktuell].filter(Boolean)
  return `/akte/${ziel}${weg.length ? `?von=${weg.join(",")}` : ""}`
}

/** Zurück eine Ebene: auf der Elternwand startet die Kamera nah an der Mappe, aus der man kommt. */
export function zurueckAdresse(pfad: string[], aktuell: string): string | null {
  if (!pfad.length) return null
  const eltern = pfad[pfad.length - 1]
  const davor = pfad.slice(0, -1)
  const q = new URLSearchParams()
  if (davor.length) q.set("von", davor.join(","))
  q.set("aus", aktuell)
  return `/akte/${eltern}?${q.toString()}`
}

/** Strichbreite eines Bündels: wächst mit der Zahl der Fäden, gedeckelt. */
export function buendelBreite(n: number): number {
  return Math.min(12, 3 + 2 * Math.log2(Math.max(1, n)))
}

/** „23 Fäden“ und die häufigsten Arten, z. B. „Finanzierung 7 · Amt 5“. */
export function buendelText(b: Pick<Buendel, "faeden" | "je_typ">): { zahl: string; typen: string } {
  const n = b.faeden.length
  return {
    zahl: `${n} ${n === 1 ? "Faden" : "Fäden"}`,
    typen: b.je_typ.map(([t, k]) => `${VERBINDUNG_NAMEN[t]?.split(" / ")[0] ?? t} ${k}`).join(" · "),
  }
}

/** Kamera, die ein Rechteck (Wandkoordinaten) bildschirmfüllend zeigt — für das Hineinfahren in eine Mappe. */
export function eintauchKamera(r: { x: number; y: number; b: number; h: number }, schirm: { b: number; h: number }, zoomMax = 3) {
  const zoom = Math.min(zoomMax, Math.min(schirm.b / r.b, schirm.h / r.h))
  return { x: r.x + r.b / 2, y: r.y + r.h / 2, zoom }
}
