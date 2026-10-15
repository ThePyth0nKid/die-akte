"use client"

import { Suspense, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import ErstesKontoHinweis, { useEinrichtungOffen } from "@/components/akte/ErstesKonto"
import { sicheresZiel } from "@/lib/ziel"

function Formular() {
  const router = useRouter()
  const suche = useSearchParams()
  const ziel = sicheresZiel(suche.get("redirect"))
  const neu = suche.get("neu") === "1"
  const [login, setLogin] = useState("")
  const [passwort, setPasswort] = useState("")
  const [fehler, setFehler] = useState("")
  const [laeuft, setLaeuft] = useState(false)
  const einrichtungOffen = useEinrichtungOffen()

  async function anmelden(e: React.FormEvent) {
    e.preventDefault()
    setLaeuft(true)
    setFehler("")
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login, password: passwort }),
    })
    setLaeuft(false)
    if (!res.ok) {
      setFehler(res.status === 429 ? "Zu viele Versuche. Bitte in einer Minute erneut." : "Anmeldung fehlgeschlagen.")
      return
    }
    router.replace(ziel)
  }

  return (
    <div className="w-full max-w-md space-y-6">
      {/* Die Akte hat noch kein Konto: Der Weg dorthin steht über allem, nicht versteckt hinter einem Fehlschlag. */}
      {einrichtungOffen && <ErstesKontoHinweis />}
      <form onSubmit={anmelden} className="w-full space-y-4 rounded-lg border border-white/10 bg-white/5 p-6">
        <h1 className="text-2xl font-semibold tracking-wide">Ultra-Akte</h1>
        {neu && (
          <p role="status" className="rounded border border-[#f0c674]/40 bg-[#f0c674]/10 p-3 text-sm">
            Dein Konto ist angelegt. Melde dich jetzt damit an.
          </p>
        )}
        <label className="block text-sm">
          Benutzername oder E-Mail
          <input value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username" required
            className="mt-1 w-full rounded border border-white/20 bg-black/40 px-3 py-2" />
        </label>
        <label className="block text-sm">
          Passwort
          <input type="password" value={passwort} onChange={(e) => setPasswort(e.target.value)}
            autoComplete="current-password" required
            className="mt-1 w-full rounded border border-white/20 bg-black/40 px-3 py-2" />
        </label>
        {fehler && <p role="alert" className="text-sm text-red-400">{fehler}</p>}
        <button disabled={laeuft}
          className="w-full rounded bg-[#f0c674] px-3 py-2 font-medium text-black disabled:opacity-50">
          {laeuft ? "…" : "Anmelden"}
        </button>
      </form>
    </div>
  )
}

export default function LoginSeite() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <Suspense>
        <Formular />
      </Suspense>
    </main>
  )
}
