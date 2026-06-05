import { NextRequest, NextResponse } from "next/server"

import {
  authIsActive,
  getCockpitAuthConfig,
  verifyCockpitAuthToken,
} from "@/lib/cockpit-auth"

const PUBLIC_FILE = /\.(?:avif|gif|ico|jpg|jpeg|png|svg|txt|webmanifest)$/i

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl
  if (isPublicPath(pathname)) {
    return NextResponse.next()
  }

  const config = getCockpitAuthConfig()
  if (!authIsActive(config)) {
    return NextResponse.next()
  }

  if (config.error) {
    return authFailure(pathname, config.error, 500)
  }

  const authenticated = await verifyCockpitAuthToken(
    config,
    request.cookies.get(config.cookieName)?.value,
  )
  if (authenticated) {
    return NextResponse.next()
  }

  if (pathname.startsWith("/api/alphadb")) {
    return authFailure(pathname, "Cockpit authentication required", 401)
  }

  const loginUrl = new URL("/login", request.url)
  loginUrl.searchParams.set("next", `${pathname}${search}`)
  return NextResponse.redirect(loginUrl)
}

function isPublicPath(pathname: string) {
  return (
    pathname === "/healthz" ||
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/api/auth/") ||
    pathname.startsWith("/_next/") ||
    PUBLIC_FILE.test(pathname)
  )
}

function authFailure(pathname: string, message: string, status: number) {
  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      {
        error: {
          code: status === 401 ? "unauthorized" : "cockpit_auth_config_invalid",
          message,
        },
        ok: false,
      },
      { status },
    )
  }

  return new NextResponse(message, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
    status,
  })
}
