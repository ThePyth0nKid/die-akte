"use client"

// Aufnahme-Dialog: eine Fahrt als fertiges Video rendern (lokaler Render-Dienst) oder live
// fahren (Pfeiltasten, für OBS). Das Rendern läuft auf dem eigenen Rechner, solange der Dienst läuft.

import { useEffect, useRef, useState } from "react"
import { FolderOpen, Loader2, Play, Video, X } from "lucide-react"
import type { FormatKennung } from "@/lib/akte/aufnahme"
import type { Fahrt } from "@/lib/akte/typen"

const DIENST = "http://127.0.0.1:8178"

const FORMAT_WAHL: { id: FormatKennung; name: string; zweck: string }[] = [
  { id: "16x9", name: "16:9", zweck: "YouTube lang, 1920×1080" },
  { id: "9x16", name: "9:16", zweck: "Shorts, TikTok, 1080×1920" },
  { id: "1x1", name: "1:1", zweck: "Einblendung, 1080×1080" },
  { id: "oben", name: "Oben", zweck: "50/50-Short, obere Hälfte 1080×960" },
]

interface Auftrag {
  id: string
  status: "laeuft" | "fertig" | "fehler"
  formate: Record<string, { bild: number; von: number }>
  dateien: string[]
  fehler: string
}

interface Props {
  board: string
  fahrten: Fahrt[]
  fahrtId: number | null
  schliessen: () => void
  live: (fahrtId: number) => void
}

const kaestchen = "flex min-h-11 cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm transition-colors duration-200 focus-within:ring-2 focus-within:ring-[#f0c674]"

