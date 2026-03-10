import { AlphaDBClient } from "@alphadb/sdk";
import type { MarketStreamSubscription, MarketStreamUpdate, MarketSummary, PersistentState, ProviderId, RangeKey } from "@alphadb/market-core";

export type ViewMode = "trending" | "saved" | "recent" | "search";

export interface ProviderSelectionState {
  selectedIndex: number;
  chartPoints: { timestamp: number; price: number }[];
  loadingChart: boolean;
  lastChartRefreshAt: number | null;
  liveStatusMessage: string;
}

export interface WorkspaceState {
  trending: Record<ProviderId, MarketSummary[]>;
  search: Record<ProviderId, MarketSummary[]>;
  persistent: PersistentState;
}

export interface ProviderTheme {
  label: string;
  border: string;
  borderSoft: string;
  panel: string;
  selected: string;
  text: string;
  accent: string;
  chartLine: string;
  chartFillTop: string;
  chartFillBottom: string;
}

const WEB_STATE_KEY = "alphadb-web-persistent-state";
const WEB_TOKEN_KEY = "alphadb-web-api-token";

export const RANGE_ORDER: RangeKey[] = ["6h", "24h", "7d", "30d", "max"];
export const PROVIDERS: ProviderId[] = ["polymarket", "kalshi"];

export const providerThemes: Record<ProviderId, ProviderTheme> = {
  polymarket: {
    label: "Polymarket",
    border: "#0dd4ff",
    borderSoft: "#0a7a92",
    panel: "#041058",
    selected: "#00d4ff",
    text: "#7ce8ff",
    accent: "#1fb6ff",
    chartLine: "#7ef29a",
    chartFillTop: "rgba(13, 212, 255, 0.38)",
    chartFillBottom: "rgba(4, 16, 88, 0.18)",
  },
  kalshi: {
    label: "Kalshi",
    border: "#3da0ff",
    borderSoft: "#1f5ca5",
    panel: "#071649",
    selected: "#3da0ff",
    text: "#8fc5ff",
    accent: "#72f6ff",
    chartLine: "#90ff66",
    chartFillTop: "rgba(61, 160, 255, 0.32)",
    chartFillBottom: "rgba(7, 22, 73, 0.18)",
  },
};

export function defaultProviderState(provider: ProviderId): ProviderSelectionState {
  return {
    selectedIndex: 0,
    chartPoints: [],
    loadingChart: true,
    lastChartRefreshAt: null,
    liveStatusMessage: `${providerThemes[provider].label} live feed idle`,
  };
}

export function defaultPersistentState(): PersistentState {
  return { savedMarkets: [], recentMarkets: [] };
}

export function loadLocalPersistentState(): PersistentState {
  if (typeof window === "undefined") {
    return defaultPersistentState();
  }

  try {
    const raw = window.localStorage.getItem(WEB_STATE_KEY);
    if (!raw) {
      return defaultPersistentState();
    }

    const parsed = JSON.parse(raw) as Partial<PersistentState>;
    return {
      savedMarkets: Array.isArray(parsed.savedMarkets) ? parsed.savedMarkets : [],
      recentMarkets: Array.isArray(parsed.recentMarkets) ? parsed.recentMarkets : [],
    };
  } catch {
    return defaultPersistentState();
  }
}

export function persistLocalState(state: PersistentState): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(WEB_STATE_KEY, JSON.stringify(state));
}

export function loadStoredToken(): string {
  if (typeof window === "undefined") {
    return "";
  }

  return window.localStorage.getItem(WEB_TOKEN_KEY) ?? "";
}

export function persistToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }

  if (token.trim()) {
    window.localStorage.setItem(WEB_TOKEN_KEY, token.trim());
    return;
  }

  window.localStorage.removeItem(WEB_TOKEN_KEY);
}

export function createClient(apiToken: string): AlphaDBClient {
  const runtimeConfiguredBaseUrl =
    typeof window !== "undefined" &&
    typeof (window as Window & { __ALPHADB_CONFIG__?: { apiBaseUrl?: string } }).__ALPHADB_CONFIG__?.apiBaseUrl === "string"
      ? (window as Window & { __ALPHADB_CONFIG__?: { apiBaseUrl?: string } }).__ALPHADB_CONFIG__?.apiBaseUrl?.trim()
      : "";
  const configuredBaseUrl = runtimeConfiguredBaseUrl || import.meta.env.VITE_ALPHADB_API_BASE_URL?.trim();
  const originBaseUrl =
    typeof window !== "undefined" ? `${window.location.origin.replace(/\/+$/, "")}/api` : null;

  return new AlphaDBClient({
    baseUrl: configuredBaseUrl || originBaseUrl,
    apiToken: apiToken.trim() || "",
    userAgent: "alphadb-web",
  });
}

export function cloneMarket(market: MarketSummary): MarketSummary {
  return {
    ...market,
    outcomes: market.outcomes.map((outcome) => ({ ...outcome })),
  };
}

