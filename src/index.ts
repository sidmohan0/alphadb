import process from "node:process";

import { fetchMarketHistory, fetchTrendingMarkets, searchMarkets, buildCandles } from "./api/polymarket.js";
import { ansi } from "./lib/ansi.js";
import {
  loadPersistentState,
  mergeMarketsIntoPersistentState,
  queuePersistentStateWrite,
  toggleSavedMarket,
  touchRecentMarket,
} from "./lib/storage.js";
import { render } from "./render/renderer.js";
import { AppState, ListMode, MarketSummary, PersistentState, RangeKey } from "./types.js";

const ranges: RangeKey[] = ["6h", "24h", "7d", "30d", "max"];
const defaultStoragePath = "loading...";

const state: AppState = {
  query: "",
  focused: "list",
  statusMessage: "Loading trending markets…",
  errorMessage: "",
  helpVisible: false,
  loadingMarkets: true,
  loadingChart: false,
  mode: "trending",
  trendingMarkets: [],
  savedMarkets: [],
  recentMarkets: [],
  searchResults: [],
  selectedIndex: 0,
  selectedOutcomeIndex: 0,
  range: "24h",
  candles: [],
  chartPoints: [],
  lastMarketRefreshAt: null,
  lastChartRefreshAt: null,
  storagePath: defaultStoragePath,
};

let closed = false;
let searchTimer: NodeJS.Timeout | null = null;
let previewToken = 0;
let browseMode: Exclude<ListMode, "search"> = "trending";
let persistentState: PersistentState = {
  savedMarkets: [],
  recentMarkets: [],
};

function currentMarkets(): MarketSummary[] {
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
  return currentMarkets()[state.selectedIndex] ?? null;
}

function resetSelection(): void {
  state.selectedIndex = 0;
  state.selectedOutcomeIndex = 0;
}

function sanitizeSelection(): void {
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
  state.savedMarkets = persistentState.savedMarkets.map((entry) => entry.market);
  state.recentMarkets = persistentState.recentMarkets.map((entry) => entry.market);

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
  syncPersistentLists(selectedMarket()?.id ?? undefined);
  persistStateToDisk();
}

function showBrowseMode(mode: Exclude<ListMode, "search">): void {
  browseMode = mode;
  state.mode = mode;
  state.focused = "list";
  state.selectedIndex = 0;
  state.selectedOutcomeIndex = 0;
  state.statusMessage = `Showing ${mode} markets.`;
  clearError();
  draw();
  void loadChart();
}

function rememberRecent(market: MarketSummary): void {
  persistentState = touchRecentMarket(persistentState, market);
  syncPersistentLists(state.mode === "recent" ? market.id : undefined);
  persistStateToDisk();
}

function toggleSaveSelectedMarket(): void {
  const market = selectedMarket();
  if (!market) {
    return;
  }

  const result = toggleSavedMarket(persistentState, market);
  persistentState = result.state;
  syncPersistentLists(state.mode === "saved" ? market.id : undefined);
  persistStateToDisk();
  state.statusMessage = result.saved ? `Saved market: ${market.question}` : `Removed market: ${market.question}`;
  draw();
}

async function loadChart(): Promise<void> {
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
    const points = await fetchMarketHistory(outcome.tokenId, state.range);
    if (previewId !== previewToken) {
      return;
    }

    const chartWidth = Math.max(12, (process.stdout.columns || 100) - Math.max(34, Math.floor((process.stdout.columns || 100) * 0.42)) - 12);
    state.chartPoints = points;
    state.candles = buildCandles(points, chartWidth);
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

async function loadTrending(): Promise<void> {
  state.loadingMarkets = true;
  if (!state.query.trim() && state.mode === "search") {
    state.mode = browseMode;
  }
  state.statusMessage = "Loading trending markets…";
  draw();

  try {
    state.trendingMarkets = await fetchTrendingMarkets(26);
    mergeLiveMarkets(state.trendingMarkets);
    state.loadingMarkets = false;
    state.lastMarketRefreshAt = Date.now();
    sanitizeSelection();
    state.statusMessage = `Loaded ${state.trendingMarkets.length} trending markets.`;
    draw();

    if (state.mode !== "search") {
      await loadChart();
    }
  } catch (error) {
    state.loadingMarkets = false;
    setError(error instanceof Error ? error.message : "Failed to load markets.");
  }
}

async function runSearch(): Promise<void> {
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
    state.searchResults = await searchMarkets(query, 18, {
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
  state.selectedIndex = Math.min(Math.max(state.selectedIndex + delta, 0), markets.length - 1);
  state.selectedOutcomeIndex = 0;
  draw();
  void loadChart();
}

function cycleOutcome(delta: number): void {
  const market = selectedMarket();
  if (!market || market.outcomes.length === 0) {
    return;
  }

  clearError();
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
  void loadChart();
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
    if (!state.query.trim()) {
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
      state.focused = "search";
      draw();
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
    case "o":
    case "\u001b[C":
      cycleOutcome(1);
      return;
    case "\u001b[D":
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
      if (state.mode === "search" && state.query.trim()) {
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
