import { buildCandles, fetchMarketHistory, fetchTrendingMarkets, searchMarkets } from "./polymarket.js";
import {
  applyKalshiTickerUpdate,
  buildKalshiCandles,
  fetchKalshiMarketHistory,
  fetchKalshiTrendingMarkets,
  searchKalshiMarkets,
} from "./kalshi.js";
import { Candle, MarketSummary, PricePoint, ProviderId, RangeKey } from "../types.js";

interface SearchOptions {
  localCandidates?: MarketSummary[];
  savedIds?: Set<string>;
  recentIds?: Set<string>;
}

export async function fetchTrendingMarketsForProvider(
  provider: ProviderId,
  limit: number,
): Promise<MarketSummary[]> {
  return provider === "kalshi"
    ? fetchKalshiTrendingMarkets(limit)
    : fetchTrendingMarkets(limit);
}

export async function searchMarketsForProvider(
  provider: ProviderId,
  query: string,
  limit: number,
  options: SearchOptions,
): Promise<MarketSummary[]> {
  return provider === "kalshi"
    ? searchKalshiMarkets(query, limit, options)
    : searchMarkets(query, limit, options);
}

export async function fetchHistoryForMarket(
  market: MarketSummary,
  range: RangeKey,
): Promise<PricePoint[]> {
  return market.provider === "kalshi"
    ? fetchKalshiMarketHistory(market, range)
    : fetchMarketHistory(market.outcomes[0]?.tokenId ?? "", range);
}

export function buildCandlesForMarket(
  market: MarketSummary,
  points: PricePoint[],
  targetCount: number,
): Candle[] {
  return market.provider === "kalshi"
    ? buildKalshiCandles(points, targetCount)
    : buildCandles(points, targetCount);
}

export function applyProviderTickerUpdate(market: MarketSummary, payload: Record<string, unknown>): MarketSummary {
  return market.provider === "kalshi" ? applyKalshiTickerUpdate(market, payload) : market;
}
