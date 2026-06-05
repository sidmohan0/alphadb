import { NextRequest } from "next/server"

const DEFAULT_API_BASE = "http://127.0.0.1:8501"

type RouteContext = {
  params: Promise<{ path?: string[] }>
}

export async function GET(request: NextRequest, context: RouteContext) {
  return proxy(request, context)
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxy(request, context)
}

async function proxy(request: NextRequest, context: RouteContext) {
  const { path = [] } = await context.params
  const baseUrl =
    process.env.ALPHADB_API_BASE_URL ||
    process.env.NEXT_PUBLIC_ALPHADB_API_BASE_URL ||
    DEFAULT_API_BASE
  const upstream = new URL(`/api/${path.join("/")}`, baseUrl)
  request.nextUrl.searchParams.forEach((value, key) => {
    upstream.searchParams.append(key, value)
  })

  const headers = new Headers()
  const contentType = request.headers.get("Content-Type")
  if (contentType) {
    headers.set("Content-Type", contentType)
  }

  const response = await fetch(upstream, {
    method: request.method,
    headers,
    body: request.method === "GET" ? undefined : await request.text(),
    cache: "no-store",
  })

  return new Response(await response.text(), {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("Content-Type") || "application/json",
    },
  })
}
