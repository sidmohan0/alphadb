import type {
  MarketSummary,
  PersistedMarketSnapshot,
  PersistentState,
  PricePoint,
  ProviderId,
  RangeKey,
} from "@alphadb/market-core";

export type {
  MarketSummary,
  OutcomeToken,
  PersistedMarketSnapshot,
  PersistentState,
  PricePoint,
  ProviderId,
  RangeKey,
} from "@alphadb/market-core";

export type ListMode = "trending" | "saved" | "recent" | "search";
export type LayoutMode = "single" | "unified";

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
