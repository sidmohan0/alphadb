import { NextRequest, NextResponse } from "next/server"

import {
  authIsActive,
  createCockpitAuthToken,
  getCockpitAuthConfig,
  pinMatches,
} from "@/lib/cockpit-auth"

export async function POST(request: NextRequest) {
  const config = getCockpitAuthConfig()
  const formData = await request.formData()
  const pin = String(formData.get("pin") || "")
  const nextPath = normalizeNext(String(formData.get("next") || "/"))

  if (!authIsActive(config)) {
    return NextResponse.redirect(new URL(nextPath, request.url), 303)
  }

  if (config.error || !pinMatches(config, pin)) {
    const loginUrl = new URL("/login", request.url)
    loginUrl.searchParams.set("next", nextPath)
    loginUrl.searchParams.set("error", config.error ? "config" : "pin")
    return NextResponse.redirect(loginUrl, 303)
  }

  const response = NextResponse.redirect(new URL(nextPath, request.url), 303)
  response.cookies.set({
    httpOnly: true,
    maxAge: config.cookieTtlSeconds,
    name: config.cookieName,
    path: "/",
    sameSite: "lax",
    secure: config.cookieSecure,
    value: await createCockpitAuthToken(config),
  })
  return response
}

function normalizeNext(value: string) {
  if (!value.startsWith("/") || value.startsWith("//")) return "/"
  return value
}
