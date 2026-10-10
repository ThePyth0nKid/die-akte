"use client"

// Render-Ansicht einer Fahrt: nur die Wand, keine Bedienelemente. Das Bild ist eine reine
// Funktion der Zeit; scripts/akte/render_fahrt.cjs ruft window.__akteRender auf.

import { use, useMemo } from "react"
import Wand, { type RenderAuftrag } from "@/components/akte/Wand"
import { FORMAT_KENNUNGEN, type FormatKennung } from "@/lib/akte/aufnahme"

type Suche = Record<string, string | string[] | undefined>

const eins = (w: string | string[] | undefined) => (Array.isArray(w) ? w[0] : w) ?? ""

export default function AkteRender({ params, searchParams }: { params: Promise<{ slug: string }>; searchParams: Promise<Suche> }) {
  const { slug } = use(params)
  const q = use(searchParams)
  const auftrag = useMemo((): RenderAuftrag | null => {
    const fahrtId = Number(eins(q.fahrt))
    const format = eins(q.format) || "16x9"
    if (!Number.isInteger(fahrtId) || fahrtId <= 0 || !FORMAT_KENNUNGEN.includes(format as FormatKennung)) return null
    const look = eins(q.look)
    const halte = Number(eins(q.halte) || 3000)
    // Video-Schalter: Abdunkeln außerhalb des Fokus, Fadenetiketten, Karten weglassen, unten freihalten
    const dimm = Number(eins(q.dimm))
    const frei = Number(eins(q.frei_unten))
    const ohne = eins(q.ohne).split(",").map(Number).filter((n) => Number.isInteger(n) && n > 0)
    return {
      fahrtId,
      format: format as FormatKennung,
      look: look === "papier" || look === "dunkel" ? look : undefined,
      stichworte: eins(q.stichworte) === "1",
      legende: eins(q.legende) === "1",
      halteMs: Number.isFinite(halte) ? Math.min(8000, Math.max(1000, halte)) : 3000,
      dimm: eins(q.dimm) !== "" && Number.isFinite(dimm) ? Math.min(0.12, Math.max(0, dimm)) : undefined,
      etiketten: eins(q.etiketten) !== "aus",
      ohne,
      freiUnten: Number.isFinite(frei) && frei > 0 ? Math.min(600, Math.round(frei)) : 0,
    }
  }, [q])
  if (!auftrag) return <p role="alert" className="p-6">Render-Auftrag unvollständig: fahrt=&lt;ID&gt;&amp;format=16x9|9x16|1x1|oben</p>
  return <Wand slug={slug} render={auftrag} />
}
