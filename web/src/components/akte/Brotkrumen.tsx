"use client"

// Brotkrumen: Die Akte › Hauptwand › Nordlicht. Jede Stufe führt eine Ebene hinauf; die Kamera
// startet dort nah an der Mappe, aus der man kam (?aus=), und fährt dann in den Überblick.

import Link from "next/link"
import { ChevronRight } from "lucide-react"

export default function Brotkrumen({ pfad, titelJe, aktuell, slug }: {
  /** Slugs von oben bis vor die aktuelle Wand */
  pfad: string[]
  titelJe: Map<string, string>
  aktuell: string
  slug: string
}) {
  const stufe = "shrink-0 rounded px-1.5 py-1 font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0] transition-colors duration-200 hover:bg-white/10 hover:text-[#f0c674]"
  return (
    <nav aria-label="Brotkrumen" className="mr-2 flex min-w-0 flex-wrap items-center gap-0.5">
      <Link href="/akte" className={stufe}>Die Akte</Link>
      {pfad.map((s, i) => {
        const q = new URLSearchParams()
        if (i > 0) q.set("von", pfad.slice(0, i).join(","))
        q.set("aus", pfad[i + 1] ?? slug)
        return (
          <span key={s} className="flex items-center gap-0.5">
            <ChevronRight className="h-3 w-3 text-[#4a5160]" aria-hidden />
            <Link href={`/akte/${s}?${q.toString()}`} className={stufe}>{titelJe.get(s) ?? s}</Link>
          </span>
        )
      })}
      <ChevronRight className="h-3 w-3 text-[#4a5160]" aria-hidden />
      <span aria-current="page" className="font-[family-name:var(--font-akte-titel)] text-xl uppercase tracking-wide">{aktuell}</span>
    </nav>
  )
}
