import { NextResponse } from "next/server"
import { cookies } from "next/headers"

export async function POST() {
  const cookieStore = await cookies()
  const domain = process.env.COOKIE_DOMAIN || undefined
  cookieStore.delete({ name: "access_token", domain, path: "/" })
  cookieStore.delete({ name: "refresh_token", domain, path: "/" })
  return NextResponse.json({ success: true })
}
