// Das Siegel „unterschrieben“: schwarz, roter Ring, gelber Haken – an Karten, Fäden, in der Legende und im Zähler.

import { FARBEN } from "@/lib/akte/faden"

export default function Siegel({ groesse = 22, titel }: { groesse?: number; titel?: string }) {
  return (
    <svg
      width={groesse}
      height={groesse}
      viewBox="0 0 24 24"
      role={titel ? "img" : undefined}
      aria-label={titel}
      aria-hidden={titel ? undefined : true}
      className="shrink-0"
    >
      {titel && <title>{titel}</title>}
      <circle cx="12" cy="12" r="11" fill="#0A0A0F" stroke={FARBEN.rot} strokeWidth="2" />
      <circle cx="12" cy="12" r="7.6" fill="none" stroke={FARBEN.rot} strokeWidth="0.9" strokeDasharray="1.4 1.6" opacity="0.85" />
      <path d="M7.6 12.4 L10.6 15.2 L16.6 8.9" fill="none" stroke="#FFD54F" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
