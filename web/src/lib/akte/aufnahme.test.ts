// @vitest-environment node
import { describe, expect, it } from "vitest"
import {
  bildZu, EINBLENDUNG_PLATZ_PX, einspielerStationMs, FORMAT_KENNUNGEN, FORMATE, flug, rahmeUeberEinblendung, licht, rahmeStation, sichereFlaeche, STANDARD, TITEL_MIN_PX, TITEL_NOT_PX,
  ueberblick, umriss, viewportVon, zeitplan, type FokusKarte, type Kamera, type PlanEingabe,
} from "./aufnahme"

const karte = (x: number, y: number, h = 380, titelPx = 26): FokusKarte => ({ x, y, b: 220, h, titelPx })

/** Wo landet ein Wand-Rechteck auf dem Bildschirm? */
function aufDemSchirm(k: Kamera, fmt: keyof typeof FORMATE, r: { x: number; y: number; b: number; h: number }) {
  const v = viewportVon(k, FORMATE[fmt])
  return { x: r.x * v.zoom + v.x, y: r.y * v.zoom + v.y, b: r.b * v.zoom, h: r.h * v.zoom }
}

describe("rahmeStation", () => {
  for (const fmt of FORMAT_KENNUNGEN) {
    it(`${fmt}: zwei Karten — ein Bild, das gut 80 % füllt, oder ein Schwenk mit großen Titeln`, () => {
      const f = FORMATE[fmt]
      const karten = [karte(0, 0), karte(300, 40)]
      const kameras = rahmeStation(karten, f)
      const s = sichereFlaeche(f)
      for (const k of kameras) expect(26 * k.zoom).toBeGreaterThanOrEqual(f.titelNot - 0.01)
      if (kameras.length === 1) {
        const u = aufDemSchirm(kameras[0], fmt, umriss(karten))
        expect(Math.max(u.b / s.b, u.h / s.h)).toBeGreaterThan(0.8)
        expect(u.x).toBeGreaterThanOrEqual(s.x - 1)
        expect(u.y).toBeGreaterThanOrEqual(s.y - 1)
        expect(u.x + u.b).toBeLessThanOrEqual(s.x + s.b + 1)
        expect(u.y + u.h).toBeLessThanOrEqual(s.y + s.h + 1)
      }
    })
  }

  it("Hochformat geht näher ran als Querformat", () => {
    const karten = [karte(0, 0, 160), karte(340, 0, 160)]
    const hoch = rahmeStation(karten, FORMATE["9x16"])
    const quer = rahmeStation(karten, FORMATE["16x9"])
    expect(Math.max(...hoch.map((k) => k.zoom))).toBeGreaterThan(Math.max(...quer.map((k) => k.zoom)))
    for (const k of hoch) expect(26 * k.zoom).toBeGreaterThanOrEqual(FORMATE["9x16"].titelNot)
  })

  it("Hochformat: vier Karten nebeneinander werden ein Schwenk statt winziger Titel", () => {
    const karten = [0, 1, 2, 3].map((i) => karte(i * 300, 0))
    const kameras = rahmeStation(karten, FORMATE["9x16"])
    expect(kameras.length).toBeGreaterThan(1)
    for (const k of kameras) expect(26 * k.zoom).toBeGreaterThanOrEqual(TITEL_MIN_PX)
    // Schwenk von links nach rechts, gleicher Zoom (kein Pumpen).
    expect(kameras[1].cx).toBeGreaterThan(kameras[0].cx)
    expect(new Set(kameras.map((k) => k.zoom)).size).toBe(1)
  })

  it("Querformat: dieselben vier Karten passen in ein Bild", () => {
    const karten = [0, 1, 2, 3].map((i) => karte(i * 300, 0))
    const kameras = rahmeStation(karten, FORMATE["16x9"])
    expect(kameras).toHaveLength(1)
    expect(26 * kameras[0].zoom).toBeGreaterThanOrEqual(TITEL_NOT_PX)
  })

  it("Karten ohne Bild (niedriger) werden enger gerahmt als Karten mit Bild", () => {
    const [mit] = rahmeStation([karte(0, 0, 380)], FORMATE["16x9"])
    const [ohne] = rahmeStation([karte(0, 0, 240)], FORMATE["16x9"])
    expect(ohne.zoom).toBeGreaterThan(mit.zoom)
  })
})

