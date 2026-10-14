import { describe, expect, it } from "vitest"
import { istRedaktionOhneWand } from "./rolle"

// Durchlauf 3: Ein frisches Redaktionskonto ohne Wand muss „Neues Board“ sehen, Besucher und Mitglieder nicht.

describe("istRedaktionOhneWand", () => {
  it("ohne Sitzung: nein, und keine Anfrage an die Einstellungen", async () => {
    let gefragt = false
    const ja = await istRedaktionOhneWand(async () => false, async () => { gefragt = true })
    expect(ja).toBe(false)
    expect(gefragt).toBe(false)
  })

  it("Redaktion: die Einstellungen antworten", async () => {
    expect(await istRedaktionOhneWand(async () => true, async () => ({ archiv_org: false }))).toBe(true)
  })

  it("Mitglied: die Einstellungen weisen ab", async () => {
    expect(await istRedaktionOhneWand(async () => true, async () => { throw new Error("403") })).toBe(false)
  })

  it("Sitzung nicht prüfbar: nein", async () => {
    expect(await istRedaktionOhneWand(async () => { throw new Error("offline") }, async () => ({}))).toBe(false)
  })
})
