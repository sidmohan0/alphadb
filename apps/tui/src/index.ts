import process from "node:process";

import { applyProviderTickerUpdate, buildCandlesForMarket, fetchHistoryForMarket, fetchTrendingMarketsForProvider, searchMarketsForProvider } from "./api/provider.js";
import { ansi } from "./lib/ansi.js";
import { KalshiTickerStream } from "./lib/kalshiLive.js";
import {
  loadPersistentState,
  mergeMarketsIntoPersistentState,
  queuePersistentStateWrite,
  toggleSavedMarket,
  touchRecentMarket,
} from "./lib/storage.js";
import { render } from "./render/renderer.js";
import { AppState, ListMode, MarketSummary, PersistentState, ProviderId, ProviderPanelState, RangeKey } from "./types.js";

const ranges: RangeKey[] = ["6h", "24h", "7d", "30d", "max"];
const defaultStoragePath = "loading...";

function createProviderPanelState(provider: ProviderId): ProviderPanelState {
  return {
    provider,
    markets: [],
    selectedIndex: 0,
    selectedOutcomeIndex: 0,
    candles: [],
    chartPoints: [],
    loadingMarkets: false,
    loadingChart: false,
    lastMarketRefreshAt: null,
    lastChartRefreshAt: null,
    liveStatusMessage: provider === "kalshi"
      ? "Kalshi live ticker not configured"
      : "Polymarket live ticker not enabled",
  };
}

const state: AppState = {
  provider: "polymarket",
  layoutMode: "unified",
  unifiedFocus: "polymarket",
  query: "",
  focused: "list",
  statusMessage: "Loading unified markets…",
  liveStatusMessage: "Polymarket live ticker not enabled",
  errorMessage: "",
  helpVisible: false,
  loadingMarkets: true,
  loadingChart: false,
  mode: "trending",
  trendingMarkets: [],
  savedMarkets: [],
  recentMarkets: [],
  savedMarketIds: [],
  recentMarketIds: [],
  searchResults: [],
  selectedIndex: 0,
  selectedOutcomeIndex: 0,
  range: "24h",
  candles: [],
  chartPoints: [],
  lastMarketRefreshAt: null,
  lastChartRefreshAt: null,
  storagePath: defaultStoragePath,
  unifiedPanels: {
    polymarket: createProviderPanelState("polymarket"),
    kalshi: createProviderPanelState("kalshi"),
  },
};

let closed = false;
let searchTimer: NodeJS.Timeout | null = null;
let previewToken = 0;
let browseMode: Exclude<ListMode, "search"> = "trending";
let persistentState: PersistentState = {
  savedMarkets: [],
  recentMarkets: [],
};
let kalshiTickerStream: KalshiTickerStream | null = null;

function activeSingleProvider(): ProviderId {
  return state.provider;
}

function focusedUnifiedProvider(): ProviderId {
  return state.unifiedFocus;
}

function activePanel(): ProviderPanelState {
  return state.unifiedPanels[focusedUnifiedProvider()];
}

function currentMarkets(): MarketSummary[] {
  if (state.layoutMode === "unified") {
    return activePanel().markets;
  }

  switch (state.mode) {
    case "search":
      return state.searchResults;
    case "saved":
      return state.savedMarkets;
    case "recent":
      return state.recentMarkets;
    default:
      return state.trendingMarkets;
  }
}

function selectedMarket(): MarketSummary | null {
  if (state.layoutMode === "unified") {
    const panel = activePanel();
    return panel.markets[panel.selectedIndex] ?? null;
  }

  return currentMarkets()[state.selectedIndex] ?? null;
}

function resetSelection(): void {
  if (state.layoutMode === "unified") {
    const panel = activePanel();
    panel.selectedIndex = 0;
    panel.selectedOutcomeIndex = 0;
    return;
  }

  state.selectedIndex = 0;
  state.selectedOutcomeIndex = 0;
}

