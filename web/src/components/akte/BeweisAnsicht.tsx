"use client"

// Beweis-Ansicht: das Dokument groß vor die Kamera, wie ein Ermittler, der das Blatt hochhält.
// Bild = die gelb markierte Fundstelle zum Zitat, sonst das Vorschaubild der Seite.

import { useEffect, useRef } from "react"
import { FileText, X } from "lucide-react"
import { akte } from "@/lib/akte/api"
import type { Quelle } from "@/lib/akte/typen"
import { datum, kopieVon } from "./QuellenVorschau"

const normal = (t: string) => t.replace(/\s+/g, " ").replace(/[„“"»«]/g, "").trim().toLowerCase()

export function bildFuerBeweis(q: Quelle, zitat?: string): number | null {
  const fundstellen = q.stand?.fundstellen ?? []
  if (zitat) {
    const z = normal(zitat)
    const passend = fundstellen.find((f) => f.zitat && (normal(f.zitat).startsWith(z.slice(0, 40)) || z.startsWith(normal(f.zitat).slice(0, 40))))
    if (passend) return passend.id
  }
  return fundstellen[0]?.id ?? q.stand?.vorschau ?? null
}

interface Props {
  quelle: Quelle
  zitat?: string
  schliessen: () => void
  /** Render-Modus: Einblenden (0→1) und Ausblenden (0→1) kommen aus der Zeit, ohne Schließknopf. */
  render?: { rein: number; raus: number }
}

export default function BeweisAnsicht({ quelle: q, zitat, schliessen, render }: Props) {
  const bild = bildFuerBeweis(q, zitat)
  const kopie = kopieVon(q)
  const zeile = [q.herausgeber, datum(q.veroeffentlicht_am)].filter(Boolean).join(" · ")
  const zu = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (render) return
    const vorher = document.activeElement as HTMLElement | null
    zu.current?.focus({ preventScroll: true })
    return () => vorher?.focus?.({ preventScroll: true })
  }, [render])
  // Render-Modus: Hintergrund blendet auf, das Blatt schwebt von unten ein und dreht sich gerade.
  const sicht = render ? render.rein * (1 - render.raus) : 1
  const hinten = render ? { backgroundColor: `rgba(0,0,0,${0.75 * sicht})`, backdropFilter: `blur(${3 * sicht}px)` } : undefined
  const blatt = render
    ? {
      opacity: sicht,
      transform: `translateY(${60 * (1 - render.rein) - 30 * render.raus}px) rotate(${-5 + 3.8 * render.rein}deg) scale(${0.96 + 0.04 * render.rein})`,
    }
    : undefined
  const unten = render ? { opacity: Math.max(0, (render.rein - 0.4) / 0.6) * (1 - render.raus) } : undefined
  return (
    <div
      role="dialog"
      aria-modal="true"
      data-beweis
      aria-label={`Beweisstück: ${q.titel}`}
      className={render
        ? "absolute inset-0 z-40 flex flex-col items-center justify-center gap-6 p-[4vh]"
        : "akte-beweis-rein absolute inset-0 z-40 flex flex-col items-center justify-center gap-6 bg-black/75 p-[4vh] backdrop-blur-[3px]"}
      style={hinten}
      onClick={schliessen}
    >
      {!render && <button
        ref={zu}
        type="button"
        onClick={schliessen}
        aria-label="Beweis-Ansicht schließen"
        className="absolute right-6 top-6 cursor-pointer rounded-full p-2 text-white opacity-0 transition-opacity duration-200 hover:opacity-100 focus-visible:opacity-100"
      >
        <X className="h-6 w-6" />
      </button>}
      <div
        className={`${render ? "" : "akte-blatt rotate-[-1.2deg] "}relative max-h-[62vh] max-w-[min(86vw,1400px)] shrink bg-[#fbf8f1] p-4 shadow-[0_30px_80px_rgba(0,0,0,0.7)]`}
        style={blatt}
      >
        <span className="absolute -right-3 -top-4 z-10 rotate-[6deg] border-[3px] border-[#C8102E] bg-[#fbf8f1] px-3 py-1 font-[family-name:var(--font-akte-mono)] text-sm font-semibold uppercase tracking-[0.25em] text-[#C8102E]">
          Beweisstück
        </span>
        {bild ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={akte.dateiUrl(bild)} alt={q.titel} className="block max-h-[calc(62vh-2rem)] w-auto max-w-full object-contain" />
        ) : (
          <div className="flex h-[40vh] w-[50vw] flex-col items-center justify-center gap-3 text-[#141318]">
            <FileText className="h-16 w-16 opacity-40" aria-hidden />
            <p className="max-w-[40vw] text-center text-2xl font-semibold">{q.titel}</p>
          </div>
        )}
      </div>

      {zitat && (
        <blockquote style={unten} className="shrink-0 max-w-[min(80vw,1200px)] text-center text-[clamp(20px,2.4vw,34px)] font-medium leading-snug text-[#F2F7FB]">
          <span className="box-decoration-clone bg-[linear-gradient(transparent_55%,rgba(255,213,79,0.55)_55%)] px-1">
            „{zitat}“
          </span>
        </blockquote>
      )}

      <p style={unten} className="shrink-0 font-[family-name:var(--font-akte-mono)] text-[clamp(12px,1.1vw,16px)] uppercase tracking-[0.2em] text-[#8A94A0]">
        {[q.titel !== zeile ? q.titel : "", zeile].filter(Boolean).join(" — ")}
        {kopie && <> · gesichert {datum(kopie.gesichert_am)} · SHA-256 {kopie.sha256.slice(0, 12)}</>}
      </p>
    </div>
  )
}
