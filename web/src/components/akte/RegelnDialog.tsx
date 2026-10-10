"use client"

// Prüfregeln dieses Boards und die eigenen Schlüssel. Die Prüfung berät, der Mensch entscheidet: Jede Regel ist
// einzeln einstellbar (aus, Hinweis, sperrt). Ob ein Faden freigegeben und seitdem unverändert ist, sperrt immer.

import { useEffect, useState } from "react"
import { KeyRound, X } from "lucide-react"
import { akte, AkteFehler } from "@/lib/akte/api"
import { eigeneSchluessel, hierGespeichert, widerrufen, type EigenerSchluessel } from "@/lib/akte/unterschrift"
import type { Regel, Stufe } from "@/lib/akte/typen"

const STUFEN: { wert: Stufe; name: string }[] = [
  { wert: "aus", name: "aus" },
  { wert: "hinweis", name: "Hinweis" },
  { wert: "sperrt", name: "sperrt" },
]

type Schluessel = EigenerSchluessel & { hier: boolean }

export default function RegelnDialog({ slug, schliessen, geaendert }: {
  slug: string
  schliessen: () => void
  geaendert: () => void
}) {
  const [regeln, setRegeln] = useState<Regel[] | null>(null)
  const [wahl, setWahl] = useState<Record<string, Stufe>>({})
  const [schluessel, setSchluessel] = useState<Schluessel[]>([])
  const [meldung, setMeldung] = useState("")
  const [laeuft, setLaeuft] = useState(false)

  async function schluesselLaden() {
    const liste = await eigeneSchluessel()
    setSchluessel(await Promise.all(liste.map(async (s) => ({ ...s, hier: await hierGespeichert(s.kid) }))))
  }

  useEffect(() => {
    akte.pruefung(slug)
      .then((p) => { setRegeln(p.regeln); setWahl(Object.fromEntries(p.regeln.map((r) => [r.code, r.stufe]))) })
      .catch((e) => setMeldung(e instanceof Error ? e.message : "Regeln nicht lesbar."))
    schluesselLaden().catch(() => setSchluessel([]))
  }, [slug])

  useEffect(() => {
    const taste = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); schliessen() } }
    window.addEventListener("keydown", taste, true)
    return () => window.removeEventListener("keydown", taste, true)
  }, [schliessen])

  async function speichern(neu: Record<string, Stufe>) {
    setLaeuft(true)
    setMeldung("")
    try {
      await akte.boardAendern(slug, { regeln: neu })
      const p = await akte.pruefung(slug)
      setRegeln(p.regeln)
      setWahl(Object.fromEntries(p.regeln.map((r) => [r.code, r.stufe])))
      setMeldung("Gespeichert. Die Prüfung dieses Boards gilt ab sofort mit diesen Stufen.")
      geaendert()
    } catch (e) {
      setMeldung(e instanceof AkteFehler || e instanceof Error ? e.message : "Speichern fehlgeschlagen.")
    } finally {
      setLaeuft(false)
    }
  }

  async function widerruf(s: Schluessel) {
    const text = `Schlüssel ${s.fingerabdruck} widerrufen?\n\nAlles, was er später unterschreibt, ist ungültig. ` +
      "Frühere Unterschriften bleiben gültig. Der Widerruf steht unterschrieben in der Kette."
    if (!window.confirm(text)) return
    setLaeuft(true)
    try {
      await widerrufen(s.kid)
      await schluesselLaden()
      setMeldung("Widerrufen.")
    } catch (e) {
      setMeldung(e instanceof Error ? e.message : "Widerruf fehlgeschlagen.")
    } finally {
      setLaeuft(false)
    }
  }

  const geaendertGegenStand = regeln?.some((r) => wahl[r.code] !== r.stufe) ?? false

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[8vh]"
      onMouseDown={schliessen}>
      <div role="dialog" aria-label="Prüfregeln und Schlüssel" onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-2xl rounded-lg border border-[#222636] bg-[#0d0e14] p-5 text-[#F2F7FB] shadow-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Prüfregeln dieses Boards</h2>
          <button type="button" onClick={schliessen} aria-label="Schließen" className="rounded p-2 hover:bg-white/10">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-4 text-sm text-[#8A94A0]">
          Die Prüfung berät, du entscheidest. <b>Hinweis</b> zeigt einen Befund, hält aber nichts auf. <b>sperrt</b> hält
          einen Faden aus der Lese-Ansicht, bis du ihn bei der Freigabe mit Begründung überstimmst. Freigegeben und seit
          der Unterschrift unverändert muss ein Faden immer sein.
        </p>
        {!regeln && !meldung && <p className="text-sm text-[#8A94A0]">Lade …</p>}
        {regeln && (
          <table className="mb-4 w-full text-sm">
            <tbody>
              {regeln.map((r) => (
                <tr key={r.code} className="border-t border-[#222636]">
                  <td className="py-2 pr-3">
                    {r.text}
                    {wahl[r.code] !== r.standard && (
                      <span className="ml-2 text-xs text-[#8A94A0]">(Standard: {r.standard})</span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    <select aria-label={r.text} value={wahl[r.code] ?? r.stufe} disabled={laeuft}
                      onChange={(e) => setWahl((w) => ({ ...w, [r.code]: e.target.value as Stufe }))}
                      className="min-h-9 rounded border border-[#222636] bg-[#0A0A0F] px-2">
                      {STUFEN.map((s) => <option key={s.wert} value={s.wert}>{s.name}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {regeln && (
          <div className="mb-6 flex flex-wrap gap-2">
            <button type="button" disabled={laeuft || !geaendertGegenStand} onClick={() => speichern(wahl)}
              className="min-h-10 rounded-md bg-[#f0c674] px-4 text-sm font-semibold text-[#0A0A0F] disabled:opacity-40">
              Speichern
            </button>
            <button type="button" disabled={laeuft} onClick={() => speichern({})}
              className="min-h-10 rounded-md px-4 text-sm text-[#8A94A0] hover:bg-white/10">
              Auf Standard zurücksetzen
            </button>
          </div>
        )}

        <h3 className="mb-2 flex items-center gap-2 font-semibold"><KeyRound className="h-4 w-4" /> Deine Schlüssel</h3>
        <p className="mb-2 text-sm text-[#8A94A0]">
          Mit ihnen unterschreibst du Freigaben. Der private Teil liegt nur im Browser, in dem er entstanden ist. Ein
          verlorenes Gerät: Schlüssel hier widerrufen.
        </p>
        {schluessel.length === 0 && <p className="text-sm text-[#8A94A0]">Noch keiner; die erste Freigabe legt ihn an.</p>}
        <ul className="space-y-1 text-sm">
          {schluessel.map((s) => (
            <li key={s.kid} className="flex items-center justify-between gap-3 border-t border-[#222636] py-2">
              <span className="font-[family-name:var(--font-akte-mono)]">
                {s.fingerabdruck}
                {s.hier && <span className="ml-2 text-xs text-[#f0c674]">in diesem Browser</span>}
                {s.widerrufen_am && <span className="ml-2 text-xs text-[#FF1744]">widerrufen</span>}
              </span>
              {!s.widerrufen_am && (
                <button type="button" disabled={laeuft} onClick={() => widerruf(s)}
                  className="min-h-9 rounded-md px-3 text-xs text-[#FF1744] hover:bg-[#FF1744]/10">
                  Widerrufen
                </button>
              )}
            </li>
          ))}
        </ul>
        {meldung && <p role="status" className="mt-4 text-sm text-[#f0c674]">{meldung}</p>}
      </div>
    </div>
  )
}