function sanitizeSelection(): void {
  if (state.layoutMode === "unified") {
    const panel = activePanel();
    if (panel.markets.length === 0) {
      panel.selectedIndex = 0;
      panel.selectedOutcomeIndex = 0;
      return;
    }

    panel.selectedIndex = Math.min(Math.max(panel.selectedIndex, 0), panel.markets.length - 1);
    const outcomeCount = panel.markets[panel.selectedIndex].outcomes.length;
    panel.selectedOutcomeIndex = Math.min(Math.max(panel.selectedOutcomeIndex, 0), Math.max(0, outcomeCount - 1));
    return;
  }

  const markets = currentMarkets();
  if (markets.length === 0) {
    state.selectedIndex = 0;
    state.selectedOutcomeIndex = 0;
    return;
  }

  state.selectedIndex = Math.min(Math.max(state.selectedIndex, 0), markets.length - 1);
  const outcomeCount = markets[state.selectedIndex].outcomes.length;
  state.selectedOutcomeIndex = Math.min(Math.max(state.selectedOutcomeIndex, 0), Math.max(0, outcomeCount - 1));
}

function syncPersistentLists(preserveSelectedId?: string): void {
  state.savedMarketIds = persistentState.savedMarkets.map((entry) => entry.market.id);
  state.recentMarketIds = persistentState.recentMarkets.map((entry) => entry.market.id);

  state.savedMarkets = persistentState.savedMarkets
    .map((entry) => entry.market)
    .filter((market) => market.provider === activeSingleProvider());
  state.recentMarkets = persistentState.recentMarkets
    .map((entry) => entry.market)
    .filter((market) => market.provider === activeSingleProvider());

  if (state.layoutMode === "unified") {
    return;
  }

  if (preserveSelectedId) {
    const index = currentMarkets().findIndex((market) => market.id === preserveSelectedId);
    if (index >= 0) {
      state.selectedIndex = index;
    }
  }

  sanitizeSelection();
}

function draw(): void {
  if (closed) {
    return;
  }

  process.stdout.write(render(state));
}

function setStatus(message: string): void {
  state.statusMessage = message;
  draw();
}

function persistStateToDisk(): void {
  queuePersistentStateWrite(persistentState, state.storagePath);
}

function setError(message: string): void {
  state.errorMessage = message;
  draw();
}

function clearError(): void {
  if (!state.errorMessage) {
    return;
  }

  state.errorMessage = "";
  draw();
}

function mergeLiveMarkets(markets: MarketSummary[]): void {
  persistentState = mergeMarketsIntoPersistentState(persistentState, markets);
  if (state.layoutMode === "single") {
    syncPersistentLists(selectedMarket()?.id ?? undefined);
  } else {
    syncPersistentLists();
  }
  persistStateToDisk();
}

function updateMarketEverywhere(marketId: string, updater: (market: MarketSummary) => MarketSummary): void {
  const updateList = (markets: MarketSummary[]) =>
    markets.map((market) => (market.id === marketId ? updater(market) : market));

  state.trendingMarkets = updateList(state.trendingMarkets);
  state.searchResults = updateList(state.searchResults);
  state.savedMarkets = updateList(state.savedMarkets);
  state.recentMarkets = updateList(state.recentMarkets);
  for (const provider of ["polymarket", "kalshi"] as const) {
    const panel = state.unifiedPanels[provider];
    panel.markets = updateList(panel.markets);
  }
  persistentState = {
    savedMarkets: persistentState.savedMarkets.map((entry) => ({
      ...entry,
      market: entry.market.id === marketId ? updater(entry.market) : entry.market,
    })),
    recentMarkets: persistentState.recentMarkets.map((entry) => ({
      ...entry,
      market: entry.market.id === marketId ? updater(entry.market) : entry.market,
    })),
  };
  state.savedMarketIds = persistentState.savedMarkets.map((entry) => entry.market.id);
  state.recentMarketIds = persistentState.recentMarkets.map((entry) => entry.market.id);
  persistStateToDisk();
}

function applyKalshiTickerMessage(payload: Record<string, unknown>): void {
  const ticker = typeof payload.market_ticker === "string" ? payload.market_ticker : null;
  if (!ticker) {
    return;
  }

  const marketId = `kalshi:${ticker}`;
  updateMarketEverywhere(marketId, (market) => applyProviderTickerUpdate(market, payload));
  draw();
}

