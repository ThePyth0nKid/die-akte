"use client"

// „Anmelden“ oder „Abmelden“, je nach Sitzung. Ohne ihn fänden Leser der öffentlichen Wand keinen Weg zur Werkstatt.

import { useEffect, useState } from "react"
import { LogIn, LogOut } from "lucide-react"

const knopf =
  "flex min-h-10 cursor-pointer items-center gap-2 rounded-md px-3 text-sm text-[#F2F7FB] transition-colors duration-200 hover:bg-white/10"

export default function KontoKnopf() {
  const [angemeldet, setAngemeldet] = useState<boolean | null>(null)

  useEffect(() => {
    fetch("/api/auth/sitzung", { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then((d: { angemeldet?: boolean }) => setAngemeldet(Boolean(d.angemeldet)))
      .catch(() => setAngemeldet(false))
  }, [])

  if (angemeldet === null) return null
  if (!angemeldet) {
    const hier = typeof window === "undefined" ? "/akte" : window.location.pathname + window.location.search
    return (
      <a href={`/login?redirect=${encodeURIComponent(hier)}`} className={knopf} title="Als Redaktion anmelden">
        <LogIn className="h-4 w-4" aria-hidden /> Anmelden
      </a>
    )
  }
  return (
    <button
      type="button"
      className={knopf}
      title="Abmelden"
      onClick={async () => {
        await fetch("/api/auth/logout", { method: "POST", credentials: "include" }).catch(() => null)
        window.location.href = "/akte"
      }}
    >
      <LogOut className="h-4 w-4" aria-hidden /> Abmelden
    </button>
  )
}
