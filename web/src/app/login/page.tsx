"use client"

import { Suspense, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { sicheresZiel } from "@/lib/ziel"

function Formular() {
  const router = useRouter()
  const ziel = sicheresZiel(useSearchParams().get("redirect"))
  const [login, setLogin] = useState("")
  const [passwort, setPasswort] = useState("")
  const [fehler, setFehler] = useState("")
  const [laeuft, setLaeuft] = useState(false)

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
      setFehler("Anmeldung fehlgeschlagen.")
      return
    }
    router.replace(ziel)
  }

  return (
    <form onSubmit={anmelden} className="w-full max-w-sm space-y-4 rounded-lg border border-white/10 bg-white/5 p-6">
      <h1 className="text-2xl font-semibold tracking-wide">Die Akte</h1>
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
      {fehler && <p className="text-sm text-red-400">{fehler}</p>}
      <button disabled={laeuft}
        className="w-full rounded bg-[#f0c674] px-3 py-2 font-medium text-black disabled:opacity-50">
        {laeuft ? "…" : "Anmelden"}
      </button>
    </form>
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
