"use client"

// Der rote Faden: hängt durch wie eine Schnur, Aussehen nach Aussageart.

import { memo } from "react"
import { BaseEdge, EdgeLabelRenderer, useStore, type Edge, type EdgeProps } from "@xyflow/react"
import { durchhang, fadenStil, zeitraum } from "@/lib/akte/faden"
import type { Verbindung } from "@/lib/akte/typen"

export type FadenDaten = {
  verbindung: Verbindung
  gedimmt: boolean
  hervorgehoben: boolean
  aufnahme: boolean
  papier: boolean
  versatz: number
  /** Render-Modus: alles aus der Zeit — Helligkeit, Hervorhebung, wie weit der Faden gezogen ist. */
  render?: { hell: number; hervor: number; zug: number; dimm?: number; etikett?: boolean }
}

/** Ab diesem Zoom stehen Beschriftungen immer da; darunter nur bei Auswahl oder im Scheinwerfer. */
const ETIKETT_AB_ZOOM = 0.7
export type FadenKantenTyp = Edge<FadenDaten, "faden">

export const FadenKante = memo(function FadenKante({
  id, sourceX, sourceY, targetX, targetY, data, selected,
}: EdgeProps<FadenKantenTyp>) {
  const zoom = useStore((z) => z.transform[2])
  if (!data) return null
  const v = data.verbindung
  const stil = fadenStil(v.aussageart)
  const { pfad, mitteX, mitteY } = durchhang(sourceX, sourceY, targetX, targetY)
  const text = v.beschreibung || ""
  const offen = !data.aufnahme && v.befunde.length > 0
  const r = data.render
  const etikettDeckkraft = r ? r.hell * (zoom >= ETIKETT_AB_ZOOM ? 1 : r.hervor) : 1
  // Im Video-Render können die Etiketten ganz aus sein: sonst steht eine andere Zahl groß im Bild, als gesprochen wird.
  const zeigen = r ? r.etikett !== false && etikettDeckkraft > 0.01 : !data.gedimmt && (zoom >= ETIKETT_AB_ZOOM || selected || data.hervorgehoben)
  // Im Render-Modus zieht sich der durchgezogene Faden über die Zeit statt per CSS-Animation.
  const zieht = r && !stil.strich

  return (
    <>
      <BaseEdge
        id={id}
        path={pfad}
        className={r ? undefined : stil.strich ? "akte-faden-blende" : "akte-faden-zieh"}
        // Nur der durchgezogene Faden „zieht sich“ (Strichlänge relativ zu 1);
        // gestrichelte Fäden brauchen echte Pixel für ihr Muster.
        pathLength={stil.strich ? undefined : 1}
        style={{
          stroke: stil.farbe,
          strokeWidth: selected && !data.aufnahme ? stil.breite + 2 : stil.breite,
          strokeDasharray: zieht ? 1 : stil.strich,
          strokeDashoffset: zieht ? 1 - r.zug : undefined,
          strokeLinecap: "round",
          opacity: r ? (r.dimm ?? 0.08) + (0.95 - (r.dimm ?? 0.08)) * r.hell : data.gedimmt ? 0.08 : 0.95,
          filter: "drop-shadow(0 3px 2px rgba(0,0,0,0.55))",
          transition: r ? undefined : "opacity 300ms ease-out",
        }}
        interactionWidth={18}
      />
      {(text || stil.stempel) && zeigen && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-auto absolute flex flex-col items-center gap-1"
            style={{
              transform: `translate(-50%, -50%) translate(${mitteX}px, ${mitteY + data.versatz}px)`,
              opacity: r ? etikettDeckkraft : undefined,
            }}
          >
            {stil.stempel && (
              <span
                className="rotate-[-4deg] border-2 px-2 py-0.5 font-[family-name:var(--font-akte-mono)] text-[11px] font-semibold tracking-[0.25em]"
                style={{ borderColor: stil.farbe, color: stil.farbe, background: data.papier ? "#fbf8f1" : "#0A0A0F" }}
              >
                {stil.stempel}
              </span>
            )}
            {text && (
              <span
                className="max-w-[220px] px-2 py-0.5 text-center text-[13px] leading-tight shadow"
                style={{
                  background: data.papier ? "#fbf8f1" : "#15161d",
                  color: data.papier ? "#141318" : "#F2F7FB",
                  border: offen ? "1px solid #FFB300" : "1px solid transparent",
                }}
              >
                {text}
                <span className="ml-1 font-[family-name:var(--font-akte-mono)] text-[11px] opacity-60">
                  {zeitraum(v, text)}
                </span>
              </span>
            )}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
})

export const kantenTypen = { faden: FadenKante }
