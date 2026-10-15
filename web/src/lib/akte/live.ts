// Live-Aktualisierung der Wand: ein billiger Fingerabdruck (`GET boards/<slug>/stand/`) sagt, ob sich etwas getan
// hat. Erst dann lädt die Wand neu – und zwar so, dass Kamera, Auswahl und offene Formulare bleiben.
//
// Alles hier ist rein bzw. bekommt Zeitgeber und Dokument hineingereicht, damit die Tests mit falschen Uhren laufen.

import type { Wand } from "./typen"

// ─── Abfrage des Stands ──────────────────────────────────────────────────────

/** Abstand der Abfragen bei sichtbarem Tab (Redaktion). */
export const STAND_INTERVALL_MS = 4000
/** Leser (Mitglieder, Besucher ohne Konto): Ihr Stand ändert sich nur mit Unterschriebenem, und jede Änderung lädt
 *  die ganze Wand aus ihrem gedrosselten Lese-Kontingent. Eine öffentliche Wand mit vielen Besuchern soll nicht alle
 *  4 s je Tab einen Fingerabdruck rechnen. */
export const LESER_INTERVALL_MS = 30_000
/** Nach Fehlern wird der Abstand verdoppelt, höchstens bis hierhin. */
const STAND_HOECHSTENS_MS = 60_000

type Ereignisquelle = {
  addEventListener: (typ: string, f: () => void) => void
  removeEventListener: (typ: string, f: () => void) => void
}

export interface StandAbfrageOptionen {
  /** Holt den aktuellen Stand; das Signal bricht die Anfrage beim Aufräumen ab. */
  holen: (signal: AbortSignal) => Promise<string>
  /** Wird gerufen, wenn sich der Stand gegenüber dem zuletzt gesehenen geändert hat (nicht beim ersten Mal). */
  geaendert: (stand: string) => void
  /** Abstand bei sichtbarem Tab; `null` = nur beim Zurückkehren (Fokus, Tab wieder sichtbar). */
  intervallMs?: number | null
  /** Mindestabstand zwischen zwei Abfragen: Fokus und Sichtbarkeit feuern oft gemeinsam. */
  mindestAbstandMs?: number
  /** true = für immer aufhören (Endpunkt fehlt, keine Leserechte). Sonst wird es später wieder versucht. */
  aufgeben?: (fehler: unknown) => boolean
  dokument?: Ereignisquelle & { visibilityState: DocumentVisibilityState }
  fenster?: Ereignisquelle
  jetzt?: () => number
}

/**
 * Fragt den Stand ab, solange der Tab sichtbar ist, und sofort, wenn er wieder sichtbar wird oder den Fokus bekommt.
 * Es läuft höchstens ein Zeitgeber und höchstens eine Anfrage zugleich. Gibt die Aufräum-Funktion zurück: Sie hält
 * den Zeitgeber an, entfernt die Horcher und bricht eine laufende Anfrage ab; danach meldet nichts mehr eine Änderung.
 */