export default function AufnahmeDialog({ board, fahrten, fahrtId, schliessen, live }: Props) {
  const [fahrt, setFahrt] = useState<number | null>(fahrtId ?? fahrten[0]?.id ?? null)
  const [formate, setFormate] = useState<FormatKennung[]>(["16x9"])
  const [halte, setHalte] = useState(3)
  const [look, setLook] = useState<"board" | "dunkel" | "papier">("board")
  const [stichworte, setStichworte] = useState(false)
  const [vierk, setVierk] = useState(false)
  const [unschaerfe, setUnschaerfe] = useState(false)
  const [auftrag, setAuftrag] = useState<Auftrag | null>(null)
  const [fehler, setFehler] = useState("")
  const [sendet, setSendet] = useState(false)
  const erstes = useRef<HTMLSelectElement>(null)

  useEffect(() => { erstes.current?.focus() }, [])

  // Fortschritt abfragen, solange der Auftrag läuft.
  useEffect(() => {
    if (!auftrag || auftrag.status !== "laeuft") return
    const t = setInterval(async () => {
      try {
        const r = await fetch(`${DIENST}/auftrag/${auftrag.id}`)
        if (r.ok) setAuftrag(await r.json())
      } catch { /* Dienst kurz weg: beim nächsten Mal wieder */ }
    }, 1000)
    return () => clearInterval(t)
  }, [auftrag])

  const gewaehlt = fahrten.find((f) => f.id === fahrt)

  async function rendern() {
    if (!gewaehlt || !formate.length) return
    setFehler("")
    setSendet(true)
    try {
      const r = await fetch(`${DIENST}/auftrag`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          board, fahrt: gewaehlt.id, titel: gewaehlt.titel, formate, halte: halte * 1000,
          look: look === "board" ? undefined : look, stichworte, vierk, unschaerfe,
        }),
      })
      const daten = await r.json()
      if (!r.ok) setFehler(daten.fehler ?? `Dienst antwortet ${r.status}`)
      else setAuftrag(daten)
    } catch {
      setFehler("Der Render-Dienst läuft nicht. Starten: START-AKTE-RENDER.cmd im lokalen Testaufbau oder `node scripts/akte/render_dienst.cjs`.")
    } finally {
      setSendet(false)
    }
  }

  const laeuft = auftrag?.status === "laeuft"

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="aufnahme-titel" className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onKeyDown={(e) => { if (e.key === "Escape" && !laeuft) schliessen() }}>
      <div className="flex max-h-full w-full max-w-[560px] flex-col overflow-y-auto rounded-lg border border-[#222636] bg-[#0d0e14] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#222636] px-5 py-3">
          <h2 id="aufnahme-titel" className="font-[family-name:var(--font-akte-titel)] text-2xl uppercase tracking-wide">Aufnahme</h2>
          <button type="button" onClick={schliessen} aria-label="Schließen" className="cursor-pointer rounded p-2 text-[#8A94A0] hover:text-white focus-visible:ring-2 focus-visible:ring-[#f0c674]">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5 p-5">
          <label className="block space-y-1.5 text-sm">
            <span className="font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]">Fahrt</span>
            <select ref={erstes} value={fahrt ?? ""} onChange={(e) => setFahrt(Number(e.target.value))} disabled={laeuft}
              className="min-h-11 w-full cursor-pointer rounded-md border border-[#222636] bg-[#0A0A0F] px-3 outline-none focus:border-[#f0c674]">
              {fahrten.map((f) => <option key={f.id} value={f.id}>{f.titel} · {f.stationen.length} Stationen</option>)}
            </select>
          </label>

          <fieldset className="space-y-1.5" disabled={laeuft}>
            <legend className="mb-1.5 font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]">Formate</legend>
            <div className="grid grid-cols-2 gap-2">
              {FORMAT_WAHL.map((f) => {
                const an = formate.includes(f.id)
                return (
                  <label key={f.id} className={`${kaestchen} ${an ? "border-[#FF1744] bg-[#FF1744]/10" : "border-[#222636] hover:border-[#8A94A0]"}`}>
                    <input type="checkbox" className="h-4 w-4 cursor-pointer accent-[#FF1744]" checked={an}
                      onChange={() => setFormate((alt) => (an ? alt.filter((x) => x !== f.id) : [...alt, f.id]))} />
                    <span><span className="font-semibold">{f.name}</span><br /><span className="text-xs text-[#8A94A0]">{f.zweck}</span></span>
                  </label>
                )
              })}
            </div>
          </fieldset>

          <fieldset className="grid grid-cols-2 gap-4" disabled={laeuft}>
            <label className="space-y-1.5 text-sm">
              <span className="font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]">Halten je Station: {halte.toLocaleString("de-DE")} s</span>
              <input type="range" min={1.5} max={6} step={0.5} value={halte} onChange={(e) => setHalte(Number(e.target.value))}
                className="h-11 w-full cursor-pointer accent-[#f0c674]" />
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]">Look</span>
              <select value={look} onChange={(e) => setLook(e.target.value as typeof look)}
                className="min-h-11 w-full cursor-pointer rounded-md border border-[#222636] bg-[#0A0A0F] px-3 outline-none focus:border-[#f0c674]">
                <option value="board">wie das Board</option>
                <option value="dunkel">dunkel</option>
                <option value="papier">Papier / Kork</option>
              </select>
            </label>
          </fieldset>

          <fieldset className="grid grid-cols-1 gap-2 sm:grid-cols-3" disabled={laeuft}>
            {([
              ["Stichworte", "als Bauchbinde", stichworte, setStichworte],
              ["4K", "16:9 in 3840×2160", vierk, setVierk],
              ["Unschärfe", "Bewegung wie Kamera, ~4× Zeit", unschaerfe, setUnschaerfe],
            ] as const).map(([name, info, an, setzen]) => (
              <label key={name} className={`${kaestchen} ${an ? "border-[#f0c674] bg-[#f0c674]/10" : "border-[#222636] hover:border-[#8A94A0]"}`}>
                <input type="checkbox" className="h-4 w-4 cursor-pointer accent-[#f0c674]" checked={an} onChange={() => setzen(!an)} />
                <span><span className="font-semibold">{name}</span><br /><span className="text-xs text-[#8A94A0]">{info}</span></span>
              </label>
            ))}
          </fieldset>

          {fehler && <p role="alert" className="rounded-md border border-[#FF1744]/50 bg-[#FF1744]/10 px-3 py-2 text-sm">{fehler}</p>}

          {auftrag && (
            <div className="space-y-2 rounded-md border border-[#222636] p-3" aria-live="polite">
              {Object.entries(auftrag.formate).map(([f, s]) => (
                <div key={f} className="space-y-1">
                  <div className="flex justify-between font-[family-name:var(--font-akte-mono)] text-xs text-[#8A94A0]">
                    <span>{FORMAT_WAHL.find((x) => x.id === f)?.name ?? f}</span><span>Bild {s.bild} / {s.von}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-[#222636]">
                    <div className="h-full bg-[#FF1744]" style={{ width: `${s.von ? (100 * s.bild) / s.von : 0}%` }} />
                  </div>
                </div>
              ))}
              {auftrag.status === "laeuft" && !Object.keys(auftrag.formate).length && <p className="text-sm text-[#8A94A0]">Wand wird geladen …</p>}
              {auftrag.status === "fehler" && <p role="alert" className="text-sm text-[#FF1744]">{auftrag.fehler || "Rendern fehlgeschlagen."}</p>}
              {auftrag.status === "fertig" && (
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <button type="button" onClick={() => fetch(`${DIENST}/auftrag/${auftrag.id}/oeffnen`, { method: "POST" })}
                    className="flex min-h-10 cursor-pointer items-center gap-2 rounded-md bg-[#f0c674] px-3 text-sm font-semibold text-black focus-visible:ring-2 focus-visible:ring-white">
                    <FolderOpen className="h-4 w-4" aria-hidden /> Ordner öffnen
                  </button>
                  {auftrag.dateien.map((d, i) => (
                    <a key={d} href={`${DIENST}/auftrag/${auftrag.id}/datei/${i}`} className="text-sm text-[#f0c674] underline underline-offset-2">
                      {d.split(/[\\/]/).pop()}
                    </a>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-[#222636] px-5 py-3">
          <button type="button" disabled={!gewaehlt || laeuft} onClick={() => gewaehlt && live(gewaehlt.id)}
            className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md border border-[#222636] px-4 text-sm hover:border-[#8A94A0] focus-visible:ring-2 focus-visible:ring-[#f0c674] disabled:cursor-not-allowed disabled:opacity-40">
            <Play className="h-4 w-4" aria-hidden /> Live fahren (OBS)
          </button>
          <button type="button" disabled={!gewaehlt || !formate.length || laeuft || sendet} onClick={rendern}
            className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md bg-[#FF1744] px-4 text-sm font-semibold text-white hover:bg-[#ff3d63] focus-visible:ring-2 focus-visible:ring-white disabled:cursor-not-allowed disabled:opacity-40">
            {laeuft || sendet ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Video className="h-4 w-4" aria-hidden />}
            {laeuft ? "Rendert …" : "Video rendern"}
          </button>
        </div>
      </div>
    </div>
  )
}
