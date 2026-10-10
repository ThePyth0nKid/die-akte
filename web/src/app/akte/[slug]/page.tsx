"use client"

import { use } from "react"
import Wand from "@/components/akte/Wand"

type Suche = Record<string, string | string[] | undefined>
const eins = (w: string | string[] | undefined) => (Array.isArray(w) ? w[0] : w) || undefined

export default function AkteBoard({ params, searchParams }: { params: Promise<{ slug: string }>; searchParams: Promise<Suche> }) {
  const { slug } = use(params)
  const q = use(searchParams)
  // key: jedes Board bekommt eine frische Wand (Auswahl, Scheinwerfer, Fahrt wandern nicht mit).
  return <Wand key={slug} slug={slug} ankunft={{ von: eins(q.von), karte: eins(q.karte), aus: eins(q.aus) }} />
}
