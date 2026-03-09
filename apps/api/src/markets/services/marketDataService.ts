import { mapInvalidInput } from "../errors";
import { fetchKalshiHistory, fetchKalshiTrendingMarkets, searchKalshiMarkets } from "../providers/kalshi";
import { fetchPolymarketHistory, fetchPolymarketTrendingMarkets, searchPolymarketMarkets } from "../providers/polymarket";
import { MarketSummary, PricePoint, ProviderId, RangeKey } from "../types";
import { getOrLoadCached } from "./marketCache";

const TRENDING_TTL_MS = 20_000;
const SEARCH_TTL_MS = 15_000;
const HISTORY_TTL_MS = 60_000;

export async function getTrendingMarkets(provider: ProviderId, limit: number): Promise<MarketSummary[]> {
  return getOrLoadCached(`trending:${provider}:${limit}`, TRENDING_TTL_MS, async () =>
    provider === "kalshi" ? fetchKalshiTrendingMarkets(limit) : fetchPolymarketTrendingMarkets(limit),
  );
}

export async function searchMarkets(provider: ProviderId, query: string, limit: number): Promise<MarketSummary[]> {
  const trimmed = query.trim().toLowerCase();
  return getOrLoadCached(`search:${provider}:${limit}:${trimmed}`, SEARCH_TTL_MS, async () =>
    provider === "kalshi" ? searchKalshiMarkets(trimmed, limit) : searchPolymarketMarkets(trimmed, limit),
  );
}

export async function getUnifiedTrendingMarkets(
  limitPerProvider: number,
): Promise<Record<ProviderId, MarketSummary[]>> {
  const [polymarket, kalshi] = await Promise.all([
    getTrendingMarkets("polymarket", limitPerProvider),
    getTrendingMarkets("kalshi", limitPerProvider),
  ]);

  return {
    polymarket,
    kalshi,
  };
}

export async function getMarketHistory(
  provider: ProviderId,
  marketId: string,
  outcomeTokenId: string | undefined,
  range: RangeKey,
): Promise<PricePoint[]> {
  if (provider === "kalshi") {
    return getOrLoadCached(`history:${provider}:${marketId}:${outcomeTokenId ?? ""}:${range}`, HISTORY_TTL_MS, () =>
      fetchKalshiHistory(marketId, outcomeTokenId, range),
    );
  }

  if (!outcomeTokenId) {
    throw mapInvalidInput("outcomeTokenId is required for polymarket history", "outcomeTokenId");
  }

  return getOrLoadCached(`history:${provider}:${marketId}:${outcomeTokenId}:${range}`, HISTORY_TTL_MS, () =>
    fetchPolymarketHistory(outcomeTokenId, range),
  );
}

export const marketDataService = {
  getTrendingMarkets,
  getUnifiedTrendingMarkets,
  searchMarkets,
  getMarketHistory,
};
