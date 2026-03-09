import { mapInvalidInput } from "../errors";
import { fetchKalshiHistory, fetchKalshiTrendingMarkets, searchKalshiMarkets } from "../providers/kalshi";
import { fetchPolymarketHistory, fetchPolymarketTrendingMarkets, searchPolymarketMarkets } from "../providers/polymarket";
import { MarketSummary, PricePoint, ProviderId, RangeKey } from "../types";

export async function getTrendingMarkets(provider: ProviderId, limit: number): Promise<MarketSummary[]> {
  return provider === "kalshi" ? fetchKalshiTrendingMarkets(limit) : fetchPolymarketTrendingMarkets(limit);
}

export async function searchMarkets(provider: ProviderId, query: string, limit: number): Promise<MarketSummary[]> {
  return provider === "kalshi" ? searchKalshiMarkets(query, limit) : searchPolymarketMarkets(query, limit);
}

export async function getMarketHistory(
  provider: ProviderId,
  marketId: string,
  outcomeTokenId: string | undefined,
  range: RangeKey,
): Promise<PricePoint[]> {
  if (provider === "kalshi") {
    return fetchKalshiHistory(marketId, outcomeTokenId, range);
  }

  if (!outcomeTokenId) {
    throw mapInvalidInput("outcomeTokenId is required for polymarket history", "outcomeTokenId");
  }

  return fetchPolymarketHistory(outcomeTokenId, range);
}

export const marketDataService = {
  getTrendingMarkets,
  searchMarkets,
  getMarketHistory,
};
