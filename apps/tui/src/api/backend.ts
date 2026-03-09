import { AlphaDBClient } from "@alphadb/sdk";

import { MarketSummary, PersistentState, PricePoint, ProviderId, RangeKey } from "../types.js";

export const backendClient = new AlphaDBClient({
  baseUrl: process.env.ALPHADB_API_BASE_URL,
  userAgent: "alphadb-markets-tui",
  userId: process.env.ALPHADB_USER_ID?.trim() || "local-user",
});

export function hasBackendMarketApi(): boolean {
  return backendClient.hasBaseUrl();
}

export function backendApiBaseUrl(): string | null {
  return backendClient.baseUrl();
}

export async function fetchBackendUnifiedTrendingMarkets(limit: number): Promise<Record<ProviderId, MarketSummary[]>> {
  return backendClient.fetchUnifiedTrendingMarkets(limit);
}

export async function fetchBackendTrendingMarkets(provider: ProviderId, limit: number): Promise<MarketSummary[]> {
  return backendClient.fetchTrendingMarkets(provider, limit);
}

export async function fetchBackendSearchCandidates(
  provider: ProviderId,
  query: string,
  limit: number,
): Promise<MarketSummary[]> {
  return backendClient.fetchSearchMarkets(provider, query, limit);
}

export async function fetchBackendUnifiedSearchMarkets(
  query: string,
  limit: number,
): Promise<Record<ProviderId, MarketSummary[]>> {
  return backendClient.fetchUnifiedSearchMarkets(query, limit);
}

export async function fetchBackendMarketHistory(
  market: MarketSummary,
  range: RangeKey,
): Promise<PricePoint[]> {
  return backendClient.fetchMarketHistory(market, range);
}

export async function fetchBackendPersistentState(): Promise<PersistentState> {
  return backendClient.fetchPersistentState();
}

export async function saveBackendMarket(market: MarketSummary): Promise<PersistentState> {
  return backendClient.saveMarket(market);
}

export async function removeBackendSavedMarket(marketId: string): Promise<PersistentState> {
  return backendClient.removeSavedMarket(marketId);
}

export async function touchBackendRecentMarket(market: MarketSummary): Promise<PersistentState> {
  return backendClient.touchRecentMarket(market);
}