function syncKalshiTickerSubscription(): void {
  const kalshiTickers =
    state.layoutMode === "unified"
      ? state.unifiedPanels.kalshi.markets.slice(0, 75).map((market) => market.symbol)
      : state.provider === "kalshi"
        ? currentMarkets().slice(0, 75).map((market) => market.symbol)
        : [];

  if (kalshiTickers.length === 0) {
    if (kalshiTickerStream) {
      kalshiTickerStream.close();
      kalshiTickerStream = null;
    }
    if (state.layoutMode === "single") {
      state.liveStatusMessage = "Polymarket live ticker not enabled";
    } else {
      state.unifiedPanels.kalshi.liveStatusMessage = "Kalshi live idle";
    }
    return;
  }

  if (!kalshiTickerStream) {
    kalshiTickerStream = new KalshiTickerStream({
      onStatus: (message) => {
        if (state.layoutMode === "unified") {
          state.unifiedPanels.kalshi.liveStatusMessage = message;
        } else {
          state.liveStatusMessage = message;
        }
        draw();
      },
      onTicker: applyKalshiTickerMessage,
    });
  }

  const selected =
    state.layoutMode === "unified"
      ? state.unifiedPanels.kalshi.markets[state.unifiedPanels.kalshi.selectedIndex] ?? null
      : selectedMarket();

  const tickers = [...kalshiTickers];
  if (selected?.provider === "kalshi" && !tickers.includes(selected.symbol)) {
    tickers.push(selected.symbol);
  }

  kalshiTickerStream.replaceMarkets(tickers);
  const reason = kalshiTickerStream.getStatusReason();
  if (reason) {
    if (state.layoutMode === "unified") {
      state.unifiedPanels.kalshi.liveStatusMessage = reason;
    } else {
      state.liveStatusMessage = reason;
    }
  }
}

function showBrowseMode(mode: Exclude<ListMode, "search">): void {
  if (state.layoutMode === "unified") {
    state.statusMessage = "Saved, recent, and search views are available in single-provider mode.";
    draw();
    return;
  }

  browseMode = mode;
  state.mode = mode;
  state.focused = "list";
  state.selectedIndex = 0;
  state.selectedOutcomeIndex = 0;
  state.statusMessage = `Showing ${mode} markets.`;
  clearError();
  draw();
  syncKalshiTickerSubscription();
  void loadChart();
}

function rememberRecent(market: MarketSummary): void {
  persistentState = touchRecentMarket(persistentState, market);
  if (state.layoutMode === "single") {
    syncPersistentLists(state.mode === "recent" ? market.id : undefined);
  } else {
    syncPersistentLists();
  }
  persistStateToDisk();
}

function toggleSaveSelectedMarket(): void {
  const market = selectedMarket();
  if (!market) {
    return;
  }

  const result = toggleSavedMarket(persistentState, market);
  persistentState = result.state;
  if (state.layoutMode === "single") {
    syncPersistentLists(state.mode === "saved" ? market.id : undefined);
  } else {
    syncPersistentLists();
  }
  persistStateToDisk();
  state.statusMessage = result.saved ? `Saved market: ${market.question}` : `Removed market: ${market.question}`;
  draw();
}

async function loadChart(): Promise<void> {
  if (state.layoutMode === "unified") {
    await loadUnifiedChart(focusedUnifiedProvider());
    return;
  }

  const market = selectedMarket();
  if (!market) {
    state.chartPoints = [];
    state.candles = [];
    state.loadingChart = false;
    state.lastChartRefreshAt = null;
    state.statusMessage = "No market selected.";
    draw();
    return;
  }

  const previewId = ++previewToken;
  const outcome = market.outcomes[state.selectedOutcomeIndex] ?? market.outcomes[0];
  state.loadingChart = true;
  state.statusMessage = `Loading ${outcome?.name ?? "selected"} outcome chart…`;
  draw();

  try {
    const points = await fetchHistoryForMarket(market, state.range);
    if (previewId !== previewToken) {
      return;
    }

    const chartWidth = Math.max(12, (process.stdout.columns || 100) - Math.max(34, Math.floor((process.stdout.columns || 100) * 0.42)) - 12);
    state.chartPoints = points;
    state.candles = buildCandlesForMarket(market, points, chartWidth);
    state.loadingChart = false;
    state.lastChartRefreshAt = Date.now();
    state.statusMessage = `${market.question}`;
    rememberRecent(market);
    draw();
  } catch (error) {
    if (previewId !== previewToken) {
      return;
    }

    state.loadingChart = false;
    state.chartPoints = [];
    state.candles = [];
    setError(error instanceof Error ? error.message : "Failed to load chart.");
  }
}

