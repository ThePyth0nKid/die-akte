/** Kommt eine ändernde Anfrage an die Routen der Oberfläche aus der Oberfläche selbst?
 *
 * Die Cookies sind SameSite=Lax und schon damit vor fremden Seiten geschützt. Das hier ist die zweite Tür: Ein
 * Browser sagt mit Sec-Fetch-Site bzw. Origin, woher die Anfrage stammt. Lesen (GET/HEAD) bleibt immer erlaubt;
 * Anfragen ohne beide Köpfe kommen nicht aus einem Browser-Tab (curl, Server) und tragen dann auch keine fremden
 * Cookies.
 */
export function gleicheHerkunft(methode: string, kopf: (name: string) => string | null): boolean {
  if (methode === "GET" || methode === "HEAD" || methode === "OPTIONS") return true
  const seite = kopf("sec-fetch-site")
  if (seite) return seite === "same-origin" || seite === "none"
  const origin = kopf("origin")
  if (!origin) return true
  const host = kopf("x-forwarded-host") ?? kopf("host")
  try {
    return new URL(origin).host === host
  } catch {
    return false
  }
}
