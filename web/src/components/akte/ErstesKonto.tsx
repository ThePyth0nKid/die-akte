"use client"

// Solange die Akte noch kein Konto hat, zeigen Login und Übersicht deutlich den Weg zum ersten Konto
// statt „Hier ist noch nichts freigeschaltet“.

import Link from "next/link"
import { useEffect, useState } from "react"
import { KeyRound } from "lucide-react"
import { einrichtungZustand } from "@/lib/einrichtung"

/** true, sobald feststeht, dass die Einrichtung offen ist; sonst false (auch während der Abfrage). */
export function useEinrichtungOffen(): boolean {
  const [offen, setOffen] = useState(false)
  useEffect(() => {
    const ac = new AbortController()
    einrichtungZustand(ac.signal).then((z) => setOffen(z === "offen")).catch(() => undefined)
    return () => ac.abort()
  }, [])
  return offen
}

export default function ErstesKontoHinweis() {
  return (
    <section
      aria-labelledby="erstes-konto-titel"
      className="flex gap-4 rounded-lg border-2 border-[#FF1744] bg-[#FF1744]/10 p-5 text-[#F2F7FB]"
    >
      <span aria-hidden className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#FF1744]">
        <KeyRound className="h-5 w-5 text-white" />
      </span>
      <div>
        <h2 id="erstes-konto-titel" className="font-[family-name:var(--font-akte-titel)] text-3xl uppercase leading-none tracking-wide">
          Erstes Konto anlegen
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-[#C9CED6]">
          Die Ultra-Akte ist neu und hat noch kein Konto. Lege jetzt dein eigenes an. Du brauchst dafür den
          Einrichtungscode: Der Starter trägt ihn ein, wenn er den Browser öffnet. Fehlt er, starte START-AKTE noch
          einmal (Doppelklick).
        </p>
        <Link
          href="/akte/einrichten"
          className="mt-4 inline-flex min-h-11 items-center rounded-md bg-[#FF1744] px-5 font-semibold text-white transition-colors duration-200 hover:bg-[#ff3d63] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f0c674]"
        >
          Erstes Konto anlegen
        </Link>
      </div>
    </section>
  )
}