async function loadUnifiedChart(provider: ProviderId): Promise<void> {
  const panel = state.unifiedPanels[provider];
  const market = panel.markets[panel.selectedIndex] ?? null;
  if (!market) {
    panel.chartPoints = [];
    panel.candles = [];
    panel.loadingChart = false;
    panel.lastChartRefreshAt = null;
    draw();
    return;
  }

  const previewId = ++previewToken;
  const outcome = market.outcomes[panel.selectedOutcomeIndex] ?? market.outcomes[0];
  panel.loadingChart = true;
  state.statusMessage = `Loading ${provider} ${outcome?.name ?? "selected"} chart…`;
  draw();

  try {
    const points = await fetchHistoryForMarket(market, state.range);
    if (previewId !== previewToken) {
      return;
    }

    const columns = process.stdout.columns || 120;
    const paneWidth = Math.max(40, Math.floor((Math.max(100, columns) - 3) / 2));
    const chartWidth = Math.max(12, paneWidth - 12);
    panel.chartPoints = points;
    panel.candles = buildCandlesForMarket(market, points, chartWidth);
    panel.loadingChart = false;
    panel.lastChartRefreshAt = Date.now();
    rememberRecent(market);
    draw();
  } catch (error) {
    if (previewId !== previewToken) {
      return;
    }

    panel.loadingChart = false;
    panel.chartPoints = [];
    panel.candles = [];
    setError(error instanceof Error ? error.message : `Failed to load ${provider} chart.`);
  }
}

async function loadTrending(): Promise<void> {
  if (state.layoutMode === "unified") {
    await loadUnifiedTrending();
    return;
  }

  state.loadingMarkets = true;
  if (!state.query.trim() && state.mode === "search") {
    state.mode = browseMode;
  }
  state.statusMessage = "Loading trending markets…";
  draw();

  try {
    state.trendingMarkets = await fetchTrendingMarketsForProvider(state.provider, 26);
    mergeLiveMarkets(state.trendingMarkets);
    state.loadingMarkets = false;
    state.lastMarketRefreshAt = Date.now();
    sanitizeSelection();
    state.statusMessage = `Loaded ${state.trendingMarkets.length} trending markets.`;
    draw();
    syncKalshiTickerSubscription();

    if (state.mode !== "search") {
      await loadChart();
    }
  } catch (error) {
    state.loadingMarkets = false;
    setError(error instanceof Error ? error.message : "Failed to load markets.");
  }
}

async function loadUnifiedTrending(): Promise<void> {
  state.statusMessage = "Loading unified markets…";
  state.unifiedPanels.polymarket.loadingMarkets = true;
  state.unifiedPanels.kalshi.loadingMarkets = true;
  draw();

  try {
    const [polymarketMarkets, kalshiMarkets] = await Promise.all([
      fetchTrendingMarketsForProvider("polymarket", 16),
      fetchTrendingMarketsForProvider("kalshi", 16),
    ]);

    state.unifiedPanels.polymarket.markets = polymarketMarkets;
    state.unifiedPanels.kalshi.markets = kalshiMarkets;
    state.unifiedPanels.polymarket.loadingMarkets = false;
    state.unifiedPanels.kalshi.loadingMarkets = false;
    state.unifiedPanels.polymarket.lastMarketRefreshAt = Date.now();
    state.unifiedPanels.kalshi.lastMarketRefreshAt = Date.now();
    mergeLiveMarkets([...polymarketMarkets, ...kalshiMarkets]);

    for (const provider of ["polymarket", "kalshi"] as const) {
      const panel = state.unifiedPanels[provider];
      panel.selectedIndex = Math.min(panel.selectedIndex, Math.max(0, panel.markets.length - 1));
      panel.selectedOutcomeIndex = 0;
    }

    state.statusMessage = "Unified view loaded.";
    draw();
    syncKalshiTickerSubscription();
    await Promise.all([
      loadUnifiedChart("polymarket"),
      loadUnifiedChart("kalshi"),
    ]);
  } catch (error) {
    state.unifiedPanels.polymarket.loadingMarkets = false;
    state.unifiedPanels.kalshi.loadingMarkets = false;
    setError(error instanceof Error ? error.message : "Failed to load unified markets.");
  }
}

