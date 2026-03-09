import { MarketSummary, PricePoint, ProviderId, RangeKey } from "../types.js";

const RAW_BACKEND_BASE_URL = process.env.ALPHADB_API_BASE_URL?.trim();
const BACKEND_BASE_URL = RAW_BACKEND_BASE_URL ? RAW_BACKEND_BASE_URL.replace(/\/+$/, "") : null;

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
      "User-Agent": "alphadb-markets-tui",
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
