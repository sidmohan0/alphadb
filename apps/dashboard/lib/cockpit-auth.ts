const AWS_LIKE_ENVIRONMENTS = new Set(["aws", "prod", "production"])

type Env = Record<string, string | undefined>

export type CockpitAuthConfig = {
  enabled: boolean
  required: boolean
  pin: string | null
  cookieSecret: string | null
  cookieName: string
  cookieTtlSeconds: number
  cookieSecure: boolean
  error: string | null
}

const DEFAULT_COOKIE_NAME = "alphadb_cockpit_auth"
const DEFAULT_COOKIE_TTL_SECONDS = 60 * 60 * 24 * 7

function firstEnv(env: Env, ...keys: string[]) {
  for (const key of keys) {
    const value = env[key]
    if (value) return value
  }
  return null
}

function isTruthy(value: string | null) {
  return value === "1" || value?.toLowerCase() === "true"
}

function parsePositiveInteger(value: string | null, fallback: number) {
  if (!value) return fallback
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export function getCockpitAuthConfig(env: Env = process.env): CockpitAuthConfig {
  const environment = firstEnv(env, "ALPHADB_ENV") || "local"
  const required =
    AWS_LIKE_ENVIRONMENTS.has(environment.toLowerCase()) ||
    isTruthy(firstEnv(env, "ALPHADB_COCKPIT_AUTH_REQUIRED"))
  const pin = firstEnv(env, "ALPHADB_COCKPIT_PIN", "ALPHADB_DASHBOARD_PIN")
  const cookieSecret = firstEnv(
    env,
    "ALPHADB_COCKPIT_COOKIE_SECRET",
    "ALPHADB_DASHBOARD_COOKIE_SECRET",
  )
  const cookieName =
    firstEnv(env, "ALPHADB_COCKPIT_COOKIE_NAME", "ALPHADB_DASHBOARD_COOKIE_NAME") ||
    DEFAULT_COOKIE_NAME
  const cookieTtlSeconds = parsePositiveInteger(
    firstEnv(
      env,
      "ALPHADB_COCKPIT_COOKIE_TTL_SECONDS",
      "ALPHADB_DASHBOARD_COOKIE_TTL_SECONDS",
    ),
    DEFAULT_COOKIE_TTL_SECONDS,
  )
  const enabled = Boolean(pin)
  let error: string | null = null

  if ((required || enabled) && !(pin && /^\d{4}$/.test(pin))) {
    error = "ALPHADB_COCKPIT_PIN must be exactly four digits"
  } else if ((required || enabled) && !cookieSecret) {
    error = "ALPHADB_COCKPIT_COOKIE_SECRET is required when Cockpit auth is enabled"
  }

  return {
    enabled,
    required,
    pin,
    cookieSecret,
    cookieName,
    cookieTtlSeconds,
    cookieSecure: isTruthy(firstEnv(env, "ALPHADB_COCKPIT_COOKIE_SECURE")),
    error,
  }
}

export function authIsActive(config: CockpitAuthConfig) {
  return config.required || config.enabled
}

export function pinMatches(config: CockpitAuthConfig, submittedPin: string | null) {
  return Boolean(
    config.pin &&
      submittedPin &&
      /^\d{4}$/.test(submittedPin) &&
      constantTimeEqual(config.pin, submittedPin),
  )
}

export async function createCockpitAuthToken(
  config: CockpitAuthConfig,
  issuedAt = Math.floor(Date.now() / 1000),
) {
  if (!config.cookieSecret) {
    throw new Error("Cockpit cookie secret is not configured")
  }
  const payload = {
    exp: issuedAt + config.cookieTtlSeconds,
    iat: issuedAt,
    nonce: randomId(),
    v: 1,
  }
  const payloadBytes = new TextEncoder().encode(canonicalJson(payload))
  const encodedPayload = base64UrlEncode(payloadBytes)
  const encodedSignature = await sign(config.cookieSecret, payloadBytes)
  return `${encodedPayload}.${encodedSignature}`
}

export async function verifyCockpitAuthToken(
  config: CockpitAuthConfig,
  token: string | undefined,
  now = Math.floor(Date.now() / 1000),
) {
  if (!token || !config.cookieSecret) return false
  const [encodedPayload, encodedSignature, extra] = token.split(".")
  if (!encodedPayload || !encodedSignature || extra !== undefined) return false

  try {
    const payloadBytes = base64UrlDecode(encodedPayload)
    const expectedSignature = await sign(config.cookieSecret, payloadBytes)
    if (!constantTimeEqual(expectedSignature, encodedSignature)) return false

    const payload = JSON.parse(new TextDecoder().decode(payloadBytes)) as {
      exp?: unknown
      v?: unknown
    }
    return payload.v === 1 && typeof payload.exp === "number" && payload.exp >= now
  } catch {
    return false
  }
}

function canonicalJson(payload: Record<string, number | string>) {
  const entries = Object.entries(payload).sort(([left], [right]) => left.localeCompare(right))
  return `{${entries
    .map(([key, value]) => `${JSON.stringify(key)}:${JSON.stringify(value)}`)
    .join(",")}}`
}

async function sign(secret: string, payloadBytes: Uint8Array) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { hash: "SHA-256", name: "HMAC" },
    false,
    ["sign"],
  )
  const signature = await crypto.subtle.sign("HMAC", key, payloadBytes)
  return base64UrlEncode(new Uint8Array(signature))
}

function randomId() {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return base64UrlEncode(bytes)
}

function base64UrlEncode(bytes: Uint8Array) {
  let binary = ""
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "")
}

function base64UrlDecode(value: string) {
  const base64 = value.replaceAll("-", "+").replaceAll("_", "/")
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=")
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return bytes
}

function constantTimeEqual(left: string, right: string) {
  if (left.length !== right.length) return false
  let result = 0
  for (let index = 0; index < left.length; index += 1) {
    result |= left.charCodeAt(index) ^ right.charCodeAt(index)
  }
  return result === 0
}