async function runSearch(): Promise<void> {
  if (state.layoutMode === "unified") {
    state.statusMessage = "Search is available in single-provider mode. Press 1 or 2 to exit unified view.";
    draw();
    return;
  }

  const query = state.query.trim();
  if (!query) {
    state.mode = browseMode;
    state.searchResults = [];
    resetSelection();
    clearError();
    setStatus(`Showing ${browseMode} markets.`);
    await loadChart();
    return;
  }

  state.loadingMarkets = true;
  if (state.mode !== "search") {
    browseMode = state.mode as Exclude<ListMode, "search">;
  }
  state.mode = "search";
  state.statusMessage = `Searching "${query}"…`;
  draw();

  try {
    state.searchResults = await searchMarketsForProvider(state.provider, query, 18, {
      localCandidates: [
        ...state.trendingMarkets,
        ...state.savedMarkets,
        ...state.recentMarkets,
      ],
      savedIds: new Set(state.savedMarkets.map((market) => market.id)),
      recentIds: new Set(state.recentMarkets.map((market) => market.id)),
    });
    mergeLiveMarkets(state.searchResults);
    state.loadingMarkets = false;
    state.lastMarketRefreshAt = Date.now();
    resetSelection();
    sanitizeSelection();
    state.statusMessage = state.searchResults.length
      ? `Found ${state.searchResults.length} markets for "${query}".`
      : `No markets found for "${query}".`;
    draw();
    syncKalshiTickerSubscription();
    await loadChart();
  } catch (error) {
    state.loadingMarkets = false;
    setError(error instanceof Error ? error.message : "Search failed.");
  }
}

function queueSearch(): void {
  if (searchTimer) {
    clearTimeout(searchTimer);
  }

  searchTimer = setTimeout(() => {
    void runSearch();
  }, 250);
}

function moveSelection(delta: number): void {
  const markets = currentMarkets();
  if (markets.length === 0) {
    return;
  }

  clearError();
  if (state.layoutMode === "unified") {
    const panel = activePanel();
    panel.selectedIndex = Math.min(Math.max(panel.selectedIndex + delta, 0), markets.length - 1);
    panel.selectedOutcomeIndex = 0;
    draw();
    syncKalshiTickerSubscription();
    void loadUnifiedChart(focusedUnifiedProvider());
    return;
  }

  state.selectedIndex = Math.min(Math.max(state.selectedIndex + delta, 0), markets.length - 1);
  state.selectedOutcomeIndex = 0;
  draw();
  syncKalshiTickerSubscription();
  void loadChart();
}

function cycleOutcome(delta: number): void {
  const market = selectedMarket();
  if (!market || market.outcomes.length === 0) {
    return;
  }

  clearError();
  if (state.layoutMode === "unified") {
    const panel = activePanel();
    const next = (panel.selectedOutcomeIndex + delta + market.outcomes.length) % market.outcomes.length;
    panel.selectedOutcomeIndex = next;
    draw();
    void loadUnifiedChart(focusedUnifiedProvider());
    return;
  }

  const next = (state.selectedOutcomeIndex + delta + market.outcomes.length) % market.outcomes.length;
  state.selectedOutcomeIndex = next;
  draw();
  void loadChart();
}

function cycleRange(delta: number): void {
  const index = ranges.indexOf(state.range);
  const next = Math.min(Math.max(index + delta, 0), ranges.length - 1);
  state.range = ranges[next];
  draw();
  if (state.layoutMode === "unified") {
    void Promise.all([
      loadUnifiedChart("polymarket"),
      loadUnifiedChart("kalshi"),
    ]);
    return;
  }

  void loadChart();
}

function setProvider(provider: ProviderId): void {
  if (state.layoutMode === "unified") {
    state.layoutMode = "single";
  }

  if (state.provider === provider) {
    return;
  }

  state.provider = provider;
  state.trendingMarkets = [];
  state.searchResults = [];
  state.chartPoints = [];
  state.candles = [];
  resetSelection();
  syncPersistentLists();
  state.liveStatusMessage = provider === "kalshi"
    ? "Kalshi live ticker pending connection"
    : "Polymarket live ticker not enabled";
  draw();

  if (state.query.trim()) {
    void runSearch();
    return;
  }

  state.mode = browseMode;
  void loadTrending();
}

function setUnifiedMode(): void {
  if (state.layoutMode === "unified") {
    state.statusMessage = "Unified mode already active.";
    draw();
    return;
  }

  state.layoutMode = "unified";
  state.focused = "list";
  state.helpVisible = false;
  state.statusMessage = "Unified mode: Polymarket left, Kalshi right.";
  draw();
  void loadUnifiedTrending();
}

function shiftUnifiedFocus(delta: number): void {
  if (state.layoutMode !== "unified") {
    return;
  }

  state.unifiedFocus = delta < 0 ? "polymarket" : "kalshi";
  draw();
}

