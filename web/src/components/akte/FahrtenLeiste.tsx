"use client"

// Fahrten: Stationen für die Aufnahme festhalten. Eine Station merkt sich den
// Bildausschnitt und die gewählten Karten (die der Scheinwerfer später hervorhebt).

import { useState } from "react"
import { Play, Plus, Trash2, X } from "lucide-react"
import { akte } from "@/lib/akte/api"
import type { Fahrt } from "@/lib/akte/typen"

interface Props {
  slug: string
  fahrten: Fahrt[]
  aktiv: number | null
  waehlen: (id: number) => void
  stationAufnehmen: (stichwort: string) => Promise<void>
  anfahren: (index: number) => void
  geaendert: () => void
  schliessen: () => void
}

const feld = "min-h-10 w-full rounded border border-[#222636] bg-[#0A0A0F] px-3 text-sm outline-none focus:border-[#f0c674]"

export default function FahrtenLeiste({ slug, fahrten, aktiv, waehlen, stationAufnehmen, anfahren, geaendert, schliessen }: Props) {
  const [neuTitel, setNeuTitel] = useState("")
  const [stichwort, setStichwort] = useState("")
  const fahrt = fahrten.find((f) => f.id === aktiv)

  async function anlegen(e: React.FormEvent) {
    e.preventDefault()
    if (!neuTitel.trim()) return
    const f = await akte.fahrtAnlegen(slug, { titel: neuTitel.trim(), stationen: [] })
    setNeuTitel("")
    geaendert()
    waehlen(f.id)
  }

  async function stationWeg(i: number) {
    if (!fahrt) return
    await akte.fahrtSpeichern(slug, { ...fahrt, stationen: fahrt.stationen.filter((_, j) => j !== i) })
    geaendert()
  }

  return (
    <aside className="absolute bottom-4 left-4 top-20 z-30 flex w-[320px] flex-col max-[1560px]:top-36 rounded-lg border border-[#222636] bg-[#0d0e14]/95 backdrop-blur" aria-label="Fahrten">
      <div className="flex items-center justify-between border-b border-[#222636] px-4 py-2">
        <span className="font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]">Fahrten</span>
        <button type="button" onClick={schliessen} aria-label="Schließen" className="cursor-pointer p-2 text-[#8A94A0] hover:text-white">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <ul className="space-y-1">
          {fahrten.map((f) => (
            <li key={f.id}>
              <button type="button" onClick={() => waehlen(f.id)}
                className={`w-full cursor-pointer rounded px-3 py-2 text-left text-sm ${f.id === aktiv ? "bg-[#FF1744]/15 text-white" : "hover:bg-white/5"}`}>
                {f.titel} <span className="text-[#8A94A0]">· {f.stationen.length}</span>
              </button>
            </li>
          ))}
        </ul>
        <form onSubmit={anlegen} className="flex gap-2">
          <input aria-label="Neue Fahrt" placeholder="Neue Fahrt, z. B. K3 Deutschland" className={feld} value={neuTitel} onChange={(e) => setNeuTitel(e.target.value)} />
          <button type="submit" aria-label="Fahrt anlegen" className="cursor-pointer rounded border border-[#222636] px-3 hover:border-[#f0c674]"><Plus className="h-4 w-4" /></button>
        </form>

        {fahrt && (
          <>
            <ol className="space-y-1">
              {fahrt.stationen.map((s, i) => (
                <li key={i} className="flex items-center gap-2 rounded border border-[#222636] px-2 py-1.5 text-sm">
                  <span className="w-5 font-[family-name:var(--font-akte-mono)] text-[#8A94A0]">{i + 1}</span>
                  <span className="flex-1 truncate">{s.stichwort || "—"}</span>
                  <button type="button" onClick={() => anfahren(i)} aria-label={`Station ${i + 1} anfahren`} className="cursor-pointer p-1 text-[#8A94A0] hover:text-white"><Play className="h-3.5 w-3.5" /></button>
                  <button type="button" onClick={() => stationWeg(i)} aria-label={`Station ${i + 1} löschen`} className="cursor-pointer p-1 text-[#8A94A0] hover:text-[#FF1744]"><Trash2 className="h-3.5 w-3.5" /></button>
                </li>
              ))}
            </ol>
            <form onSubmit={async (e) => { e.preventDefault(); await stationAufnehmen(stichwort.trim()); setStichwort("") }} className="space-y-2">
              <input aria-label="Stichwort der Station" placeholder="Stichwort (z. B. „Mustermann gründet Nordlicht“)" className={feld} value={stichwort} onChange={(e) => setStichwort(e.target.value)} />
              <button type="submit" className="min-h-10 w-full cursor-pointer rounded bg-[#f0c674] text-sm font-semibold text-black">
                Aktuellen Ausschnitt als Station
              </button>
              <p className="text-xs text-[#8A94A0]">Gewählte Karten (Umschalt + Klick) bleiben im Scheinwerfer, der Rest wird gedimmt.</p>
            </form>
          </>
        )}
      </div>
    </aside>
  )
}
