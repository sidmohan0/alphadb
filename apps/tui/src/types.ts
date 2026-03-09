export type RangeKey = "6h" | "24h" | "7d" | "30d" | "max";
export type ListMode = "trending" | "saved" | "recent" | "search";
export type ProviderId = "polymarket" | "kalshi";
export type LayoutMode = "single" | "unified";

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

export interface ProviderPanelState {
  provider: ProviderId;
  markets: MarketSummary[];
  selectedIndex: number;
  selectedOutcomeIndex: number;
  candles: Candle[];
  chartPoints: PricePoint[];
  loadingMarkets: boolean;
  loadingChart: boolean;
  lastMarketRefreshAt: number | null;
  lastChartRefreshAt: number | null;
  liveStatusMessage: string;
}

export interface AppState {
  provider: ProviderId;
  layoutMode: LayoutMode;
  unifiedFocus: ProviderId;
  query: string;
  focused: "list" | "search";
  statusMessage: string;
  liveStatusMessage: string;
  errorMessage: string;
  helpVisible: boolean;
  loadingMarkets: boolean;
  loadingChart: boolean;
  mode: ListMode;
  trendingMarkets: MarketSummary[];
  savedMarkets: MarketSummary[];
  recentMarkets: MarketSummary[];
  savedMarketIds: string[];
  recentMarketIds: string[];
  searchResults: MarketSummary[];
  selectedIndex: number;
  selectedOutcomeIndex: number;
  range: RangeKey;
  candles: Candle[];
  chartPoints: PricePoint[];
  lastMarketRefreshAt: number | null;
  lastChartRefreshAt: number | null;
  storagePath: string;
  unifiedPanels: Record<ProviderId, ProviderPanelState>;
}
