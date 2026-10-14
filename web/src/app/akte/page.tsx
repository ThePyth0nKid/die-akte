"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { Download, Plus } from "lucide-react"
import ErstesKontoHinweis, { useEinrichtungOffen } from "@/components/akte/ErstesKonto"
import KontoKnopf from "@/components/akte/KontoKnopf"
import { akte, AkteFehler } from "@/lib/akte/api"
import type { Board } from "@/lib/akte/typen"

export default function AkteStart() {
  const [boards, setBoards] = useState<Board[] | null>(null)
  const [fehler, setFehler] = useState("")
  const [titel, setTitel] = useState("")
  const [laeuft, setLaeuft] = useState(false)
  // Mitglieder bekommen nur freigeschaltete Boards mit darf_bearbeiten = false.
  const redaktion = boards?.some((b) => b.darf_bearbeiten) ?? false
  const router = useRouter()
  // Noch kein Konto in der Akte: statt „Hier ist noch nichts freigeschaltet“ der Weg zum ersten Konto.
  const einrichtungOffen = useEinrichtungOffen()

  // Lesende (Mitglieder, Besucher ohne Konto) landen direkt auf der Hauptwand, wenn es genau eine gibt:
  // So reicht ein kurzer Link auf /akte.
  useEffect(() => {
    if (!boards || redaktion) return
    const slugs = new Set(boards.map((b) => b.slug))
    const wurzeln = boards.filter((b) => !(b.eltern ?? []).some((e) => slugs.has(e)))
    if (wurzeln.length === 1) router.replace(`/akte/${wurzeln[0].slug}`)
  }, [boards, redaktion, router])

  useEffect(() => {
    akte.boards().then(setBoards).catch((e) => {
      // Ohne Anmeldung und ohne öffentliche Boards: keine Fehlermeldung, sondern der Weg zum Login.
      if (e instanceof AkteFehler && e.status === 401) setBoards([])
      else setFehler(e instanceof AkteFehler && e.status === 403
        ? "Die Akte ist bisher nur für die Redaktion offen."
        : "Die Boards konnten nicht geladen werden.")
    })
  }, [])

  async function anlegen(e: React.FormEvent) {
    e.preventDefault()
    if (!titel.trim()) return
    setLaeuft(true)
    try {
      const b = await akte.boardAnlegen({ titel: titel.trim() })
      window.location.href = `/akte/${b.slug}`
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Anlegen fehlgeschlagen.")
      setLaeuft(false)
    }
  }

  return (
    <main className="mx-auto h-full max-w-4xl overflow-y-auto px-6 py-12">
      <header className="mb-10 flex items-end justify-between gap-4">
        <div>
          <p className="font-[family-name:var(--font-akte-mono)] text-xs uppercase tracking-[0.3em] text-[#8A94A0]">
            Ermittler-Wand
          </p>
          <h1 className="font-[family-name:var(--font-akte-titel)] text-6xl uppercase tracking-wide">
            Die Akte
          </h1>
        </div>
        <div className="flex items-center gap-2">
        {redaktion && (
        <a
          href={akte.exportUrl()}
          download
          className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md border border-[#222636] px-4 text-sm text-[#8A94A0] transition-colors duration-200 hover:border-[#f0c674] hover:text-[#f0c674]"
        >
          <Download className="h-4 w-4" aria-hidden /> Obsidian-Vault
        </a>
        )}
        <KontoKnopf />
        </div>
      </header>

      {fehler && <p role="alert" className="mb-6 rounded-md border border-[#FF1744]/50 bg-[#FF1744]/10 p-3 text-sm">{fehler}</p>}

      {redaktion && (
      <form onSubmit={anlegen} className="mb-8 flex gap-3">
        <label htmlFor="neues-board" className="sr-only">Titel des neuen Boards</label>
        <input
          id="neues-board"
          value={titel}
          onChange={(e) => setTitel(e.target.value)}
          placeholder="Neues Board, z. B. „Wer finanziert wen?“"
          className="min-h-11 flex-1 rounded-md border border-[#222636] bg-transparent px-4 outline-none focus:border-[#f0c674]"
        />
        <button
          type="submit"
          disabled={laeuft || !titel.trim()}
          className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md bg-[#FF1744] px-5 font-semibold text-white transition-opacity duration-200 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Plus className="h-4 w-4" aria-hidden /> Anlegen
        </button>
      </form>
      )}

      {boards === null && !fehler && <p className="text-[#8A94A0]">Lädt …</p>}
      {boards?.length === 0 && einrichtungOffen && <ErstesKontoHinweis />}
      {boards?.length === 0 && !einrichtungOffen && (
        <p className="text-[#8A94A0]">
          Hier ist noch nichts freigeschaltet.{" "}
          <Link href="/login?redirect=%2Fakte" className="underline">Anmelden</Link>
        </p>
      )}
      {!redaktion && !!boards?.length && (
        <p className="mb-6 text-sm text-[#8A94A0]">Nur lesen. Jede Verbindung trägt ihre Quelle, Meinungen stehen auf eigenen Zetteln. Die Recherche geht weiter.</p>
      )}
      {boards && <BoardBaum boards={boards} />}
      <Quelltext />
    </main>
  )
}

// AGPL-3.0 § 13: Wer die Akte im Netz betreibt, bietet allen Nutzern den Quelltext an.
function Quelltext() {
  const url = process.env.NEXT_PUBLIC_AKTE_QUELLTEXT_URL || "https://github.com/ThePyth0nKid/die-akte"
  return (
    <footer className="mt-12 text-xs text-[#8A94A0]">
      <a href={url} className="underline" rel="noopener noreferrer">Quelltext</a> · freie Software unter AGPL-3.0
    </footer>
  )
}

// Der Baum der Akte: Hauptwände oben, ihre Mappen eingerückt darunter (ein Board kann in mehreren liegen).
function BoardBaum({ boards }: { boards: Board[] }) {
  const slugs = new Set(boards.map((b) => b.slug))
  const kinder = new Map<string, Board[]>()
  for (const b of boards) for (const e of b.eltern ?? []) if (slugs.has(e)) kinder.set(e, [...(kinder.get(e) ?? []), b])
  const wurzeln = boards.filter((b) => !(b.eltern ?? []).some((e) => slugs.has(e)))
  // Jedes Board genau einmal (am ersten Weg); was in keinem Baum hängt (Kreis), kommt am Ende dazu.
  const gezeigt = new Set<string>()
  const zeile = (b: Board, tiefe: number, weg: string[]): React.ReactNode => { gezeigt.add(b.slug); return (
    <li key={`${weg.join("/")}/${b.slug}`}>
      <Link
        href={weg.length ? `/akte/${b.slug}?von=${weg.join(",")}` : `/akte/${b.slug}`}
        className="block cursor-pointer rounded-lg border border-[#222636] p-5 transition-colors duration-200 hover:border-[#FF1744]"
        style={{ marginLeft: tiefe * 28, background: tiefe ? "rgba(217,183,122,0.05)" : undefined }}
      >
        {tiefe > 0 && <span className="mb-1 block font-[family-name:var(--font-akte-mono)] text-[10px] uppercase tracking-[0.3em] text-[#d9b77a]">Mappe</span>}
        <span className="font-[family-name:var(--font-akte-titel)] text-2xl uppercase">{b.titel}</span>
        {b.beschreibung && <span className="mt-1 line-clamp-2 block text-sm text-[#8A94A0]">{b.beschreibung}</span>}
      </Link>
      {!!kinder.get(b.slug)?.length && tiefe < 6 && (
        <ul className="mt-3 space-y-3">
          {kinder.get(b.slug)!.filter((k) => !weg.includes(k.slug) && !gezeigt.has(k.slug)).map((k) => zeile(k, tiefe + 1, [...weg, b.slug]))}
        </ul>
      )}
    </li>
  ) }
  const baum = wurzeln.map((b) => zeile(b, 0, []))
  const uebrig = boards.filter((b) => !gezeigt.has(b.slug)).map((b) => zeile(b, 0, []))
  return <ul className="space-y-3">{baum}{uebrig}</ul>
}