export function standAbfragen(o: StandAbfrageOptionen): () => void {
  const dok = o.dokument ?? document
  const fen = o.fenster ?? window
  const jetzt = o.jetzt ?? Date.now
  const intervall = o.intervallMs === undefined ? STAND_INTERVALL_MS : o.intervallMs
  const mindestAbstand = o.mindestAbstandMs ?? 1000

  let stand: string | null = null
  let zeitgeber: ReturnType<typeof setTimeout> | null = null
  let laufend: AbortController | null = null
  let fehler = 0
  let zuletzt = Number.NEGATIVE_INFINITY
  let aus = false

  const sichtbar = () => dok.visibilityState === "visible"

  function anhalten() {
    if (zeitgeber !== null) clearTimeout(zeitgeber)
    zeitgeber = null
  }

  // Immer nur ein Zeitgeber: Wer neu plant, räumt den alten ab.
  function planen() {
    anhalten()
    if (aus || intervall === null || !sichtbar()) return
    const warten = fehler ? Math.min(intervall * 2 ** fehler, STAND_HOECHSTENS_MS) : intervall
    zeitgeber = setTimeout(() => {
      zeitgeber = null
      void pruefen(true)
    }, warten)
  }

  // Nach jeder frühen Rückkehr: Läuft weder ein Zeitgeber noch eine Anfrage, den Takt neu ansetzen. Sonst bliebe die
  // Abfrage nach „verborgen, gleich wieder sichtbar“ (Fokus innerhalb des Mindestabstands) für immer stehen.
  function taktSichern() {
    if (zeitgeber === null && !laufend) planen()
  }

  // Eine abgebrochene Anfrage gibt ihren Platz zuerst frei; sonst hielte `taktSichern` sie für noch laufend und plante
  // nichts (CR-5).
  function abgebrochen(ac: AbortController) {
    if (laufend === ac) laufend = null
    taktSichern()
  }

  async function pruefen(vomZeitgeber = false) {
    if (aus) return
    if (laufend || !sichtbar()) { taktSichern(); return }
    // Zu dicht hinter der letzten Abfrage (Fokus + Sichtbarkeit zugleich): nichts abfragen, der Takt läuft weiter.
    if (!vomZeitgeber && jetzt() - zuletzt < mindestAbstand) { taktSichern(); return }
    zuletzt = jetzt()
    const ac = new AbortController()
    laufend = ac
    try {
      const neu = await o.holen(ac.signal)
      if (aus) return
      if (ac.signal.aborted) { abgebrochen(ac); return }
      fehler = 0
      const vorher = stand
      stand = neu
      if (vorher !== null && neu !== vorher) o.geaendert(neu)
    } catch (e) {
      if (aus) return
      if (ac.signal.aborted) { abgebrochen(ac); return }
      if (o.aufgeben?.(e)) {
        stoppen()
        return
      }
      fehler = Math.min(fehler + 1, 4)
    } finally {
      if (laufend === ac) laufend = null
    }
    planen()
  }

  // Verborgen: Takt anhalten und eine laufende Anfrage abbrechen (ihr Ergebnis sähe ohnehin niemand). Der Stand
  // bleibt der zuletzt gesehene; eine Änderung fällt beim nächsten Sichtbarwerden auf.
  const beiSichtbarkeit = () => {
    if (sichtbar()) void pruefen()
    else {
      anhalten()
      laufend?.abort()
    }
  }
  const beiFokus = () => void pruefen()

  function stoppen() {
    if (aus) return
    aus = true
    anhalten()
    laufend?.abort()
    laufend = null
    dok.removeEventListener("visibilitychange", beiSichtbarkeit)
    fen.removeEventListener("focus", beiFokus)
  }

  dok.addEventListener("visibilitychange", beiSichtbarkeit)
  fen.addEventListener("focus", beiFokus)
  // Erste Abfrage: legt nur den Ausgangsstand fest.
  void pruefen()
  return stoppen
}

// ─── Was hat sich auf der Wand geändert? ────────────────────────────────────

export interface WandUnterschied {
  geaendert: boolean
  /** Namen der neuen Karten (in der Reihenfolge der Wand). */
  neueKarten: string[]
  /** IDs der neuen Karten-Platzierungen (Knoten `k-<id>`), zum Hervorheben. */
  neueKartenIds: number[]
  neueFaeden: number
  /** IDs der Fäden, die es schon gab und die sich geändert haben. */
  geaenderteFaeden: number[]
  /** Karten, Fäden, Zettel, Rahmen … die verschwunden sind. */
  entfernt: number
  /** Alles andere: verschobene oder geänderte Karten, Zettel, Rahmen, Beweise, Mappen, Fahrten, Board. */
  sonst: number
}

const gleich = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

function listeVergleichen<T extends { id: number }>(alt: T[] | undefined, neu: T[] | undefined) {
  const vorher = new Map((alt ?? []).map((x) => [x.id, x]))
  const nachher = new Map((neu ?? []).map((x) => [x.id, x]))
  const dazu: T[] = []
  const anders: T[] = []
  for (const [id, x] of nachher) {
    const v = vorher.get(id)
    if (!v) dazu.push(x)
    else if (!gleich(v, x)) anders.push(x)
  }
  const weg = [...vorher.keys()].filter((id) => !nachher.has(id)).length
  return { dazu, anders, weg }
}

/** Vergleicht zwei Stände der Wand. Ohne alten Stand gilt alles als geändert. */
export function wandUnterschied(alt: Wand | null | undefined, neu: Wand): WandUnterschied {
  if (!alt) {
    return {
      geaendert: true, neueKarten: [], neueKartenIds: [], neueFaeden: 0, geaenderteFaeden: [], entfernt: 0, sonst: 1,
    }
  }
  const karten = listeVergleichen(alt.karten, neu.karten)
  const faeden = listeVergleichen(alt.faeden, neu.faeden)
  let entfernt = karten.weg + faeden.weg
  let sonst = karten.anders.length
  for (const [a, b] of [
    [alt.zettel, neu.zettel], [alt.rahmen, neu.rahmen], [alt.beweise, neu.beweise], [alt.fahrten, neu.fahrten],
    [alt.mappen, neu.mappen], [alt.buendel_faeden, neu.buendel_faeden],
  ] as [{ id: number }[] | undefined, { id: number }[] | undefined][]) {
    const u = listeVergleichen(a, b)
    sonst += u.dazu.length + u.anders.length
    entfernt += u.weg
  }
  // Was keine eigene Liste mit IDs hat, zählt als eine Änderung.
  const rest = (w: Wand) => [w.board, w.buendel, w.ausser_haus, w.auch_in, w.eltern, w.gelenke, w.darf_bearbeiten]
  if (!gleich(rest(alt), rest(neu))) sonst += 1
  const u: WandUnterschied = {
    geaendert: false,
    neueKarten: karten.dazu.map((k) => k.entitaet_detail.name),
    neueKartenIds: karten.dazu.map((k) => k.id),
    neueFaeden: faeden.dazu.length,
    geaenderteFaeden: faeden.anders.map((f) => f.id),
    entfernt,
    sonst,
  }
  u.geaendert = !!(u.neueKarten.length || u.neueFaeden || u.geaenderteFaeden.length || u.entfernt || u.sonst)
  return u
}

