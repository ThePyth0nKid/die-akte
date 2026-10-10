// @vitest-environment node
import { describe, expect, it } from "vitest"
import { FARBEN, durchhang, fadenStil, rahmenStil, wikilinks, zeitraum } from "./faden"

describe("fadenStil", () => {
  it("zeichnet Verdacht gestrichelt mit Stempel, Belegtes durchgezogen", () => {
    expect(fadenStil("belegt").strich).toBeUndefined()
    expect(fadenStil("verdacht")).toMatchObject({ strich: "10 8", stempel: "VERDACHT" })
    expect(fadenStil("meinung").stempel).toBe("MEINUNG")
  })
})

describe("durchhang", () => {
  it("sackt die Mitte nach unten, begrenzt auf 120 px", () => {
    const kurz = durchhang(0, 0, 100, 0)
    expect(kurz.mitteY).toBeCloseTo(6)
    const lang = durchhang(0, 0, 10000, 0)
    expect(lang.mitteY).toBeCloseTo(60)
    expect(lang.pfad.startsWith("M 0,0 Q")).toBe(true)
  })
})

describe("zeitraum", () => {
  it("unterscheidet aktuell, beendet und offen", () => {
    expect(zeitraum({ start: "2003-05-01", ende: null, aktuell: true })).toBe("seit 2003")
    expect(zeitraum({ start: "2003-05-01", ende: "2016-01-01", aktuell: false })).toBe("2003–2016")
    expect(zeitraum({ start: null, ende: null, aktuell: false })).toBe("?")
    expect(zeitraum({ start: null, ende: null, aktuell: false }, "Etikett")).toBe("")
    expect(zeitraum({ start: "2014-01-01", ende: null, aktuell: false }, "Az. 20141123")).toBe("2014")
    expect(zeitraum({ start: "2019-01-01", ende: "2024-01-01", aktuell: false }, "Hausbank (2019)")).toBe("2019–2024")
    expect(zeitraum({ start: "2026-01-01", ende: "2026-09-21", aktuell: false })).toBe("2026")
    expect(zeitraum({ start: "2019-01-01", ende: "2026-01-01", aktuell: false }, "Hausbank (2019–2026)")).toBe("")
    expect(zeitraum({ start: "2026-05-01", ende: null, aktuell: true }, "Ermittlung ausgeweitet (Mai 2026)")).toBe("")
    expect(zeitraum({ start: "2011-01-01", ende: "2014-12-31", aktuell: false }, "15–17 Kontakte")).toBe("2011–2014")
  })
})

describe("wikilinks", () => {
  it("findet [[Ziel]] und [[Ziel|Anzeige]]", () => {
    expect(wikilinks("Mitgründer von [[Nordlicht]] und [[PayPal|PayPal Inc.]].")).toEqual([
      { art: "text", text: "Mitgründer von " },
      { art: "link", ziel: "Nordlicht", text: "Nordlicht" },
      { art: "text", text: " und " },
      { art: "link", ziel: "PayPal", text: "PayPal Inc." },
      { art: "text", text: "." },
    ])
  })
})

describe("rahmenStil", () => {
  it("bleibt ohne Farbe die goldene Strichlinie", () => {
    expect(rahmenStil("")).toMatchObject({ strich: "dashed", titel: FARBEN.gold, plakette: null })
    expect(rahmenStil(undefined).plakette).toBeNull()
  })

  it("macht mit Farbe ein Schild mit Plakette", () => {
    expect(rahmenStil("#C8102E")).toEqual({
      rand: "#C8102E", flaeche: "#C8102E14", strich: "solid", titel: "#FFFFFF", plakette: "#C8102E",
    })
  })

  it("nimmt nur #RRGGBB, nie beliebiges CSS aus der Datenbank", () => {
    for (const boese of ["red", "#C8102E; background:url(x)", "url(javascript:1)", "#FFF"]) {
      expect(rahmenStil(boese).plakette).toBeNull()
    }
  })
})
