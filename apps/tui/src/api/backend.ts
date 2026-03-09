import { MarketSummary, PersistentState, PricePoint, ProviderId, RangeKey } from "../types.js";

const RAW_BACKEND_BASE_URL = process.env.ALPHADB_API_BASE_URL?.trim();
const BACKEND_BASE_URL = RAW_BACKEND_BASE_URL ? RAW_BACKEND_BASE_URL.replace(/\/+$/, "") : null;
const BACKEND_USER_ID = process.env.ALPHADB_USER_ID?.trim() || "local-user";

function backendHeaders(): Record<string, string> {
  return {
    Accept: "application/json",
    "User-Agent": "alphadb-markets-tui",
    "X-AlphaDB-User-Id": BACKEND_USER_ID,
  };
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      ...backendHeaders(),
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}`);
  }

  return response.json() as Promise<T>;
}

export function hasBackendMarketApi(): boolean {
  return Boolean(BACKEND_BASE_URL);
}

export function backendApiBaseUrl(): string | null {
  return BACKEND_BASE_URL;
}

export async function fetchBackendUnifiedTrendingMarkets(limit: number): Promise<Record<ProviderId, MarketSummary[]>> {
  const url = new URL(`${BACKEND_BASE_URL}/markets/unified/trending`);
  url.searchParams.set("limit", String(limit));
  const payload = await fetchJson<{ markets?: Partial<Record<ProviderId, MarketSummary[]>> }>(url.toString());
  return {
    polymarket: payload.markets?.polymarket ?? [],
    kalshi: payload.markets?.kalshi ?? [],
  };
}

export async function fetchBackendTrendingMarkets(provider: ProviderId, limit: number): Promise<MarketSummary[]> {
  const url = new URL(`${BACKEND_BASE_URL}/markets/trending`);
  url.searchParams.set("provider", provider);
  url.searchParams.set("limit", String(limit));
  const payload = await fetchJson<{ markets?: MarketSummary[] }>(url.toString());
  return payload.markets ?? [];
}

export async function fetchBackendSearchCandidates(
  provider: ProviderId,
  query: string,
  limit: number,
): Promise<MarketSummary[]> {
  const url = new URL(`${BACKEND_BASE_URL}/markets/search`);
  url.searchParams.set("provider", provider);
  url.searchParams.set("q", query);
  url.searchParams.set("limit", String(limit));
  const payload = await fetchJson<{ markets?: MarketSummary[] }>(url.toString());
  return payload.markets ?? [];
}

export async function fetchBackendUnifiedSearchMarkets(
  query: string,
  limit: number,
): Promise<Record<ProviderId, MarketSummary[]>> {
  const url = new URL(`${BACKEND_BASE_URL}/markets/unified/search`);
  url.searchParams.set("q", query);
  url.searchParams.set("limit", String(limit));
  const payload = await fetchJson<{ markets?: Partial<Record<ProviderId, MarketSummary[]>> }>(url.toString());
  return {
    polymarket: payload.markets?.polymarket ?? [],
    kalshi: payload.markets?.kalshi ?? [],
  };
}

export async function fetchBackendMarketHistory(
  market: MarketSummary,
  range: RangeKey,
): Promise<PricePoint[]> {
  const url = new URL(`${BACKEND_BASE_URL}/markets/history`);
  url.searchParams.set("provider", market.provider);
  url.searchParams.set("marketId", market.id);
  url.searchParams.set("range", range);
  const firstOutcomeTokenId = market.outcomes[0]?.tokenId;
  if (firstOutcomeTokenId) {
    url.searchParams.set("outcomeTokenId", firstOutcomeTokenId);
  }

  const payload = await fetchJson<{ points?: PricePoint[] }>(url.toString());
  return payload.points ?? [];
}

export async function fetchBackendPersistentState(): Promise<PersistentState> {
  const payload = await fetchJson<{ state?: PersistentState }>(`${BACKEND_BASE_URL}/markets/state`);
  return payload.state ?? { savedMarkets: [], recentMarkets: [] };
}

export async function saveBackendMarket(market: MarketSummary): Promise<PersistentState> {
  const payload = await fetchJson<{ state?: PersistentState }>(`${BACKEND_BASE_URL}/markets/state/saved`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ market }),
  });
  return payload.state ?? { savedMarkets: [], recentMarkets: [] };
}

export async function removeBackendSavedMarket(marketId: string): Promise<PersistentState> {
  const url = new URL(`${BACKEND_BASE_URL}/markets/state/saved`);
  url.searchParams.set("marketId", marketId);
  const payload = await fetchJson<{ state?: PersistentState }>(url.toString(), {
    method: "DELETE",
  });
  return payload.state ?? { savedMarkets: [], recentMarkets: [] };
}

export async function touchBackendRecentMarket(market: MarketSummary): Promise<PersistentState> {
  const payload = await fetchJson<{ state?: PersistentState }>(`${BACKEND_BASE_URL}/markets/state/recent`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ market }),
  });
  return payload.state ?? { savedMarkets: [], recentMarkets: [] };
}
