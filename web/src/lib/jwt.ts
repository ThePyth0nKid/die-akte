/** Läuft dieses Access-Token noch? Liest nur das Ablaufdatum (``exp``), prüft keine Signatur: Es geht allein um die
 * Frage, ob die Oberfläche jemanden für angemeldet halten soll. Ob das Token gilt, entscheidet immer das Backend. */
export function laeuftNoch(token: string | undefined, jetzt = Date.now()): boolean {
  const teil = token?.split(".")[1]
  if (!teil) return false
  try {
    const json = atob(teil.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((teil.length + 3) % 4))
    const exp = (JSON.parse(json) as { exp?: unknown }).exp
    return typeof exp === "number" && exp * 1000 > jetzt
  } catch {
    return false
  }
}