describe("Platz für die Einblendung", () => {
  for (const fmt of ["16x9", "9x16"] as const) {
    it(`${fmt}: jede Karte endet über der Zahlenkarte, auch beim Schwenk`, () => {
      const f = FORMATE[fmt]
      const karten = [karte(0, 0, 400), karte(300, 0, 400), karte(600, 0, 400)]
      const kameras = rahmeUeberEinblendung(karten, f)
      const grenze = f.h - f.rand.u - EINBLENDUNG_PLATZ_PX
      for (const k of kameras) {
        // Karten, die diese Kamera zeigt (Mitte im Bild), müssen oberhalb der Einblendung enden.
        for (const r of karten) {
          const u = aufDemSchirm(k, fmt, r)
          const mitteX = u.x + u.b / 2
          if (mitteX < 0 || mitteX > f.b) continue
          expect(u.y + u.h).toBeLessThanOrEqual(grenze + 1)
        }
      }
    })
  }
})

describe("Schwenk über zwei Reihen", () => {
  it("fährt Nachbarn zusammen ab statt zwischen den Reihen zu springen", () => {
    // Unten links zwei Karten, oben rechts drei — wie die Länder auf der Nordlicht-Wand.
    const karten = [karte(3270, 760, 125), karte(3610, 760, 149), karte(3610, 230, 128), karte(4290, 230, 128), karte(4630, 230, 128)]
    const kameras = rahmeStation(karten, FORMATE["16x9"])
    expect(kameras.length).toBeLessThanOrEqual(3)
    // Erste Gruppe: die beiden unteren Karten zusammen.
    expect(kameras[0].cy).toBeGreaterThan(760)
    expect(kameras[0].cx).toBeCloseTo(3550, -1)
  })

  it("Beiwerk (Faden-Beschriftung über den Karten) kommt mit ins Bild", () => {
    const karten = [karte(0, 300, 128), karte(400, 300, 128)]
    const [ohne] = rahmeStation(karten, FORMATE["16x9"])
    const [mit] = rahmeStation(karten, FORMATE["16x9"], [{ x: 150, y: 180, b: 220, h: 60 }])
    expect(mit.cy).toBeLessThan(ohne.cy)
  })
})

describe("ueberblick", () => {
  it("zeigt alles", () => {
    const alle = [karte(0, 0), karte(3000, 1200)]
    const k = ueberblick(alle, FORMATE["16x9"])
    const u = aufDemSchirm(k, "16x9", umriss(alle, 0))
    expect(u.x).toBeGreaterThanOrEqual(0)
    expect(u.x + u.b).toBeLessThanOrEqual(1920)
  })
})

describe("flug", () => {
  it("beginnt und endet an den Kameras", () => {
    const a = { cx: 0, cy: 0, zoom: 1 }
    const b = { cx: 2000, cy: 500, zoom: 2 }
    const f = flug(a, b, 1920)
    expect(f(0).cx).toBeCloseTo(0)
    expect(f(1)).toEqual(b)
    // Auf weitem Weg zieht die Kamera zwischendurch auf.
    expect(f(0.5).zoom).toBeLessThan(1)
  })
})

