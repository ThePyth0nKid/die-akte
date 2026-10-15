import { act, useEffect } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import type { Vorbereitung } from "@/lib/akte/unterschrift"
import { useUnterschrift, type Rueckfragen } from "./UnterschriftDialog"

// Der Dialog ersetzt window.confirm/prompt: Er muss Klartext zeigen und die Antwort des Menschen zurückgeben.

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const V: Vorbereitung = {
  event_id: "01J", signing_input: "", event_hash: "6d683a0e7c6a0a85eac96b2fab37ee02",
  inhalt: {
    von: "Digitale Gesellschaft e.V.", nach: "Chatkontrolle", typ: "lobby", beschreibung: "lehnt Entwurf ab",
    aussageart: "belegt", konfidenz: 2, start: "2024-06-25", ende: null, aktuell: true,
    belege: [{ quelle: { titel: "Lobbyregister RV0005904", url: "https://lobbyregister.example/x", herausgeber: "Bundestag" },
      zitat_woertlich: "Unsere Bemühungen um Einflussnahme", fundstelle: "Beschreibung", original_sha256: "ab".repeat(32) }],
  },
  ueberstimmungen: [{ code: "verdacht_zu_duenn", begruendung: "Zweite Quelle folgt" }],
  hinweise_offen: ["quelle_ohne_archiv", "ohne_start"],
}

let wurzel: HTMLDivElement
let behaelter: HTMLDivElement
let root: Root
let fragen: (o: "karte" | "faden") => Rueckfragen

function Halter() {
  const u = useUnterschrift()
  useEffect(() => { fragen = u.fragen }, [u.fragen])
  return <div>{u.dialog}</div>
}

beforeEach(() => {
  // Wie im Layout der Akte: Der Dialog geht per Portal in #akte-wurzel, die Komponente sitzt darin.
  wurzel = document.createElement("div")
  wurzel.id = "akte-wurzel"
  behaelter = document.createElement("div")
  wurzel.appendChild(behaelter)
  document.body.appendChild(wurzel)
  root = createRoot(behaelter)
  act(() => root.render(<Halter />))
})

afterEach(() => {
  act(() => root.unmount())
  wurzel.remove()
})

const knopf = (text: string) =>
  [...document.querySelectorAll("button")].find((b) => b.textContent?.includes(text)) as HTMLButtonElement

