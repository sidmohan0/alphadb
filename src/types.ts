export type RangeKey = "6h" | "24h" | "7d" | "30d" | "max";
export type ListMode = "trending" | "saved" | "recent" | "search";

export interface OutcomeToken {
  name: string;
  tokenId: string;
  price: number | null;
}

export interface MarketSummary {
  id: string;
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

export interface PersistedMarketSnapshot {
  market: MarketSummary;
  savedAt?: number;
  viewedAt: number;
}

export interface PersistentState {
  savedMarkets: PersistedMarketSnapshot[];
  recentMarkets: PersistedMarketSnapshot[];
}

export interface PricePoint {
  timestamp: number;
  price: number;
}

export interface Candle {
  startTime: number;
  endTime: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface AppState {
  query: string;
  focused: "list" | "search";
  statusMessage: string;
  errorMessage: string;
  helpVisible: boolean;
  loadingMarkets: boolean;
  loadingChart: boolean;
  mode: ListMode;
  trendingMarkets: MarketSummary[];
  savedMarkets: MarketSummary[];
  recentMarkets: MarketSummary[];
  searchResults: MarketSummary[];
  selectedIndex: number;
  selectedOutcomeIndex: number;
  range: RangeKey;
  candles: Candle[];
  chartPoints: PricePoint[];
  lastMarketRefreshAt: number | null;
  lastChartRefreshAt: number | null;
  storagePath: string;
}