function cleanup(): void {
  if (closed) {
    return;
  }

  closed = true;
  if (searchTimer) {
    clearTimeout(searchTimer);
  }
  if (process.stdin.isTTY) {
    process.stdin.setRawMode(false);
    process.stdin.pause();
  }
  process.stdout.write(`${ansi.reset}${ansi.showCursor}${ansi.mainScreen}`);
}

function handleSearchInput(sequence: string): void {
  if (sequence === "\u0003") {
    cleanup();
    process.exit(0);
  }

  if (sequence === "\r") {
    void runSearch();
    return;
  }

  if (sequence === "\u001b") {
    state.focused = "list";
    clearError();
    if (!state.query.trim() && state.layoutMode === "single") {
      state.mode = browseMode;
    }
    draw();
    return;
  }

  if (sequence === "\u007f") {
    state.query = state.query.slice(0, -1);
    queueSearch();
    draw();
    return;
  }

  if (sequence === "\t") {
    state.focused = "list";
    draw();
    return;
  }

  if (sequence >= " " && sequence !== "\u007f") {
    state.query += sequence;
    queueSearch();
    draw();
  }
}

function handleListInput(sequence: string): void {
  switch (sequence) {
    case "\u0003":
    case "q":
      cleanup();
      process.exit(0);
      return;
    case "?":
      state.helpVisible = !state.helpVisible;
      draw();
      return;
    case "/":
      if (state.layoutMode === "unified") {
        state.statusMessage = "Search is disabled in unified mode. Press 1 or 2 for single-provider mode.";
        draw();
        return;
      }
      state.focused = "search";
      draw();
      return;
    case "1":
      setProvider("polymarket");
      return;
    case "2":
      setProvider("kalshi");
      return;
    case "3":
      setUnifiedMode();
      return;
    case "t":
      showBrowseMode("trending");
      return;
    case "v":
      showBrowseMode("saved");
      return;
    case "u":
      showBrowseMode("recent");
      return;
    case "f":
      toggleSaveSelectedMarket();
      return;
    case "\u001b":
      clearError();
      state.helpVisible = false;
      draw();
      return;
    case "\u001b[A":
    case "k":
      moveSelection(-1);
      return;
    case "\u001b[B":
    case "j":
      moveSelection(1);
      return;
    case "h":
      shiftUnifiedFocus(-1);
      return;
    case "l":
      shiftUnifiedFocus(1);
      return;
    case "o":
    case "\u001b[C":
      if (state.layoutMode === "unified" && sequence === "\u001b[C") {
        shiftUnifiedFocus(1);
        return;
      }
      cycleOutcome(1);
      return;
    case "\u001b[D":
      if (state.layoutMode === "unified") {
        shiftUnifiedFocus(-1);
        return;
      }
      cycleOutcome(-1);
      return;
    case "[":
      cycleRange(-1);
      return;
    case "]":
      cycleRange(1);
      return;
    case "r":
      clearError();
      if (state.layoutMode === "unified") {
        void loadUnifiedTrending();
      } else if (state.mode === "search" && state.query.trim()) {
        void runSearch();
      } else {
        void loadTrending();
      }
      return;
    case "\t":
      state.focused = "search";
      draw();
      return;
    case "\r":
      void loadChart();
      return;
    default:
      if (state.layoutMode === "unified") {
        return;
      }
      if (sequence.length === 1 && /[ -~]/.test(sequence)) {
        state.focused = "search";
        state.query += sequence;
        queueSearch();
        draw();
      }
  }
}

async function boot(): Promise<void> {
  const loaded = await loadPersistentState();
  persistentState = loaded.state;
  state.storagePath = loaded.path;
  syncPersistentLists();
  process.stdout.write(`${ansi.altScreen}${ansi.hideCursor}`);
  if (process.stdin.isTTY) {
    process.stdin.setRawMode(true);
  }

  process.stdin.resume();
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk: string) => {
    if (state.focused === "search") {
      handleSearchInput(chunk);
      return;
    }

    handleListInput(chunk);
  });

  process.stdout.on("resize", () => {
    draw();
    if (state.layoutMode === "unified") {
      void Promise.all([
        loadUnifiedChart("polymarket"),
        loadUnifiedChart("kalshi"),
      ]);
      return;
    }
    void loadChart();
  });
  process.on("SIGINT", cleanup);
  process.on("SIGTERM", cleanup);
  process.on("exit", cleanup);

  draw();
  await loadTrending();
}

void boot().catch((error) => {
  cleanup();
  const message = error instanceof Error ? error.message : String(error);
  console.error(message);
  process.exit(1);
});