describe("Unterschrift-Dialog", () => {
  it("zeigt die Freigabe in Klartext und offene Hinweise ohne Codes", async () => {
    let antwort: Promise<boolean> = Promise.resolve(false)
    act(() => { antwort = fragen("faden").bestaetigen(V) })
    const dialog = document.querySelector("[role='alertdialog']")!
    expect(dialog).toBeTruthy()
    const sichtbar = (dialog.textContent ?? "").replace((dialog.querySelector("details")?.textContent ?? ""), "")
    for (const teil of ["Von", "Digitale Gesellschaft e.V.", "Nach", "Art der Verbindung", "Lobby / Beratung",
      "Beschriftung", "lehnt Entwurf ab", "Belegt", "Seit", "25.06.2024", "Besteht heute noch", "Lobbyregister RV0005904",
      "„Unsere Bemühungen um Einflussnahme“", "archive.org", "Startdatum", "Zweite Quelle folgt"]) {
      expect(sichtbar).toContain(teil)
    }
    for (const code of ["quelle_ohne_archiv", "ohne_start", "verdacht_zu_duenn", "aussageart", "konfidenz"]) {
      expect(sichtbar).not.toContain(code)
    }
    act(() => knopf("Mit meinem Schlüssel unterschreiben").click())
    await expect(antwort).resolves.toBe(true)
    expect(document.querySelector("[role='alertdialog']")).toBeNull()
  })

  it("macht aus unsicheren Adressen keinen Link und zeigt versteckte Zeichen", async () => {
    let antwort: Promise<boolean> = Promise.resolve(false)
    const boese: Vorbereitung = { ...V, inhalt: { ...V.inhalt, belege: [{
      quelle: { titel: "Drucksache‮fdp.exe", url: "javascript:alert(1)" }, zitat_woertlich: "Zitat​" }] } }
    act(() => { antwort = fragen("faden").bestaetigen(boese) })
    const dialog = document.querySelector("[role='alertdialog']")!
    expect([...dialog.querySelectorAll("a")].map((a) => a.getAttribute("href"))).not.toContain("javascript:alert(1)")
    expect(dialog.textContent).toContain("javascript:alert(1) (kein sicherer Link)")
    expect(dialog.textContent).toContain("Drucksache⟦U+202E⟧fdp.exe")
    expect(dialog.textContent).not.toContain("‮")
    expect(dialog.querySelector("summary")?.textContent).toContain("Angaben des Servers")
    act(() => knopf("Abbrechen").click())
    await expect(antwort).resolves.toBe(false)
  })

  it("zeigt den Server getrennt und warnt bei Benutzerinfo vor dem @ (SR-F7)", async () => {
    let antwort: Promise<boolean> = Promise.resolve(false)
    const taeuschend: Vorbereitung = { ...V, inhalt: { ...V.inhalt, belege: [{
      quelle: { titel: "Drucksache", url: "https://www.bundestag.de@boese.example/d.pdf" }, zitat_woertlich: "Zitat" }] } }  // erfundene Täuschungs-Adresse, scrub:erlaubt
    act(() => { antwort = fragen("faden").bestaetigen(taeuschend) })
    const dialog = document.querySelector("[role='alertdialog']")!
    expect(dialog.textContent).toContain("Server: boese.example")
    expect(dialog.textContent).toContain("führt zu boese.example")
    act(() => knopf("Abbrechen").click())
    await expect(antwort).resolves.toBe(false)
  })

  it("Abbrechen und Escape geben false zurück", async () => {
    let antwort: Promise<boolean> = Promise.resolve(true)
    act(() => { antwort = fragen("karte").bestaetigen({ ...V, inhalt: { name: "Thorn", typ: "organisation" }, hinweise_offen: [], ueberstimmungen: [] }) })
    expect(document.body.textContent).toContain("Diese Karte unterschreiben?")
    act(() => knopf("Abbrechen").click())
    await expect(antwort).resolves.toBe(false)

    act(() => { antwort = fragen("faden").bestaetigen(V) })
    const dialog = document.querySelector("[role='alertdialog']")!
    act(() => { dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })) })
    await expect(antwort).resolves.toBe(false)
  })

  it("fragt eine Begründung ab statt window.prompt", async () => {
    let antwort: Promise<string | null> = Promise.resolve(null)
    act(() => { antwort = fragen("faden").begruendung({ code: "verdacht_ohne_anhoerung", text: "Verdacht gegen eine Person ohne Anhörung." }) })
    expect(document.body.textContent).toContain("Begründung nötig")
    expect(document.body.textContent).toContain("nicht angehört")
    // Leer geht nicht weiter
    act(() => knopf("Weiter").click())
    expect(document.querySelector("[role='alert']")?.textContent).toContain("Begründung")
    const feld = document.querySelector("textarea")!
    act(() => {
      const setzen = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!
      setzen.call(feld, "Anhörung läuft, Antwort steht aus")
      feld.dispatchEvent(new Event("input", { bubbles: true }))
    })
    act(() => knopf("Weiter").click())
    await expect(antwort).resolves.toBe("Anhörung läuft, Antwort steht aus")
  })

  it("gilt als abgebrochen, wenn das Formular verschwindet", async () => {
    let antwort: Promise<boolean> = Promise.resolve(true)
    act(() => { antwort = fragen("faden").bestaetigen(V) })
    act(() => root.unmount())
    await expect(antwort).resolves.toBe(false)
    expect(document.querySelector("[role='alertdialog']")).toBeNull()
    root = createRoot(behaelter)
  })
})
