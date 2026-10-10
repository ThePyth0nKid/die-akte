"use client"

// Das Bündel: viele Fäden zwischen einer Karte und einer Mappe (oder zwei Mappen) als ein dicker Strang.
// Klick öffnet die Liste der Einzelfäden mit ihren Quellen. Bewusst keine Geldsumme (siehe mappen.py).

import { memo } from "react"
import { BaseEdge, EdgeLabelRenderer, useStore, type Edge, type EdgeProps } from "@xyflow/react"
import { EyeOff, Pencil, X } from "lucide-react"
import { durchhang, FARBEN, zeitraum } from "@/lib/akte/faden"
import { buendelBreite, buendelText } from "@/lib/akte/mappen"
import { AUSSAGE_NAMEN, VERBINDUNG_NAMEN, type Buendel, type EntitaetKurz, type Verbindung } from "@/lib/akte/typen"
import QuellenVorschau from "./QuellenVorschau"

export type BuendelDaten = {
  buendel: Buendel
  gedimmt: boolean
  aufnahme: boolean
  papier: boolean
  versatz: number
  /** Render-Modus: Helligkeit aus der Zeit. */
  render?: { hell: number }
  /** Klick auf die Aufschrift öffnet die Liste der Einzelfäden (wie ein Klick auf den Strang). */
  oeffnen?: () => void
}
export type BuendelKantenTyp = Edge<BuendelDaten, "buendel">

/** Ab diesem Zoom steht die Aufschrift immer da; weiter draußen würden sich die Kästen stapeln. */
const AUFSCHRIFT_AB_ZOOM = 0.3

