export type ProviderId = "polymarket" | "kalshi";
export type RangeKey = "6h" | "24h" | "7d" | "30d" | "max";

export interface OutcomeToken {
  name: string;
  tokenId: string;
  price: number | null;
}

export interface MarketSummary {
  id: string;
  provider: ProviderId;
  symbol: string;
  question: string;
  conditionId: string;
  slug: string;
  endDate: string | null;
  liquidity: number;
  volume24hr: number;
  volumeTotal: number;
  bestBid: number | null;
  bestAsk: number | null;
  lastTradePrice: number | null;
  oneDayPriceChange: number | null;
  eventTitle: string | null;
  seriesTitle: string | null;
  image: string | null;
  outcomes: OutcomeToken[];
}

export interface PricePoint {
  timestamp: number;
  price: number;
}

export interface PersistedMarketSnapshot {
  market: MarketSummary;
  savedAt?: number;
  viewedAt: number;
}

export interface PersistentState {
  savedMarkets: PersistedMarketSnapshot[];
  recentMarkets: PersistedMarketSnapshot[];
}

export interface MarketStreamSubscription {
  provider: ProviderId;
  marketId: string;
  symbol: string;
  outcomeTokenIds?: string[];
}

export interface MarketStreamUpdate {
  provider: ProviderId;
  marketId: string;
  symbol: string;
  bestBid?: number | null;
  bestAsk?: number | null;
  lastTradePrice?: number | null;
  volume24hr?: number;
  volumeTotal?: number;
  liquidity?: number;
  oneDayPriceChange?: number | null;
  outcomePrices?: Record<string, number | null>;
  receivedAt: number;
}

export interface MarketStreamStatus {
  provider: ProviderId;
  message: string;
}
