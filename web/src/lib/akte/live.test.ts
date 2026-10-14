// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  liveEntscheidung, mitPositionen, sichtbarerUnterschied, standAbfragen, STAND_INTERVALL_MS, unterschiedText,
  wandUnterschied,
  type OffenePosition,
} from "./live"
import type { Karte, Verbindung, Wand } from "./typen"

// ─── Ein Dokument und ein Fenster zum Umschalten, ohne Browser ──────────────

function umgebung(sichtbar = true) {
  const dokument = Object.assign(new EventTarget(), { visibilityState: (sichtbar ? "visible" : "hidden") as DocumentVisibilityState })
  const fenster = new EventTarget()
  return {
    dokument,
    fenster,
    verbergen() { dokument.visibilityState = "hidden"; dokument.dispatchEvent(new Event("visibilitychange")) },
    zeigen() { dokument.visibilityState = "visible"; dokument.dispatchEvent(new Event("visibilitychange")) },
    fokus() { fenster.dispatchEvent(new Event("focus")) },
  }
}

/** Ein Server, dessen Stand sich von außen setzen lässt; zählt die Abfragen. */
function server(start = "s1") {
  let stand = start
  const holen = vi.fn(async () => stand)
  return { holen, setze: (s: string) => { stand = s } }
}

describe("standAbfragen", () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it("fragt sofort und dann alle 4 s, solange der Tab sichtbar ist", async () => {
    const u = umgebung()
    const s = server()
    const stopp = standAbfragen({ holen: s.holen, geaendert: vi.fn(), dokument: u.dokument, fenster: u.fenster })
    await vi.advanceTimersByTimeAsync(0)
    expect(s.holen).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS - 1)
    expect(s.holen).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(s.holen).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS * 3)
    expect(s.holen).toHaveBeenCalledTimes(5)
    stopp()
  })

  it("meldet nur echte Änderungen, nicht den ersten Stand", async () => {
    const u = umgebung()
    const s = server()
    const geaendert = vi.fn()
    const stopp = standAbfragen({ holen: s.holen, geaendert, dokument: u.dokument, fenster: u.fenster })
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS * 2)
    expect(geaendert).not.toHaveBeenCalled()
    s.setze("s2")
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS)
    expect(geaendert).toHaveBeenCalledTimes(1)
    expect(geaendert).toHaveBeenCalledWith("s2")
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS * 2)
    expect(geaendert).toHaveBeenCalledTimes(1)
    stopp()
  })

  it("pausiert bei verborgenem Tab und fragt beim Zurückkommen sofort", async () => {
    const u = umgebung()
    const s = server()
    const stopp = standAbfragen({ holen: s.holen, geaendert: vi.fn(), dokument: u.dokument, fenster: u.fenster })
    await vi.advanceTimersByTimeAsync(0)
    u.verbergen()
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS * 10)
    expect(s.holen).toHaveBeenCalledTimes(1)
    u.zeigen()
    await vi.advanceTimersByTimeAsync(0)
    expect(s.holen).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS)
    expect(s.holen).toHaveBeenCalledTimes(3)
    stopp()
  })

  it("verliert den Takt nicht, wenn der Tab kurz verborgen und gleich wieder sichtbar ist (CR4)", async () => {
    const u = umgebung()
    const s = server()
    const stopp = standAbfragen({ holen: s.holen, geaendert: vi.fn(), dokument: u.dokument, fenster: u.fenster })
    await vi.advanceTimersByTimeAsync(0)
    expect(s.holen).toHaveBeenCalledTimes(1)
    // Innerhalb des Mindestabstands: verborgen (Takt hält an), sofort wieder sichtbar und Fokus (keine Abfrage) …
    await vi.advanceTimersByTimeAsync(200)
    u.verbergen()
    u.zeigen()
    u.fokus()
    await vi.advanceTimersByTimeAsync(0)
    expect(s.holen).toHaveBeenCalledTimes(1)
    // … aber der Takt läuft weiter.
    expect(vi.getTimerCount()).toBe(1)
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS)
    expect(s.holen).toHaveBeenCalledTimes(2)
    stopp()
  })

  it("bricht beim Verbergen ab und plant danach wieder, auch wenn der Tab sofort zurückkommt (CR-5)", async () => {
    const u = umgebung()
    let n = 0
    const holen = vi.fn((signal: AbortSignal) => {
      n++
      if (n === 1) return Promise.resolve("s1")
      // Zweite Abfrage hängt, bis sie abgebrochen wird; der Abbruch meldet sich erst nach 50 ms.
      return new Promise<string>((_, nein) => {
        signal.addEventListener("abort", () => setTimeout(() => nein(new DOMException("abgebrochen", "AbortError")), 50))
      })
    })
    const stopp = standAbfragen({ holen, geaendert: vi.fn(), dokument: u.dokument, fenster: u.fenster })
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS)
    expect(holen).toHaveBeenCalledTimes(2)
    u.verbergen()   // bricht die hängende Abfrage ab
    u.zeigen()      // sofort zurück: die alte Anfrage gilt noch als laufend
    await vi.advanceTimersByTimeAsync(60)
    // Nach dem Abbruch ist der Platz frei und ein neuer Takt geplant.
    expect(vi.getTimerCount()).toBe(1)
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS)
    expect(holen).toHaveBeenCalledTimes(3)
    stopp()
  })

  it("startet in einem verborgenen Tab gar nicht erst", async () => {
    const u = umgebung(false)
    const s = server()
    const stopp = standAbfragen({ holen: s.holen, geaendert: vi.fn(), dokument: u.dokument, fenster: u.fenster })
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS * 5)
    expect(s.holen).not.toHaveBeenCalled()
    stopp()
  })

  it("fragt beim Fokus sofort, aber nicht doppelt kurz hintereinander", async () => {
    const u = umgebung()
    const s = server()
    const stopp = standAbfragen({ holen: s.holen, geaendert: vi.fn(), dokument: u.dokument, fenster: u.fenster })
    await vi.advanceTimersByTimeAsync(1500)
    u.fokus()
    await vi.advanceTimersByTimeAsync(0)
    expect(s.holen).toHaveBeenCalledTimes(2)
    // Fokus und Sichtbarkeit zugleich (Tab-Wechsel): nur eine Abfrage
    u.fokus()
    u.zeigen()
    await vi.advanceTimersByTimeAsync(0)
    expect(s.holen).toHaveBeenCalledTimes(2)
    // Der Takt beginnt nach der Fokus-Abfrage neu: kein zweiter Zeitgeber daneben
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS)
    expect(s.holen).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1)
    expect(vi.getTimerCount()).toBe(1)
    stopp()
  })

  it("lässt nie zwei Anfragen zugleich laufen", async () => {
    const u = umgebung()
    let freigeben: (s: string) => void = () => undefined
    const holen = vi.fn(() => new Promise<string>((ok) => { freigeben = ok }))
    const stopp = standAbfragen({ holen, geaendert: vi.fn(), dokument: u.dokument, fenster: u.fenster, mindestAbstandMs: 0 })
    await vi.advanceTimersByTimeAsync(0)
    u.fokus()
    u.fokus()
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS * 3)
    expect(holen).toHaveBeenCalledTimes(1)
    freigeben("s1")
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS)
    expect(holen).toHaveBeenCalledTimes(2)
    stopp()
  })

  it("räumt sauber auf: kein Zeitgeber, keine Horcher, keine Meldung danach", async () => {
    const u = umgebung()
    const s = server()
    const geaendert = vi.fn()
    const signale: AbortSignal[] = []
    let freigeben: (st: string) => void = () => undefined
    const holen = vi.fn((sig: AbortSignal) => {
      signale.push(sig)
      return s.holen().then((st) => new Promise<string>((ok) => { freigeben = () => ok(st) }))
    })
    const stopp = standAbfragen({ holen, geaendert, dokument: u.dokument, fenster: u.fenster })
    await vi.advanceTimersByTimeAsync(0)
    freigeben("s1")
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS)
    expect(holen).toHaveBeenCalledTimes(2)
    s.setze("s2")
    stopp()
    expect(signale.at(-1)?.aborted).toBe(true)
    freigeben("s2")
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS * 5)
    u.fokus()
    u.zeigen()
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS * 5)
    expect(holen).toHaveBeenCalledTimes(2)
    expect(geaendert).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it("gibt auf, wenn der Endpunkt fehlt, und wird nach Netzfehlern langsamer", async () => {
    const u = umgebung()
    const fehlt = Object.assign(new Error("404"), { status: 404 })
    const holen = vi.fn(async () => { throw fehlt })
    standAbfragen({
      holen, geaendert: vi.fn(), dokument: u.dokument, fenster: u.fenster,
      aufgeben: (e) => (e as { status?: number }).status === 404,
    })
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS * 10)
    expect(holen).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)

    const netz = vi.fn(async () => { throw new Error("Netz weg") })
    const stopp = standAbfragen({ holen: netz, geaendert: vi.fn(), dokument: u.dokument, fenster: u.fenster, aufgeben: () => false })
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS)
    expect(netz).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS)
    expect(netz).toHaveBeenCalledTimes(2)
    stopp()
  })

  it("ohne Takt (Leser): nur beim Zurückkehren, höchstens einmal je Mindestabstand", async () => {
    const u = umgebung()
    const s = server()
    let t = 0
    const stopp = standAbfragen({
      holen: s.holen, geaendert: vi.fn(), dokument: u.dokument, fenster: u.fenster,
      intervallMs: null, mindestAbstandMs: 60_000, jetzt: () => t,
    })
    await vi.advanceTimersByTimeAsync(STAND_INTERVALL_MS * 20)
    expect(s.holen).toHaveBeenCalledTimes(1)
    t = 30_000
    u.fokus()
    await vi.advanceTimersByTimeAsync(0)
    expect(s.holen).toHaveBeenCalledTimes(1)
    t = 61_000
    u.fokus()
    await vi.advanceTimersByTimeAsync(0)
    expect(s.holen).toHaveBeenCalledTimes(2)
    expect(vi.getTimerCount()).toBe(0)
    stopp()
  })
})