export function applyLiveUpdate(market: MarketSummary, update: MarketStreamUpdate): MarketSummary {
  const next = cloneMarket(market);

  if (update.bestBid !== undefined) {
    next.bestBid = update.bestBid ?? null;
  }
  if (update.bestAsk !== undefined) {
    next.bestAsk = update.bestAsk ?? null;
  }
  if (update.lastTradePrice !== undefined) {
    next.lastTradePrice = update.lastTradePrice ?? null;
  }
  if (update.volume24hr !== undefined) {
    next.volume24hr = update.volume24hr;
  }
  if (update.volumeTotal !== undefined) {
    next.volumeTotal = update.volumeTotal;
  }
  if (update.liquidity !== undefined) {
    next.liquidity = update.liquidity;
  }
  if (update.oneDayPriceChange !== undefined) {
    next.oneDayPriceChange = update.oneDayPriceChange ?? null;
  }
  if (update.outcomePrices) {
    const outcomePrices = update.outcomePrices;
    next.outcomes = next.outcomes.map((outcome) => ({
      ...outcome,
      price: Object.prototype.hasOwnProperty.call(outcomePrices, outcome.tokenId)
        ? outcomePrices[outcome.tokenId] ?? null
        : outcome.price,
    }));
  }

  return next;
}

export function touchRecentState(state: PersistentState, market: MarketSummary): PersistentState {
  const now = Date.now();
  const recentMarkets = [
    {
      market: cloneMarket(market),
      viewedAt: now,
      savedAt: state.savedMarkets.find((entry) => entry.market.id === market.id)?.savedAt,
    },
    ...state.recentMarkets.filter((entry) => entry.market.id !== market.id),
  ].slice(0, 24);

  return {
    ...state,
    recentMarkets,
  };
}

export function toggleSavedState(
  state: PersistentState,
  market: MarketSummary,
): { state: PersistentState; saved: boolean } {
  const existing = state.savedMarkets.find((entry) => entry.market.id === market.id);
  if (existing) {
    return {
      saved: false,
      state: {
        ...state,
        savedMarkets: state.savedMarkets.filter((entry) => entry.market.id !== market.id),
      },
    };
  }

  const savedAt = Date.now();
  return {
    saved: true,
    state: {
      ...state,
      savedMarkets: [
        {
          market: cloneMarket(market),
          savedAt,
          viewedAt: state.recentMarkets.find((entry) => entry.market.id === market.id)?.viewedAt ?? savedAt,
        },
        ...state.savedMarkets,
      ],
    },
  };
}

export function updatePersistentStateMarkets(
  state: PersistentState,
  marketId: string,
  updater: (market: MarketSummary) => MarketSummary,
): PersistentState {
  return {
    savedMarkets: state.savedMarkets.map((entry) => ({
      ...entry,
      market: entry.market.id === marketId ? updater(entry.market) : entry.market,
    })),
    recentMarkets: state.recentMarkets.map((entry) => ({
      ...entry,
      market: entry.market.id === marketId ? updater(entry.market) : entry.market,
    })),
  };
}

export function formatCompactMoney(value: number | null | undefined): string {
  const safe = Number(value ?? 0);
  if (!Number.isFinite(safe)) {
    return "$0";
  }

  if (safe >= 1_000_000_000) {
    return `$${(safe / 1_000_000_000).toFixed(1)}B`;
  }
  if (safe >= 1_000_000) {
    return `$${(safe / 1_000_000).toFixed(1)}M`;
  }
  if (safe >= 1_000) {
    return `$${(safe / 1_000).toFixed(1)}K`;
  }
  return `$${safe.toFixed(safe >= 100 ? 0 : 1)}`;
}

export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }

  return `${(value * 100).toFixed(value * 100 >= 10 ? 1 : 2)}c`;
}

export function formatEndDate(value: string | null): string {
  if (!value) {
    return "--";
  }

  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return "--";
  }

  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(date);
}

export function formatAge(timestamp: number | null): string {
  if (!timestamp) {
    return "never";
  }

  const deltaSeconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (deltaSeconds < 60) {
    return `${deltaSeconds}s ago`;
  }

  const deltaMinutes = Math.round(deltaSeconds / 60);
  if (deltaMinutes < 60) {
    return `${deltaMinutes}m ago`;
  }

  const deltaHours = Math.round(deltaMinutes / 60);
  return `${deltaHours}h ago`;
}

export function clampIndex(index: number, total: number): number {
  if (total <= 0) {
    return 0;
  }

  return Math.max(0, Math.min(index, total - 1));
}

export function buildSubscriptions(markets: Record<ProviderId, MarketSummary[]>): MarketStreamSubscription[] {
  return [
    ...markets.polymarket.slice(0, 20).map((market) => ({
      provider: "polymarket" as const,
      marketId: market.id,
      symbol: market.symbol,
      outcomeTokenIds: market.outcomes.map((outcome) => outcome.tokenId),
    })),
    ...markets.kalshi.slice(0, 30).map((market) => ({
      provider: "kalshi" as const,
      marketId: market.id,
      symbol: market.symbol,
    })),
  ];
}

export function displayMarketsForMode(
  mode: ViewMode,
  provider: ProviderId,
  workspace: WorkspaceState,
): MarketSummary[] {
  if (mode === "search") {
    return workspace.search[provider];
  }

  if (mode === "saved") {
    return workspace.persistent.savedMarkets
      .map((entry) => entry.market)
      .filter((market) => market.provider === provider);
  }

  if (mode === "recent") {
    return workspace.persistent.recentMarkets
      .map((entry) => entry.market)
      .filter((market) => market.provider === provider);
  }

  return workspace.trending[provider];
}
