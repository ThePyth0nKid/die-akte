import type { NextConfig } from "next"

// Mit Docker leitet Caddy /api/v1, /admin und /static an das Backend weiter (gleiche Herkunft).
// Ohne Docker (AKTE_OHNE_PROXY=1 npm run dev) übernehmen das diese Umleitungen.
const DJANGO_API_URL = process.env.DJANGO_API_URL || "http://127.0.0.1:8000"

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    if (process.env.AKTE_OHNE_PROXY !== "1") return []
    return [
      { source: "/api/v1/:pfad*", destination: `${DJANGO_API_URL}/api/v1/:pfad*` },
      { source: "/admin/:pfad*", destination: `${DJANGO_API_URL}/admin/:pfad*` },
      { source: "/static/:pfad*", destination: `${DJANGO_API_URL}/static/:pfad*` },
    ]
  },
}

export default nextConfig