// ─── Unterschied, Entscheidung, Positionen ──────────────────────────────────

const karte = (id: number, name: string, x = 0): Karte => ({
  id, entitaet: id * 10, x, y: 0, farbe: "",
  entitaet_detail: {
    id: id * 10, typ: "organisation", name, slug: name.toLowerCase(), kurzbeschreibung: "", bild_url: "",
    oeffentliche_person: false, status: "entwurf",
  },
})
const faden = (id: number, beschreibung = "fordert Ablehnung"): Verbindung => ({
  id, von: 10, nach: 20, typ: "lobby", beschreibung, start: null, ende: null, aktuell: true, betrag: null, waehrung: "",
  aussageart: "belegt", status: "entwurf", belege: [], befunde: [],
})
const wand = (teile: Partial<Wand> = {}): Wand => ({
  board: { id: 1, titel: "Chatkontrolle", slug: "chatkontrolle", beschreibung: "", look: "dunkel" },
  karten: [karte(1, "Bitkom"), karte(2, "Bündnis F5")], faeden: [faden(1)], zettel: [], rahmen: [], fahrten: [],
  beweise: [], ...teile,
})

describe("wandUnterschied", () => {
  it("findet nichts, wenn alles gleich ist", () => {
    expect(wandUnterschied(wand(), wand()).geaendert).toBe(false)
  })
  it("zählt neue Karten mit Namen, neue und geänderte Fäden", () => {
    const neu = wand({
      karten: [karte(1, "Bitkom"), karte(2, "Bündnis F5"), karte(3, "Thorn")],
      faeden: [faden(1, "lehnt Entwurf ab"), faden(2)],
    })
    const u = wandUnterschied(wand(), neu)
    expect(u).toMatchObject({ geaendert: true, neueKarten: ["Thorn"], neueKartenIds: [3], neueFaeden: 1, geaenderteFaeden: [1] })
    expect(unterschiedText(u)).toBe("Neu auf der Wand: Karte „Thorn“, 1 Faden, 1 Faden geändert")
  })
  it("merkt Verschobenes, Entferntes und Zettel", () => {
    const u = wandUnterschied(wand(), wand({ karten: [karte(1, "Bitkom", 400)], zettel: [{ id: 1, art: "notiz", text: "", x: 0, y: 0 }] }))
    expect(u.entfernt).toBe(1)
    expect(u.sonst).toBe(2)
    expect(unterschiedText(u)).toBe("Neu auf der Wand: 1 entfernt, weitere Änderungen")
  })
  it("fasst viele neue Karten kurz", () => {
    const neu = wand({ karten: [karte(1, "A"), karte(2, "B"), karte(3, "C"), karte(4, "D")] })
    expect(unterschiedText(wandUnterschied(wand({ karten: [karte(1, "A")] }), neu)))
      .toBe("Neu auf der Wand: 3 Karten („B“, „C“ …)")
  })
})

