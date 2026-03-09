import { mapInvalidInput } from "../errors";
import { fetchKalshiHistory, fetchKalshiTrendingMarkets, searchKalshiMarkets } from "../providers/kalshi";
import { fetchPolymarketHistory, fetchPolymarketTrendingMarkets, searchPolymarketMarkets } from "../providers/polymarket";
import { MarketSummary, PricePoint, ProviderId, RangeKey } from "../types";
import { getOrLoadCached } from "./marketCache";
import { rankMarkets } from "./marketRanking";
import { getUserMarketState } from "./userStateStore";

const TRENDING_TTL_MS = 20_000;
const SEARCH_TTL_MS = 15_000;
const HISTORY_TTL_MS = 60_000;

export async function getTrendingMarkets(provider: ProviderId, limit: number): Promise<MarketSummary[]> {
  return getOrLoadCached(`trending:${provider}:${limit}`, TRENDING_TTL_MS, async () =>
    provider === "kalshi" ? fetchKalshiTrendingMarkets(limit) : fetchPolymarketTrendingMarkets(limit),
  );
}

export async function searchMarkets(provider: ProviderId, query: string, limit: number): Promise<MarketSummary[]> {
  return searchMarketsForUser(provider, query, limit);
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

export async function searchMarketsForUser(
  provider: ProviderId,
  query: string,
  limit: number,
  userId = "local-user",
): Promise<MarketSummary[]> {
  const trimmed = query.trim().toLowerCase();
  const [state, remoteMarkets] = await Promise.all([
    getUserMarketState(userId),
    getOrLoadCached(`search:${provider}:${Math.max(limit * 4, 32)}:${trimmed}`, SEARCH_TTL_MS, async () =>
      provider === "kalshi"
        ? searchKalshiMarkets(trimmed, Math.max(limit * 4, 32))
        : searchPolymarketMarkets(trimmed, Math.max(limit * 4, 32)),
    ),
  ]);

  return rankMarkets(trimmed, remoteMarkets, {
    limit,
    remoteIds: new Set(remoteMarkets.map((market) => market.id)),
    savedIds: new Set(state.savedMarkets.map((entry) => entry.market.id)),
    recentIds: new Set(state.recentMarkets.map((entry) => entry.market.id)),
  });
}

export async function getUnifiedSearchMarkets(
  query: string,
  limitPerProvider: number,
  userId = "local-user",
): Promise<Record<ProviderId, MarketSummary[]>> {
  const [polymarket, kalshi] = await Promise.all([
    searchMarketsForUser("polymarket", query, limitPerProvider, userId),
    searchMarketsForUser("kalshi", query, limitPerProvider, userId),
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
  searchMarketsForUser,
  getUnifiedSearchMarkets,
  getMarketHistory,
};