describe("zeitplan und bildZu", () => {
  const eingaben: PlanEingabe[] = [
    { kameras: [{ cx: 0, cy: 0, zoom: 0.3 }], fokus: null, stichwort: "Wand", beweis: null, fahrtMs: 1400 },
    { kameras: [{ cx: 500, cy: 0, zoom: 2 }], fokus: [1, 2], stichwort: "", beweis: null, fahrtMs: 1400 },
    { kameras: [{ cx: 900, cy: 300, zoom: 2 }], fokus: [3], stichwort: "", beweis: { quelle: 7, zitat: "x" }, fahrtMs: 900 },
  ]
  const plan = zeitplan(eingaben, { ...STANDARD, bildBreite: 1920 })

  it("Stationen folgen lückenlos aufeinander", () => {
    expect(plan.stationen).toHaveLength(3)
    for (let i = 1; i < plan.stationen.length; i++) expect(plan.stationen[i].start).toBe(plan.stationen[i - 1].ende)
    expect(plan.dauerMs).toBeGreaterThan(plan.stationen[2].ende)
    expect(plan.stationen[2].ankunft - plan.stationen[2].start).toBe(1000) // Mindestfahrt
  })

  it("ist deterministisch und stetig", () => {
    expect(bildZu(plan, 4321)).toEqual(bildZu(plan, 4321))
    // Keine Sprünge: zwischen zwei Bildern (40 ms) bewegt sich die Kamera nur ein Stück.
    for (let t = 40; t < plan.dauerMs; t += 40) {
      const a = bildZu(plan, t - 40).kamera
      const b = bildZu(plan, t).kamera
      expect(Math.abs(Math.log(b.zoom / a.zoom))).toBeLessThan(0.2)
    }
  })

  it("das Beweisblatt kommt nach der Ankunft und geht vor dem Ende", () => {
    const s = plan.stationen[2]
    expect(bildZu(plan, s.ankunft).beweis).toBeNull()
    expect(bildZu(plan, s.ankunft + 2000).beweis?.rein).toBe(1)
    expect(bildZu(plan, s.ende - 1).beweis).toBeNull()
  })

  it("im Takt der Stimme: die Kamera steht beim ersten Wort, gleiches Bild fliegt nicht", () => {
    const a = { cx: 0, cy: 0, zoom: 0.3 }
    const b = { cx: 900, cy: 200, zoom: 2 }
    const getaktet: PlanEingabe[] = [
      { kameras: [a], fokus: null, stichwort: "", beweis: null, fahrtMs: 1400, ankunftMs: 200 },
      { kameras: [b], fokus: [1], stichwort: "", beweis: null, fahrtMs: 1400, ankunftMs: 4200 },
      { kameras: [b], fokus: [1], stichwort: "", beweis: null, fahrtMs: 1400, ankunftMs: 7000,
        einblendung: { gross: "39 Mio.", klein: "Personendatensätze" } },
    ]
    const p = zeitplan(getaktet, { ...STANDARD, bildBreite: 1920, endeMs: 9500 })
    expect(p.stationen.map((s) => s.ankunft)).toEqual([0, 4200, 7000])
    // Kamera steht bei 4200 genau auf b, der Flug davor ist vorbei.
    const bei = bildZu(p, 4200).kamera
    expect(bei.cx).toBeCloseTo(900, 0)
    expect(bei.zoom).toBeCloseTo(2, 1)
    // Station 3 zeigt dasselbe Bild: kein Flug, die Drift läuft weiter (kein Rücksprung).
    const vor = bildZu(p, 6990).kamera
    const nach = bildZu(p, 7010).kamera
    expect(Math.abs(nach.zoom - vor.zoom)).toBeLessThan(0.01)
    expect(bildZu(p, 7700).einblendung?.gross).toBe("39 Mio.")
    expect(bildZu(p, 6000).einblendung).toBeNull()
    expect(p.dauerMs).toBe(9500 + 600)
  })

  it("im Takt: auch bei sehr kurzen Sätzen und Schwenks läuft nichts auf", () => {
    const k = (cx: number) => ({ cx, cy: 0, zoom: 2 })
    // Lücken von 450 ms, eine Station mit Schwenk über drei Kameras in 900 ms, eine Einblendung in knapper Station.
    const ankunft = [300, 750, 1200, 2100, 2550, 3000]
    const eingaben: PlanEingabe[] = ankunft.map((a, i) => ({
      kameras: i === 3 ? [k(1000), k(1400), k(1800)] : [k(i * 500)],
      fokus: [i], stichwort: "", beweis: null, fahrtMs: 1400, ankunftMs: a,
      einblendung: i === 4 ? { gross: "7" } : null,
    }))
    const p = zeitplan(eingaben, { ...STANDARD, bildBreite: 1920, endeMs: 3800 })
    expect(p.stationen.map((s) => s.ankunft)).toEqual([0, 750, 1200, 2100, 2550, 3000])
    for (const [i, s] of p.stationen.entries()) {
      if (i === 0) continue
      // Die Kamera steht bei jeder Ankunft auf ihrer ersten Zielkamera.
      expect(bildZu(p, s.ankunft).kamera.cx).toBeCloseTo(eingaben[i].kameras[0].cx, 0)
      expect(s.start).toBeLessThanOrEqual(s.ankunft)
      expect(s.ende).toBeGreaterThan(s.ankunft)
    }
    // Die Einblendung endet spätestens mit ihrer Station.
    const s4 = p.stationen[4]
    expect(s4.einblendung!.t1).toBeLessThanOrEqual(s4.ende)
    expect(p.dauerMs).toBe(3800 + 600)
  })

  it("im Takt: Tonspur kürzer als der letzte Satz ist ein Fehler, kein stilles Abschneiden", () => {
    const e: PlanEingabe = { kameras: [{ cx: 0, cy: 0, zoom: 1 }], fokus: null, stichwort: "", beweis: null, fahrtMs: 1000, ankunftMs: 5000 }
    expect(() => zeitplan([{ ...e, ankunftMs: 0 }, e], { ...STANDARD, bildBreite: 1920, endeMs: 4000 })).toThrow(/Tonspur/)
  })

  it("Einspieler: Bild für Bild, danach Standbild, Station lang genug", () => {
    const k = { cx: 0, cy: 0, zoom: 1 }
    const p = zeitplan([
      { kameras: [k], fokus: null, stichwort: "", beweis: null, fahrtMs: 1000 },
      { kameras: [{ cx: 500, cy: 0, zoom: 2 }], fokus: [1], stichwort: "", beweis: null, fahrtMs: 1000,
        einspieler: { dauerMs: 2000, freezeMs: 700, quelle: "NYT, 26.06.2025" } },
    ], { ...STANDARD, halteMs: 1500, bildBreite: 1920 })
    const s = p.stationen[1]
    const e = s.einspieler!
    expect(s.ende - s.ankunft).toBeGreaterThanOrEqual(einspielerStationMs(2000, 700) - 1)
    expect(bildZu(p, e.t0).einspieler?.bild).toBe(1)
    expect(bildZu(p, e.t0 + 1000).einspieler?.bild).toBe(26)
    // Nach dem Clip: Standbild = letztes Bild (50 bei 2 s und 25 fps).
    expect(bildZu(p, e.laufBis + 300).einspieler?.bild).toBe(50)
    expect(bildZu(p, e.t0 + 100).einspieler?.quelle).toBe("NYT, 26.06.2025")
    expect(bildZu(p, s.ankunft - 400).einspieler).toBeNull()
  })

  it("im Takt: der Flug nach einem O-Ton schneidet Clip, Standbild und Quelle nicht an", () => {
    // Abstände wie vertonen.py sie legt: O-Ton-Station + 900 ms Platz für den Flug.
    const dauer = 2000
    const o = { dauerMs: dauer, freezeMs: 700, quelle: "NYT" }
    const a1 = 4000
    const a2 = a1 + einspielerStationMs(dauer, 700) + 900
    const p = zeitplan([
      { kameras: [{ cx: 0, cy: 0, zoom: 1 }], fokus: null, stichwort: "", beweis: null, fahrtMs: 1000, ankunftMs: 500 },
      { kameras: [{ cx: 800, cy: 0, zoom: 2 }], fokus: [1], stichwort: "", beweis: null, fahrtMs: 1000, ankunftMs: a1, einspieler: o },
      { kameras: [{ cx: 3000, cy: 900, zoom: 2 }], fokus: [2], stichwort: "", beweis: null, fahrtMs: 1500, ankunftMs: a2 },
    ], { ...STANDARD, bildBreite: 1920, endeMs: a2 + 3000 })
    const e = p.stationen[1].einspieler!
    // Clip läuft ganz, Standbild auf mindestens 5 s Quelle verlängert, dazu die Ausblende.
    expect(e.laufBis - e.t0).toBe(dauer)
    expect(e.t1 - e.laufBis).toBeGreaterThanOrEqual(5000 - dauer)
    expect(e.t1).toBeLessThanOrEqual(p.stationen[1].ende)
    expect(bildZu(p, a2).kamera.cx).toBeCloseTo(3000, 0)
  })

  it("Scheinwerfer blendet über", () => {
    const s = plan.stationen[1]
    expect(licht(bildZu(plan, s.start).fokus, 9)).toBe(1)
    expect(licht(bildZu(plan, s.ankunft).fokus, 9)).toBe(0)
    expect(licht(bildZu(plan, s.ankunft).fokus, 1)).toBe(1)
  })
})