const anzahl = (n: number, eins: string, viele: string) => `${n} ${n === 1 ? eins : viele}`

/** Kurzer Satz für den Hinweis über einem offenen Formular: „Neu auf der Wand: Karte „Thorn“, 2 Fäden“. */
export function unterschiedText(u: WandUnterschied): string {
  const teile: string[] = []
  const n = u.neueKarten.length
  if (n === 1) teile.push(`Karte „${u.neueKarten[0]}“`)
  else if (n === 2) teile.push(`Karten „${u.neueKarten[0]}“ und „${u.neueKarten[1]}“`)
  else if (n > 2) teile.push(`${n} Karten („${u.neueKarten[0]}“, „${u.neueKarten[1]}“ …)`)
  if (u.neueFaeden) teile.push(anzahl(u.neueFaeden, "Faden", "Fäden"))
  if (u.geaenderteFaeden.length) teile.push(`${anzahl(u.geaenderteFaeden.length, "Faden", "Fäden")} geändert`)
  if (u.entfernt) teile.push(`${u.entfernt} entfernt`)
  if (u.sonst) teile.push(teile.length ? "weitere Änderungen" : "Änderungen an der Wand")
  return `Neu auf der Wand: ${teile.join(", ") || "Änderungen"}`
}

// ─── Wann darf eine neue Fassung auf die Wand? ───────────────────────────────

export type LiveEntscheidung = "uebernehmen" | "hinweis" | "warten"

/** Sieht man den Unterschied auf der Wand (Karten oder Fäden neu, geändert, weg)? Verschobenes, Zettel, Beweise
 *  und Sicherungen kommen still mit, ohne Hinweis. */
export function sichtbarerUnterschied(u: WandUnterschied): boolean {
  return !!(u.neueKarten.length || u.neueFaeden || u.geaenderteFaeden.length || u.entfernt)
}

/**
 * Offene Formulare werden nie überschrieben: Dann gibt es nur einen Hinweis zum Übernehmen – und den nur, wenn man den
 * Unterschied auf der Wand sieht; sonst wartet die neue Fassung still. Während jemand eine Karte zieht oder eine
 * Aufnahme läuft, wartet sie ebenfalls, bis das vorbei ist.
 */
export function liveEntscheidung(lage: {
  formularOffen: boolean
  zieht: boolean
  aufnahme: boolean
  /** Ist der Unterschied sichtbar? Ohne Angabe: ja. */
  sichtbar?: boolean
}): LiveEntscheidung {
  if (lage.aufnahme || lage.zieht) return "warten"
  if (lage.formularOffen) return lage.sichtbar === false ? "warten" : "hinweis"
  return "uebernehmen"
}

// ─── Positionen, die noch gespeichert werden, nicht zurückspringen lassen ───

export type OffenePosition = { art: string; id: number; x: number; y: number; breite?: number; hoehe?: number }

/**
 * Legt Positionen, die der Mensch gerade gezogen hat und die noch unterwegs zum Server sind, über die frisch geladene
 * Wand. Sonst spränge eine eben abgelegte Karte kurz zurück, bis der Server die neue Lage kennt.
 */
export function mitPositionen<T extends Wand>(w: T, offen: Map<string, OffenePosition>): T {
  if (!offen.size) return w
  const lage = (art: string, id: number) => offen.get(`${art}-${id}`)
  const setzen = <X extends { id: number; x: number; y: number }>(art: string, liste: X[]): X[] =>
    liste.map((x) => {
      const p = lage(art, x.id)
      return p ? { ...x, x: p.x, y: p.y } : x
    })
  return {
    ...w,
    karten: setzen("karte", w.karten),
    zettel: setzen("zettel", w.zettel),
    beweise: setzen("beweis", w.beweise),
    mappen: w.mappen ? setzen("mappe", w.mappen) : w.mappen,
    rahmen: w.rahmen.map((r) => {
      const p = lage("rahmen", r.id)
      return p ? { ...r, x: p.x, y: p.y, breite: p.breite ?? r.breite, hoehe: p.hoehe ?? r.hoehe } : r
    }),
  }
}
