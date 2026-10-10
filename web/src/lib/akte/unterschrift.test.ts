import { describe, expect, it } from "vitest"
import { b64url, b64urlLesen, zusammenfassung, type Vorbereitung } from "./unterschrift"

describe("b64url", () => {
  it("hin und zurück ohne Auffüllung", () => {
    const roh = new Uint8Array([0, 1, 2, 250, 251, 252, 253, 254, 255])
    const text = b64url(roh)
    expect(text).not.toContain("=")
    expect(text).not.toMatch(/[+/]/)
    expect(Array.from(b64urlLesen(text))).toEqual(Array.from(roh))
  })
})

describe("zusammenfassung", () => {
  it("zeigt Inhalt, Belege, Hinweise und Überstimmungen", () => {
    const v: Vorbereitung = {
      event_id: "01X", signing_input: "", event_hash: "6d683a0e7c6a0a85eac96b2fab37ee02",
      inhalt: { von: "Senat Musterhafen", nach: "Nordlicht Analytik GmbH", belege: [{}, {}], ende: null },
      ueberstimmungen: [{ code: "quelle_ohne_archiv", begruendung: "…" }],
      hinweise_offen: ["ohne_start"],
    }
    const text = zusammenfassung(v)
    expect(text).toContain("von: Senat Musterhafen")
    expect(text).toContain("belege: 2")
    expect(text).toContain("Offene Hinweise: ohne_start")
    expect(text).toContain("Überstimmt: quelle_ohne_archiv")
    expect(text).not.toContain("ende:")
  })
})
