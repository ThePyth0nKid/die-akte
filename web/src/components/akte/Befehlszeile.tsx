"use client"

// Strg+K: Karte suchen und aufs Board holen, oder neu anlegen.

import { useEffect, useRef, useState } from "react"
import { Plus, Search } from "lucide-react"
import { akte } from "@/lib/akte/api"
import { TYP_NAMEN, type EntitaetKurz, type EntitaetTyp } from "@/lib/akte/typen"

// Wird bei jedem Öffnen neu eingehängt: frischer Zustand ohne Rücksetz-Effekt.
interface Props {
  schliessen: () => void
  gewaehlt: (e: EntitaetKurz) => void
  titel?: string
}

export default function Befehlszeile({ schliessen, gewaehlt, titel = "Karte aufs Board holen" }: Props) {
  const [q, setQ] = useState("")
  const [treffer, setTreffer] = useState<EntitaetKurz[]>([])
  const [aktiv, setAktiv] = useState(0)
  const [typ, setTyp] = useState<EntitaetTyp>("person")
  const [fehler, setFehler] = useState("")
  const eingabe = useRef<HTMLInputElement>(null)

  useEffect(() => {
    eingabe.current?.focus()
  }, [])

  useEffect(() => {
    const t = setTimeout(() => {
      akte.suchen(q).then((r) => { setTreffer(r); setAktiv(0) }).catch(() => setTreffer([]))
    }, 150)
    return () => clearTimeout(t)
  }, [q])

  async function neuAnlegen() {
    try {
      const e = await akte.entitaetAnlegen({ name: q.trim(), typ })
      gewaehlt(e)
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Anlegen fehlgeschlagen.")
    }
  }

  const kannNeu = q.trim().length > 1 && !treffer.some((t) => t.name.toLowerCase() === q.trim().toLowerCase())
  const anzahl = treffer.length + (kannNeu ? 1 : 0)

  function taste(e: React.KeyboardEvent) {
    if (e.key === "Escape") schliessen()
    if (e.key === "ArrowDown") { e.preventDefault(); setAktiv((a) => Math.min(a + 1, anzahl - 1)) }
    if (e.key === "ArrowUp") { e.preventDefault(); setAktiv((a) => Math.max(a - 1, 0)) }
    if (e.key === "Enter") {
      e.preventDefault()
      if (aktiv < treffer.length) gewaehlt(treffer[aktiv])
      else if (kannNeu) neuAnlegen()
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[12vh]" onMouseDown={schliessen}>
      <div
        role="dialog"
        aria-label={titel}
        className="w-full max-w-xl overflow-hidden rounded-lg border border-[#222636] bg-[#101117] shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-[#222636] px-4">
          <Search className="h-4 w-4 text-[#8A94A0]" aria-hidden />
          <input
            ref={eingabe}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={taste}
            aria-label={titel}
            placeholder={titel}
            className="h-14 flex-1 bg-transparent text-lg outline-none"
          />
        </div>
        <ul className="max-h-[50vh] overflow-y-auto py-2">
          {treffer.map((t, i) => (
            <li key={t.id}>
              <button
                type="button"
                onMouseEnter={() => setAktiv(i)}
                onClick={() => gewaehlt(t)}
                className={`flex w-full cursor-pointer items-baseline justify-between gap-3 px-4 py-2 text-left ${i === aktiv ? "bg-[#FF1744]/15" : ""}`}
              >
                <span>
                  <span className="font-semibold">{t.name}</span>
                  {t.kurzbeschreibung && <span className="ml-2 text-sm text-[#8A94A0]">{t.kurzbeschreibung}</span>}
                </span>
                <span className="font-[family-name:var(--font-akte-mono)] text-[11px] uppercase text-[#8A94A0]">
                  {TYP_NAMEN[t.typ]}
                </span>
              </button>
            </li>
          ))}
          {kannNeu && (
            <li className={`flex items-center gap-3 px-4 py-2 ${aktiv === treffer.length ? "bg-[#FF1744]/15" : ""}`}>
              <button type="button" onClick={neuAnlegen} className="flex flex-1 cursor-pointer items-center gap-2 text-left">
                <Plus className="h-4 w-4 text-[#FF1744]" aria-hidden />
                Neu anlegen: <strong>{q.trim()}</strong>
              </button>
              <label className="sr-only" htmlFor="neu-typ">Typ</label>
              <select
                id="neu-typ"
                value={typ}
                onChange={(e) => setTyp(e.target.value as EntitaetTyp)}
                className="rounded border border-[#222636] bg-[#0A0A0F] px-2 py-1 text-sm"
              >
                {Object.entries(TYP_NAMEN).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
              </select>
            </li>
          )}
          {!treffer.length && !kannNeu && <li className="px-4 py-3 text-sm text-[#8A94A0]">Name tippen …</li>}
        </ul>
        {fehler && <p role="alert" className="border-t border-[#222636] px-4 py-2 text-sm text-[#FF1744]">{fehler}</p>}
      </div>
    </div>
  )
}
