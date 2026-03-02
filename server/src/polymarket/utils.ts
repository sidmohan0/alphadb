import { MarketToken, JsonObject } from "./types";

/**
 * Type guard: checks if a value is a meaningful, non-empty string.
 */
export function isString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/**
 * Type guard: validates a value as a plausible Polymarket token/asset id.
 */
export function isAssetIdCandidate(value: unknown): value is string {
  if (!isString(value)) return false;

  const normalized = value.trim();
  if (normalized.startsWith("0x") && normalized.length === 66) return true;
  return /^\d{8,}$/.test(normalized);
}

/**
 * Normalizes unknown values into trimmed strings when available.
 */
export function toStringOrUndefined(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;

  const str = String(value).trim();
  return str.length ? str : undefined;
}

/**
 * Split an array into fixed-size chunks.
 */
export function chunk<T>(items: T[], size: number): T[][] {
  if (size <= 0) return [items];

  const output: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    output.push(items.slice(i, i + size));
  }

  return output;
}

/**
 * Safely parse a positive integer-like environment variable with fallback.
 */
export function parseNumber(value: string | undefined, fallback: number): number {
  if (!value) return fallback;

  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/**
 * Convert websocket payload data into string form when possible.
 */
export function parseMessageData(raw: unknown): string | undefined {
  if (typeof raw === "string") return raw;

  if (raw instanceof ArrayBuffer) {
    return Buffer.from(raw).toString("utf8");
  }

  if (ArrayBuffer.isView(raw)) {
    return Buffer.from(raw.buffer, raw.byteOffset, raw.byteLength).toString("utf8");
  }

  if (raw instanceof Blob) {
    return undefined;
  }

  return undefined;
}

/**
 * Recursively traverse any payload and collect asset-like keys.
 */
export function extractAssetIdsFromWsPayload(payload: unknown, seen: Set<string>): void {
  /**
   * DFS-style nested traversal.
   */
  const walk = (value: unknown) => {
    if (!value || typeof value !== "object") return;

    if (Array.isArray(value)) {
      for (const item of value) walk(item);
      return;
    }

    const obj = value as JsonObject;
    for (const [key, valueForKey] of Object.entries(obj)) {
      const isAssetKey = ["asset_id", "assetId", "token_id", "tokenId"].includes(key);

      if (isAssetKey && isAssetIdCandidate(valueForKey)) {
        seen.add(String(valueForKey).trim());
      }

      if (Array.isArray(valueForKey) || (valueForKey && typeof valueForKey === "object")) {
        walk(valueForKey);
      }
    }
  };

  walk(payload);
}

/**
 * Parse one token object into one or more canonicalized channels.
 */
export function collectTokenChannel(token: unknown, conditionId?: string, question?: string): {
  assetId: string;
  conditionId?: string;
  question?: string;
  outcome?: string;
}[] {
  if (!token || typeof token !== "object") return [];

  const raw = token as MarketToken;
  const values = [raw.token_id, raw.tokenId, raw.asset_id, raw.assetId] as const;
  const out: {
    assetId: string;
    conditionId?: string;
    question?: string;
    outcome?: string;
  }[] = [];

  for (const candidate of values) {
    if (!isAssetIdCandidate(candidate)) continue;

    const channel = {
      assetId: String(candidate).trim(),
      ...(conditionId ? { conditionId } : {}),
      ...(question ? { question } : {}),
      ...(isString(raw.outcome) ? { outcome: raw.outcome } : {}),
    };

    out.push(channel);
  }

  return out;
}

/**
 * Normalize ws input into one of the accepted websocket endpoint forms.
 */
export function normalizeWsUrl(input: string): string {
  const base = input.endsWith("/") ? input.slice(0, -1) : input;

  if (/\/ws\/(market|user)$/.test(base)) return base;
  if (base.endsWith("/ws")) return `${base}/market`;
  return `${base}/ws/market`;
}
