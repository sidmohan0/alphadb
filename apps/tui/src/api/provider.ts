import {
  fetchBackendMarketHistory,
  fetchBackendSearchCandidates,
  fetchBackendTrendingMarkets,
  fetchBackendUnifiedTrendingMarkets,
  hasBackendMarketApi,
} from "./backend.js";
import { buildCandles, fetchMarketHistory, fetchTrendingMarkets, searchMarkets } from "./polymarket.js";
import {
  applyKalshiTickerUpdate,
  buildKalshiCandles,
  fetchKalshiMarketHistory,
  fetchKalshiTrendingMarkets,
  searchKalshiMarkets,
} from "./kalshi.js";
import { rankMarkets } from "../lib/fuzzy.js";
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
  if (hasBackendMarketApi()) {
    try {
      return await fetchBackendTrendingMarkets(provider, limit);
    } catch {
      // Fall back to direct-provider mode if the backend is unavailable.
    }
  }

  return provider === "kalshi"
    ? fetchKalshiTrendingMarkets(limit)
    : fetchTrendingMarkets(limit);
}

export async function fetchUnifiedTrendingMarkets(
  limitPerProvider: number,
): Promise<Record<ProviderId, MarketSummary[]>> {
  if (hasBackendMarketApi()) {
    try {
      return await fetchBackendUnifiedTrendingMarkets(limitPerProvider);
    } catch {
      // Fall back to direct-provider mode if the backend is unavailable.
    }
  }

  const [polymarket, kalshi] = await Promise.all([
    fetchTrendingMarketsForProvider("polymarket", limitPerProvider),
    fetchTrendingMarketsForProvider("kalshi", limitPerProvider),
  ]);

  return { polymarket, kalshi };
}

export async function searchMarketsForProvider(
  provider: ProviderId,
  query: string,
  limit: number,
  options: SearchOptions,
): Promise<MarketSummary[]> {
  if (hasBackendMarketApi()) {
    try {
      const remoteMarkets = await fetchBackendSearchCandidates(provider, query, Math.max(limit * 3, 24));
      const markets = new Map<string, MarketSummary>();

      for (const market of remoteMarkets) {
        markets.set(market.id, market);
      }

      for (const market of options.localCandidates ?? []) {
        if (!markets.has(market.id)) {
          markets.set(market.id, market);
        }
      }

      return rankMarkets(query, [...markets.values()], {
        limit,
        remoteIds: new Set(remoteMarkets.map((market) => market.id)),
        savedIds: options.savedIds,
        recentIds: options.recentIds,
      });
    } catch {
      // Fall back to direct-provider mode if the backend is unavailable.
    }
  }

  return provider === "kalshi"
    ? searchKalshiMarkets(query, limit, options)
    : searchMarkets(query, limit, options);
}

export async function fetchHistoryForMarket(
  market: MarketSummary,
  range: RangeKey,
): Promise<PricePoint[]> {
  if (hasBackendMarketApi()) {
    try {
      return await fetchBackendMarketHistory(market, range);
    } catch {
      // Fall back to direct-provider mode if the backend is unavailable.
    }
  }

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
