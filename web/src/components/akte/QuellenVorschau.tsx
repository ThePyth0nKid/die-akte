"use client"

// Link-Vorschau einer Quelle: Bild, Titel, Herausgeber und der Sicherungsstand —
// was ist kopiert, was liegt bei archive.org, welche Prüfsumme belegt die Kopie.

import { useEffect, useRef, useState } from "react"
import { Archive, Check, Copy, ExternalLink, FileText, Loader2, Maximize2, Pin, RefreshCw, TriangleAlert } from "lucide-react"
import { akte } from "@/lib/akte/api"
import type { Quelle, Sicherung, SicherungArt } from "@/lib/akte/typen"

const ART_NAME: Partial<Record<SicherungArt, string>> = {
  original: "Kopie",
  anhang: "Anhang",
  archive_org: "archive.org",
  screenshot: "Bild",
  seite_pdf: "PDF",
  video_lokal: "Video (D:)",
}

export function datum(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" })
}

/** Die Sicherung, die als eigene Kopie zählt: Original oder Anhang, fertig. */
export function kopieVon(q: Quelle): Sicherung | undefined {
  return q.stand?.sicherungen.find((s) => (s.art === "original" || s.art === "anhang") && s.status === "fertig")
}

interface Props {
  quelle: Quelle
  zitat?: string
  anDieWand?: (q: Quelle) => void
  zeigen?: (q: Quelle, zitat?: string) => void
  kompakt?: boolean
  /** Mitglieder: kein Sicherungsstand, kein „Neu sichern“. */
  nurLesen?: boolean
}

export default function QuellenVorschau({ quelle: start, zitat, anDieWand, zeigen, kompakt, nurLesen }: Props) {
  const [q, setQ] = useState(start)
  const [laeuft, setLaeuft] = useState(false)
  const [kopiert, setKopiert] = useState(false)
  const da = useRef(true)
  useEffect(() => () => { da.current = false }, [])
  const kopie = kopieVon(q)
  const stand = q.stand?.sicherungen.filter((s) => ART_NAME[s.art]) ?? []

  async function neuSichern() {
    setLaeuft(true)
    try {
      await akte.quelleSichern(q.id)
      // Die Sicherung läuft im Hintergrund; nach kurzer Zeit nachsehen.
      await new Promise((fertig) => setTimeout(fertig, 8000))
      const neu = await akte.quelle(q.id)
      if (da.current) setQ(neu)
    } catch {
      // Stand bleibt wie er war; der Knopf wird wieder frei.
    } finally {
      if (da.current) setLaeuft(false)
    }
  }

  return (
    <div className="flex gap-3 rounded border border-[#222636] bg-[#0A0A0F] p-2.5">
      {!kompakt && (
        <div className="flex h-[72px] w-[72px] shrink-0 items-center justify-center overflow-hidden rounded-sm bg-[#15161d]">
          {q.stand?.vorschau ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={akte.dateiUrl(q.stand.vorschau)} alt="" className="h-full w-full object-cover" loading="lazy" />
          ) : (
            <FileText className="h-7 w-7 text-[#8A94A0]" aria-hidden />
          )}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="line-clamp-2 text-sm font-semibold leading-snug">
          <span className="mr-1" title={q.guete === "primaer" ? "Original geöffnet" : "Presse / Sekundär"}>
            {q.guete === "primaer" ? "★" : "☆"}
          </span>
          {q.titel}
        </p>
        <p className="truncate text-xs text-[#8A94A0]">
          {[q.herausgeber, datum(q.veroeffentlicht_am)].filter(Boolean).join(" · ")}
        </p>
        {zitat && <p className="mt-1 line-clamp-3 border-l-2 border-[#FFD54F] pl-2 text-xs italic text-[#F2F7FB]/85">„{zitat}“</p>}

        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {!nurLesen && stand.length === 0 && q.url && (
            <span className="rounded bg-[#FFB300]/15 px-1.5 py-0.5 text-[11px] text-[#FFB300]">noch nicht gesichert</span>
          )}
          {stand.map((s) => (
            <span
              key={s.id}
              title={s.status === "fehler" ? s.fehler : s.gesichert_am ? `gesichert ${datum(s.gesichert_am)}` : s.status}
              className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] ${
                s.status === "fertig" ? "bg-[#22E07A]/12 text-[#22E07A]" : s.status === "fehler" ? "bg-[#FF1744]/12 text-[#FF1744]" : "bg-white/5 text-[#8A94A0]"
              }`}
            >
              {s.status === "fertig" ? <Check className="h-3 w-3" aria-hidden /> : s.status === "fehler" ? <TriangleAlert className="h-3 w-3" aria-hidden /> : <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
              {ART_NAME[s.art]}
            </span>
          ))}
          {kopie && (
            <button
              type="button"
              title="Prüfsumme SHA-256 kopieren"
              onClick={() => { navigator.clipboard?.writeText(kopie.sha256); setKopiert(true); setTimeout(() => setKopiert(false), 1500) }}
              className="flex cursor-pointer items-center gap-1 rounded bg-white/5 px-1.5 py-0.5 font-[family-name:var(--font-akte-mono)] text-[11px] text-[#8A94A0] hover:text-white"
            >
              <Copy className="h-3 w-3" aria-hidden /> {kopiert ? "kopiert" : kopie.sha256.slice(0, 10)}
            </button>
          )}
        </div>

        <div className="mt-1.5 flex flex-wrap gap-3 text-xs">
          {q.url && (
            <a href={q.url} target="_blank" rel="noreferrer noopener" className="flex items-center gap-1 text-[#f0c674] hover:text-white">
              <ExternalLink className="h-3 w-3" aria-hidden /> Link
            </a>
          )}
          {kopie && (
            <a href={akte.dateiUrl(kopie.id)} target="_blank" rel="noreferrer noopener" className="flex items-center gap-1 text-[#f0c674] hover:text-white">
              <FileText className="h-3 w-3" aria-hidden /> Kopie öffnen
            </a>
          )}
          {q.archiv_url && (
            <a href={q.archiv_url} target="_blank" rel="noreferrer noopener" className="flex items-center gap-1 text-[#f0c674] hover:text-white">
              <Archive className="h-3 w-3" aria-hidden /> archive.org
            </a>
          )}
          {q.url && !nurLesen && (
            <button type="button" onClick={neuSichern} disabled={laeuft} className="flex cursor-pointer items-center gap-1 text-[#8A94A0] hover:text-white disabled:opacity-50">
              <RefreshCw className={`h-3 w-3 ${laeuft ? "animate-spin" : ""}`} aria-hidden /> {laeuft ? "sichert …" : "Neu sichern"}
            </button>
          )}
          {zeigen && (
            <button type="button" onClick={() => zeigen(q, zitat)} className="flex cursor-pointer items-center gap-1 text-[#8A94A0] hover:text-white">
              <Maximize2 className="h-3 w-3" aria-hidden /> Groß zeigen
            </button>
          )}
          {anDieWand && (
            <button type="button" onClick={() => anDieWand(q)} className="flex cursor-pointer items-center gap-1 text-[#8A94A0] hover:text-white">
              <Pin className="h-3 w-3" aria-hidden /> An die Wand
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
