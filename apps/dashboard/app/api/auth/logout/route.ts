import { NextRequest, NextResponse } from "next/server"

import { getCockpitAuthConfig } from "@/lib/cockpit-auth"

export function GET(request: NextRequest) {
  return clearCookie(request)
}

export function POST(request: NextRequest) {
  return clearCookie(request)
}

function clearCookie(request: NextRequest) {
  const config = getCockpitAuthConfig()
  const response = NextResponse.redirect(new URL("/login", request.url), 303)
  response.cookies.set({
    httpOnly: true,
    maxAge: 0,
    name: config.cookieName,
    path: "/",
    sameSite: "lax",
    secure: config.cookieSecure,
    value: "",
  })
  return response
}
