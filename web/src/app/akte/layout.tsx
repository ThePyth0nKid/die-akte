import type { Metadata } from "next"
import { Anton, IBM_Plex_Mono, Inter } from "next/font/google"
import "@xyflow/react/dist/style.css"

const anton = Anton({ weight: "400", subsets: ["latin"], variable: "--font-akte-titel", display: "swap" })
const inter = Inter({ subsets: ["latin"], variable: "--font-akte-text", display: "swap" })
const plex = IBM_Plex_Mono({ weight: ["400", "600"], subsets: ["latin"], variable: "--font-akte-mono", display: "swap" })

export const metadata: Metadata = {
  title: process.env.AKTE_TITEL || "Die Akte",
  robots: { index: false, follow: false },
}

/**
 * Die Akte läuft ohne die App-Hülle (Navbar, Chat, Guide): die Wand braucht
 * den ganzen Bildschirm, und im Aufnahme-Modus darf nichts anderes zu sehen sein.
 * Die Anmeldung prüft die Middleware; die Rolle prüft das Backend.
 */
export default function AkteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      id="akte-wurzel"
      className={`${anton.variable} ${inter.variable} ${plex.variable} fixed inset-0 bg-[#0A0A0F] text-[#F2F7FB]`}
      style={{ fontFamily: "var(--font-akte-text), system-ui, sans-serif" }}
    >
      {children}
    </div>
  )
}