export const BuendelKante = memo(function BuendelKante({
  id, sourceX, sourceY, targetX, targetY, data, selected,
}: EdgeProps<BuendelKantenTyp>) {
  const zoom = useStore((z) => z.transform[2])
  if (!data) return null
  const b = data.buendel
  const { pfad, mitteX, mitteY } = durchhang(sourceX, sourceY, targetX, targetY)
  // Nur ausgeblendete Fäden: ein dünner, grauer Strich, damit die Werkstatt sie wiederfindet.
  const leer = b.faeden.length === 0
  const breite = leer ? 2 : buendelBreite(b.faeden.length)
  const { zahl, typen } = buendelText(b)
  const versteckt = b.ausgeblendet?.length ?? 0
  const unbelegt = (b.je_art.verdacht ?? 0) + (b.je_art.meinung ?? 0)
  const hell = data.render ? data.render.hell : data.gedimmt ? 0.1 : 1
  const zeigen = data.render ? hell > 0.01 : !data.gedimmt && (zoom >= AUFSCHRIFT_AB_ZOOM || selected)
  return (
    <>
      {!leer && (
        <path d={pfad} fill="none" stroke="#5a0714" strokeWidth={breite + 6} strokeLinecap="round"
          style={{ opacity: 0.85 * hell, filter: "drop-shadow(0 4px 3px rgba(0,0,0,0.6))" }} />
      )}
      <BaseEdge
        id={id}
        path={pfad}
        style={{
          stroke: leer ? "#8A94A0" : FARBEN.rot,
          strokeDasharray: leer ? "6 6" : undefined,
          strokeWidth: selected && !data.aufnahme ? breite + 2 : breite,
          strokeLinecap: "round",
          opacity: 0.95 * hell,
          transition: data.render ? undefined : "opacity 300ms ease-out",
        }}
        interactionWidth={28}
      />
      {/* Die Einzelfäden als feine Linien im Strang, damit er wie ein Bündel Schnur aussieht. */}
      <path d={pfad} fill="none" stroke="#ffffff" strokeWidth={Math.max(1, breite / 5)} strokeDasharray="14 10"
        strokeLinecap="round" style={{ opacity: 0.22 * hell, pointerEvents: "none" }} />
      {zeigen && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-auto absolute flex cursor-pointer flex-col items-center"
            style={{ transform: `translate(-50%, -50%) translate(${mitteX}px, ${mitteY + data.versatz}px)`, opacity: data.render ? hell : undefined }}
            role={data.oeffnen ? "button" : undefined}
            tabIndex={data.oeffnen ? 0 : undefined}
            aria-label={data.oeffnen ? `${zahl}: Einzelfäden mit Quellen zeigen` : undefined}
            onClick={data.oeffnen}
            onKeyDown={(e) => { if (data.oeffnen && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); data.oeffnen() } }}
          >
            <span
              className={`border-2 text-center shadow-lg ${b.faeden.length === 1 ? "px-2 py-0.5" : "px-3 py-1"}`}
              style={{ borderColor: FARBEN.rot, background: data.papier ? "#fbf8f1" : "#0A0A0F", color: data.papier ? "#141318" : "#F2F7FB" }}
            >
              {leer ? (
                <span className="block whitespace-nowrap font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-wider text-[#8A94A0]">
                  {versteckt} ausgeblendet
                </span>
              ) : b.faeden.length === 1 ? (
                // Ein einzelner Faden: eine Zeile, klein — sonst stapeln sich die Kästen auf der Hauptwand.
                <span className="block whitespace-nowrap font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-wider">{zahl} · {typen}</span>
              ) : (
                <>
                  <span className="block font-[family-name:var(--font-akte-titel)] text-[22px] uppercase leading-none tracking-wide">{zahl}</span>
                  {typen && <span className="mt-0.5 block font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-wider opacity-70">{typen}</span>}
                </>
              )}
              {!leer && (unbelegt > 0 || b.mit_betrag > 0 || versteckt > 0) && (
                <span className="mt-0.5 block font-[family-name:var(--font-akte-mono)] text-[10px] uppercase tracking-wider text-[#FFB300]">
                  {[b.mit_betrag > 0 && `${b.mit_betrag} mit Betrag`, unbelegt > 0 && `${unbelegt} nicht belegt`,
                    versteckt > 0 && `${versteckt} ausgeblendet`].filter(Boolean).join(" · ")}
                </span>
              )}
            </span>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
})

const etikett = "mb-1 block font-[family-name:var(--font-akte-mono)] text-[11px] uppercase tracking-widest text-[#8A94A0]"

function betragText(v: Verbindung) {
  if (!v.betrag) return ""
  const zahl = Number(v.betrag)
  if (!Number.isFinite(zahl)) return ""
  return `${zahl.toLocaleString("de-DE", { maximumFractionDigits: 2 })} ${v.waehrung === "EUR" ? "€" : v.waehrung === "USD" ? "$" : v.waehrung}`
}

/** Die Einzelfäden eines Bündels mit Quellen. Werkstatt: bearbeiten, hier aus- und wieder einblenden; Mitglieder: nur lesen. */
export function BuendelLeiste({ buendel, faeden, namen, titelVon, titelNach, schliessen, bearbeiten, ausblenden }: {
  buendel: Buendel
  faeden: Verbindung[]
  namen: Map<number, EntitaetKurz>
  titelVon: string
  titelNach: string
  schliessen: () => void
  bearbeiten?: (v: Verbindung) => void
  ausblenden?: (v: Verbindung) => void
}) {
  const ids = new Set([...buendel.faeden, ...(buendel.ausgeblendet ?? [])])
  const liste = faeden.filter((v) => ids.has(v.id))
  return (
    <aside className="absolute bottom-0 right-0 top-0 z-30 flex w-[440px] max-w-full flex-col border-l border-[#222636] bg-[#0d0e14]/95 backdrop-blur" aria-label="Bündel">
      <div className="flex items-start justify-between gap-3 border-b border-[#222636] px-5 py-3">
        <div>
          <span className={etikett}>Bündel · {buendelText(buendel).zahl}</span>
          <h2 className="font-[family-name:var(--font-akte-titel)] text-2xl uppercase leading-tight">{titelVon} ↔ {titelNach}</h2>
        </div>
        <button type="button" onClick={schliessen} aria-label="Schließen" className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded hover:bg-white/10">
          <X className="h-4 w-4" />
        </button>
      </div>
      <ul className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {liste.map((v) => (
          <li key={v.id} className={`rounded border border-[#222636] p-3 ${v.ausgeblendet ? "opacity-55" : ""}`}>
            <span className="flex items-baseline justify-between gap-2">
              <span className="font-semibold">{namen.get(v.von)?.name ?? "?"} → {namen.get(v.nach)?.name ?? "?"}</span>
              <span className="shrink-0 font-[family-name:var(--font-akte-mono)] text-[11px] text-[#8A94A0]">{zeitraum(v)}</span>
            </span>
            <span className="mt-1 block text-sm text-[#8A94A0]">
              {v.beschreibung || VERBINDUNG_NAMEN[v.typ]}
              {betragText(v) && <> · <strong className="text-[#F2F7FB]">{betragText(v)}</strong></>}
              {v.aussageart !== "belegt" && <> · <span className="text-[#FFB300]">{AUSSAGE_NAMEN[v.aussageart]}</span></>}
            </span>
            <div className="mt-2 space-y-1.5">
              {v.belege.map((b) => b.quelle_detail && (
                <QuellenVorschau key={b.id ?? b.quelle} quelle={b.quelle_detail} zitat={b.zitat_woertlich || undefined} nurLesen />
              ))}
            </div>
            {(bearbeiten || ausblenden) && (
              <div className="mt-2 flex gap-2">
                {bearbeiten && (
                  <button type="button" onClick={() => bearbeiten(v)} className="flex min-h-9 cursor-pointer items-center gap-1.5 rounded px-2 text-sm text-[#8A94A0] hover:bg-white/10 hover:text-[#F2F7FB]">
                    <Pencil className="h-3.5 w-3.5" aria-hidden /> Bearbeiten
                  </button>
                )}
                {ausblenden && (
                  <button type="button" onClick={() => ausblenden(v)} className="flex min-h-9 cursor-pointer items-center gap-1.5 rounded px-2 text-sm text-[#8A94A0] hover:bg-white/10 hover:text-[#F2F7FB]">
                    <EyeOff className="h-3.5 w-3.5" aria-hidden /> {v.ausgeblendet ? "Wieder einblenden" : "Auf dieser Wand ausblenden"}
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
      <p className="border-t border-[#222636] px-5 py-3 text-xs text-[#8A94A0]">
        Jeder Faden trägt seine eigene Quelle. Beträge stehen einzeln; eine Summe über das Bündel wäre keine belegte Aussage.
      </p>
    </aside>
  )
}
