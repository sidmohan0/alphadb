import {
  fetchBackendMarketHistory,
  fetchBackendSearchCandidates,
  fetchBackendUnifiedSearchMarkets,
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
import { Candle, MarketStreamUpdate, MarketSummary, PricePoint, ProviderId, RangeKey } from "../types.js";

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
      return await fetchBackendSearchCandidates(provider, query, limit);
    } catch {
      // Fall back to direct-provider mode if the backend is unavailable.
    }
  }

  return provider === "kalshi"
    ? searchKalshiMarkets(query, limit, options)
    : searchMarkets(query, limit, options);
}

export async function searchUnifiedMarkets(
  query: string,
  limitPerProvider: number,
): Promise<Record<ProviderId, MarketSummary[]>> {
  if (hasBackendMarketApi()) {
    try {
      return await fetchBackendUnifiedSearchMarkets(query, limitPerProvider);
    } catch {
      // Fall back to provider-direct mode if the backend is unavailable.
    }
  }

  const [polymarket, kalshi] = await Promise.all([
    searchMarkets(query, limitPerProvider, {
      localCandidates: [],
      savedIds: new Set(),
      recentIds: new Set(),
    }),
    searchKalshiMarkets(query, limitPerProvider, {
      localCandidates: [],
      savedIds: new Set(),
      recentIds: new Set(),
    }),
  ]);

  return { polymarket, kalshi };
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

export function applyMarketStreamUpdate(market: MarketSummary, update: MarketStreamUpdate): MarketSummary {
  if (market.provider !== update.provider || market.id !== update.marketId) {
    return market;
  }

  return {
    ...market,
    bestBid: update.bestBid ?? market.bestBid,
    bestAsk: update.bestAsk ?? market.bestAsk,
    lastTradePrice: update.lastTradePrice ?? market.lastTradePrice,
    volume24hr: update.volume24hr ?? market.volume24hr,
    volumeTotal: update.volumeTotal ?? market.volumeTotal,
    liquidity: update.liquidity ?? market.liquidity,
    oneDayPriceChange: update.oneDayPriceChange ?? market.oneDayPriceChange,
    outcomes: market.outcomes.map((outcome) => ({
      ...outcome,
      price: update.outcomePrices && outcome.tokenId in update.outcomePrices
        ? update.outcomePrices[outcome.tokenId] ?? null
        : outcome.price,
    })),
  };
}