describe("liveEntscheidung: offene Formulare werden nie überschrieben", () => {
  it("übernimmt nur, wenn nichts offen ist", () => {
    expect(liveEntscheidung({ formularOffen: false, zieht: false, aufnahme: false })).toBe("uebernehmen")
  })
  it("zeigt bei offenem Formular nur den Hinweis", () => {
    expect(liveEntscheidung({ formularOffen: true, zieht: false, aufnahme: false })).toBe("hinweis")
  })
  it("wartet still beim Ziehen und in der Aufnahme", () => {
    expect(liveEntscheidung({ formularOffen: false, zieht: true, aufnahme: false })).toBe("warten")
    expect(liveEntscheidung({ formularOffen: true, zieht: false, aufnahme: true })).toBe("warten")
  })
  it("meldet über einem Formular nur sichtbare Unterschiede; Verschobenes kommt still nach dem Schließen", () => {
    expect(liveEntscheidung({ formularOffen: true, zieht: false, aufnahme: false, sichtbar: false })).toBe("warten")
    expect(liveEntscheidung({ formularOffen: false, zieht: false, aufnahme: false, sichtbar: false })).toBe("uebernehmen")
    const verschoben = wandUnterschied(wand(), wand({ karten: [karte(1, "Bitkom", 400), karte(2, "Bündnis F5")] }))
    expect(verschoben.geaendert).toBe(true)
    expect(sichtbarerUnterschied(verschoben)).toBe(false)
    expect(sichtbarerUnterschied(wandUnterschied(wand(), wand({ faeden: [faden(1), faden(2)] })))).toBe(true)
  })
})

describe("mitPositionen", () => {
  it("legt Positionen, die noch gespeichert werden, über die frische Wand", () => {
    const offen = new Map<string, OffenePosition>([
      ["karte-2", { art: "karte", id: 2, x: 500, y: 60 }],
      ["rahmen-7", { art: "rahmen", id: 7, x: 1, y: 2, breite: 300, hoehe: 200 }],
    ])
    const w = mitPositionen(wand({ rahmen: [{ id: 7, titel: "", x: 0, y: 0, breite: 10, hoehe: 10, farbe: "" }] }), offen)
    expect(w.karten.map((k) => [k.x, k.y])).toEqual([[0, 0], [500, 60]])
    expect(w.rahmen[0]).toMatchObject({ x: 1, y: 2, breite: 300, hoehe: 200 })
  })
  it("lässt die Wand unverändert, wenn nichts unterwegs ist", () => {
    const w = wand()
    expect(mitPositionen(w, new Map())).toBe(w)
  })
})
