/**
 * Shared cookie configuration for all BFF auth routes.
 *
 * In Docker, NODE_ENV=production is set for the Next.js standalone build,
 * but locally we run over HTTP (no TLS). The Secure flag must be off
 * for cookies to persist in the browser over plain HTTP.
 *
 * Set COOKIE_SECURE=false in docker-compose.yml for local dev.
 * Behind HTTPS, COOKIE_SECURE defaults to true when NODE_ENV=production.
 */

const isSecure =
  process.env.COOKIE_SECURE !== undefined
    ? process.env.COOKIE_SECURE === "true"
    : process.env.NODE_ENV === "production"

const cookieDomain = process.env.COOKIE_DOMAIN || undefined

export function accessTokenCookie(value: string) {
  return {
    name: "access_token" as const,
    value,
    httpOnly: true,
    secure: isSecure,
    sameSite: "lax" as const,
    domain: cookieDomain,
    path: "/",
    maxAge: 60 * 60,
  }
}

export function refreshTokenCookie(value: string) {
  return {
    name: "refresh_token" as const,
    value,
    httpOnly: true,
    secure: isSecure,
    sameSite: "lax" as const,
    domain: cookieDomain,
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  }
}
