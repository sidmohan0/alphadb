import { ansi, color, fitAnsi, moveTo, padAnsi, truncate, visibleWidth } from "../lib/ansi.js";
import { formatAgo, formatDate, formatDateTime, formatMoney, formatPercent, formatPrice } from "../lib/format.js";
import { AppState, Candle, MarketSummary, ProviderId, ProviderPanelState } from "../types.js";

const baseTheme = {
  border: color(38, 5, 51),
  muted: color(38, 5, 250),
  panel: color(48, 5, 233),
  headerBg: color(48, 5, 17),
  accent: color(38, 5, 87),
  accentBg: color(48, 5, 31),
  blue: color(38, 5, 123),
  green: color(38, 5, 84),
  red: color(38, 5, 203),
  yellow: color(38, 5, 221),
  magenta: color(38, 5, 213),
  gold: color(38, 5, 220),
  grid: color(38, 5, 45),
  cyan: color(38, 5, 51),
  white: color(97),
  selectedFg: color(30),
  selectedBg: color(48, 5, 87),
  inputBg: color(48, 5, 236),
  inputActiveBg: color(48, 5, 31),
  lineFill: color(48, 5, 235),
  tabIdle: color(48, 5, 235),
};

type Theme = typeof baseTheme;

function getThemeForProvider(provider: AppState["provider"]): Theme {
  if (provider === "kalshi") {
    return {
      ...baseTheme,
      border: color(38, 5, 39),
      headerBg: color(48, 5, 18),
      accent: color(38, 5, 153),
      accentBg: color(48, 5, 25),
      blue: color(38, 5, 117),
      cyan: color(38, 5, 159),
      grid: color(38, 5, 33),
      selectedBg: color(48, 5, 39),
      inputActiveBg: color(48, 5, 25),
      lineFill: color(48, 5, 18),
      tabIdle: color(48, 5, 17),
    };
  }

  return {
    ...baseTheme,
    border: color(38, 5, 51),
    headerBg: color(48, 5, 17),
    accent: color(38, 5, 87),
    accentBg: color(48, 5, 31),
    blue: color(38, 5, 123),
    cyan: color(38, 5, 51),
    grid: color(38, 5, 45),
    selectedBg: color(48, 5, 45),
    inputActiveBg: color(48, 5, 31),
    lineFill: color(48, 5, 17),
    tabIdle: color(48, 5, 18),
  };
}

function getTheme(state: AppState): Theme {
  return getThemeForProvider(state.layoutMode === "unified" ? state.unifiedFocus : state.provider);
}

function writeLine(buffer: string[], row: number, col: number, text: string): void {
  buffer.push(`${moveTo(row, col)}${text}${ansi.reset}`);
}

function repeat(char: string, count: number): string {
  return Array.from({ length: Math.max(0, count) }, () => char).join("");
}

function selectedMarket(state: AppState): MarketSummary | null {
  if (state.layoutMode === "unified") {
    const panel = state.unifiedPanels[state.unifiedFocus];
    return panel.markets[panel.selectedIndex] ?? null;
  }

  const list =
    state.mode === "search" ? state.searchResults :
    state.mode === "saved" ? state.savedMarkets :
    state.mode === "recent" ? state.recentMarkets :
    state.trendingMarkets;
  return list[state.selectedIndex] ?? null;
}

function selectedMarketFromPanel(panel: ProviderPanelState): MarketSummary | null {
  return panel.markets[panel.selectedIndex] ?? null;
}

function isSaved(state: AppState, marketId: string): boolean {
  return state.savedMarketIds.includes(marketId);
}

function isRecent(state: AppState, marketId: string): boolean {
  return state.recentMarketIds.includes(marketId);
}

function providerLabel(provider: ProviderId): string {
  return provider === "kalshi" ? "Kalshi" : "Polymarket";
}

function panelTop(theme: Theme, buffer: string[], row: number, col: number, width: number, title: string): void {
  const inner = Math.max(0, width - 2);
  const label = ` ${title} `;
  const left = Math.max(0, Math.floor((inner - label.length) / 2));
  const right = Math.max(0, inner - left - label.length);
  writeLine(
    buffer,
    row,
    col,
    `${theme.border}┌${repeat("─", left)}${theme.accentBg}${theme.white}${label}${ansi.reset}${theme.border}${repeat("─", right)}┐`,
  );
}

function panelBottom(theme: Theme, buffer: string[], row: number, col: number, width: number): void {
  writeLine(buffer, row, col, `${theme.border}└${repeat("─", Math.max(0, width - 2))}┘`);
}

function panelBodyLine(theme: Theme, buffer: string[], row: number, col: number, width: number, text = ""): void {
  const inner = Math.max(0, width - 2);
  writeLine(buffer, row, col, `${theme.border}│${theme.lineFill}${fitAnsi(text, inner)}${ansi.reset}${theme.border}│`);
}

function renderUnifiedDivider(buffer: string[], row: number, height: number, col: number, focusedProvider: ProviderId): void {
  const focusedTheme = getThemeForProvider(focusedProvider);
  const otherTheme = getThemeForProvider(focusedProvider === "polymarket" ? "kalshi" : "polymarket");
  for (let offset = 0; offset < height; offset += 1) {
    const tone = offset % 2 === 0 ? focusedTheme.border : otherTheme.border;
    writeLine(buffer, row + offset, col, `${tone}│`);
  }
}

function renderHeader(buffer: string[], width: number, state: AppState): void {
  const theme = getTheme(state);
  const market = selectedMarket(state);
  const marketRefreshAt = state.layoutMode === "unified"
    ? state.unifiedPanels[state.unifiedFocus].lastMarketRefreshAt
    : state.lastMarketRefreshAt;
  const chartRefreshAt = state.layoutMode === "unified"
    ? state.unifiedPanels[state.unifiedFocus].lastChartRefreshAt
    : state.lastChartRefreshAt;
  writeLine(buffer, 1, 1, `${theme.headerBg}${" ".repeat(width)}${ansi.reset}`);
  writeLine(buffer, 2, 1, `${theme.headerBg}${" ".repeat(width)}${ansi.reset}`);
  const left = `${theme.white}${theme.headerBg} AlphaDB ${ansi.reset}${theme.accent}${theme.headerBg} Markets TUI ${ansi.reset}`;
  const middle = `${theme.blue}${theme.headerBg} ${state.layoutMode === "unified" ? `Unified Mode · Focus ${providerLabel(state.unifiedFocus)}` : `${providerLabel(state.provider)} · ${state.mode === "search" ? "Search results" : state.mode === "saved" ? "Saved markets" : state.mode === "recent" ? "Recent markets" : "Trending by 24h volume"}`} ${ansi.reset}`;
  const right = `${theme.muted}${theme.headerBg} markets ${formatAgo(marketRefreshAt)}  chart ${formatAgo(chartRefreshAt)} ${ansi.reset}`;
  const full = `${left}  ${middle}`;
  const rightWidth = visibleWidth(right);
  writeLine(buffer, 1, 1, padAnsi(full, Math.max(0, width - rightWidth - 1)));
  writeLine(buffer, 1, Math.max(1, width - rightWidth + 1), right);
  if (market) {
    writeLine(buffer, 2, 1, `${theme.muted}${truncate(market.question, width)}${ansi.reset}`);
  }
}

function renderSearch(buffer: string[], row: number, col: number, width: number, state: AppState): void {
  const theme = getTheme(state);
  const label = state.focused === "search" ? `${theme.inputActiveBg}${theme.white}` : `${theme.inputBg}${theme.white}`;
  const prompt = `${theme.accent}Search${ansi.reset}`;
  const bodyWidth = Math.max(1, width - 10);
  const body = truncate(state.query || "type / to search markets", bodyWidth);
  writeLine(buffer, row, col, `${prompt} ${label} ${body} ${ansi.reset}`);
}

function renderModes(buffer: string[], row: number, col: number, state: AppState): void {
  const theme = getTheme(state);
  const providers = [
    { key: "1", label: "Polymarket", active: state.layoutMode === "single" && state.provider === "polymarket" },
    { key: "2", label: "Kalshi", active: state.layoutMode === "single" && state.provider === "kalshi" },
    { key: "3", label: "Unified", active: state.layoutMode === "unified" },
  ];
  const tabs = [
    { key: "t", label: "Trending", active: state.mode === "trending" },
    { key: "v", label: `Saved ${state.savedMarkets.length}`, active: state.mode === "saved" },
    { key: "u", label: `Recent ${state.recentMarkets.length}`, active: state.mode === "recent" },
    { key: "/", label: "Search", active: state.mode === "search" },
  ];

  const providerText = providers.map((tab) => {
    const tone = tab.active ? `${theme.headerBg}${theme.white}` : `${theme.tabIdle}${theme.muted}`;
    return `${tone} ${tab.key}:${tab.label} ${ansi.reset}`;
  }).join(" ");
  const text = tabs.map((tab) => {
    const tone = tab.active ? `${theme.accentBg}${theme.white}` : `${theme.tabIdle}${theme.blue}`;
    return `${tone} ${tab.key}:${tab.label} ${ansi.reset}`;
  }).join(" ");

  writeLine(buffer, row, col, `${providerText}  ${text}`);
}

function renderMarketTable(buffer: string[], row: number, col: number, width: number, height: number, state: AppState): void {
  const theme = getTheme(state);
  const markets =
    state.mode === "search" ? state.searchResults :
    state.mode === "saved" ? state.savedMarkets :
    state.mode === "recent" ? state.recentMarkets :
    state.trendingMarkets;
  const title =
    state.mode === "search" ? "Markets: Search" :
    state.mode === "saved" ? "Markets: Saved" :
    state.mode === "recent" ? "Markets: Recent" :
    "Markets: Trending";
  panelTop(theme, buffer, row, col, width, title);
  const usableRows = Math.max(2, height - 2);
  const dataRows = usableRows - 1;
  const start = Math.max(0, state.selectedIndex - Math.floor(dataRows / 2));
  const page = markets.slice(start, start + dataRows);

  const questionWidth = Math.max(10, width - 27);
  const columns = `${theme.muted}${truncate("Question", questionWidth)} ${"Flg".padStart(3, " ")} ${"Px".padStart(6, " ")} ${"Vol24".padStart(7, " ")} ${"End".padStart(6, " ")}${ansi.reset}`;
  writeLine(buffer, row + 1, col, `${theme.border}│${theme.lineFill}${columns.padEnd(width - 2, " ")}${ansi.reset}${theme.border}│`);

  for (let offset = 0; offset < dataRows; offset += 1) {
    const market = page[offset];
    const currentRow = row + 2 + offset;
    if (!market) {
      panelBodyLine(theme, buffer, currentRow, col, width, "");
      continue;
    }

    const actualIndex = start + offset;
    const outcome = market.outcomes[0];
    const volume = truncate(formatMoney(market.volume24hr), 7);
    const date = truncate(formatDate(market.endDate), 6);
    const price = truncate(formatPrice(outcome?.price ?? null), 6);
    const flags = actualIndex === state.selectedIndex
      ? `${isSaved(state, market.id) ? "S" : "."}${isRecent(state, market.id) ? "R" : "."}`
      : `${isSaved(state, market.id) ? `${theme.gold}S${ansi.reset}` : "."}${isRecent(state, market.id) ? `${theme.magenta}R${ansi.reset}` : "."}`;
    const marker = actualIndex === state.selectedIndex ? "›" : " ";
    const text = `${marker} ${truncate(market.question, questionWidth)} ${flags.padStart(3, " ")} ${price.padStart(6, " ")} ${volume.padStart(7, " ")} ${date.padStart(6, " ")}`;
    const styled = actualIndex === state.selectedIndex
      ? `${theme.selectedBg}${theme.selectedFg}${fitAnsi(text, width - 2)}`
      : `${fitAnsi(`${theme.white}${text}${ansi.reset}`, width - 2)}`;
    writeLine(buffer, currentRow, col, `${theme.border}│${styled}${theme.border}│`);
  }

  panelBottom(theme, buffer, row + height - 1, col, width);
}

function renderPanelTable(
  buffer: string[],
  row: number,
  col: number,
  width: number,
  height: number,
  panel: ProviderPanelState,
  focused: boolean,
  savedIds: Set<string>,
  recentIds: Set<string>,
): void {
  const theme = getThemeForProvider(panel.provider);
  const title = `${providerLabel(panel.provider)}${focused ? " • focus" : ""}`;
  panelTop(theme, buffer, row, col, width, title);
  const usableRows = Math.max(2, height - 2);
  const dataRows = usableRows - 1;
  const start = Math.max(0, panel.selectedIndex - Math.floor(dataRows / 2));
  const page = panel.markets.slice(start, start + dataRows);
  const questionWidth = Math.max(10, width - 27);
  const columns = `${theme.muted}${truncate("Question", questionWidth)} ${"Flg".padStart(3, " ")} ${"Px".padStart(6, " ")} ${"Vol24".padStart(7, " ")} ${"End".padStart(6, " ")}${ansi.reset}`;
  writeLine(buffer, row + 1, col, `${theme.border}│${theme.lineFill}${columns.padEnd(width - 2, " ")}${ansi.reset}${theme.border}│`);

  for (let offset = 0; offset < dataRows; offset += 1) {
    const market = page[offset];
    const currentRow = row + 2 + offset;
    if (!market) {
      panelBodyLine(theme, buffer, currentRow, col, width, "");
      continue;
    }

    const actualIndex = start + offset;
    const outcome = market.outcomes[panel.selectedOutcomeIndex] ?? market.outcomes[0];
    const volume = truncate(formatMoney(market.volume24hr), 7);
    const date = truncate(formatDate(market.endDate), 6);
    const price = truncate(formatPrice(outcome?.price ?? null), 6);
    const flags = actualIndex === panel.selectedIndex
      ? `${savedIds.has(market.id) ? "S" : "."}${recentIds.has(market.id) ? "R" : "."}`
      : `${savedIds.has(market.id) ? `${theme.gold}S${ansi.reset}` : "."}${recentIds.has(market.id) ? `${theme.magenta}R${ansi.reset}` : "."}`;
    const marker = actualIndex === panel.selectedIndex ? "›" : " ";
    const text = `${marker} ${truncate(market.question, questionWidth)} ${flags.padStart(3, " ")} ${price.padStart(6, " ")} ${volume.padStart(7, " ")} ${date.padStart(6, " ")}`;
    const styled = actualIndex === panel.selectedIndex
      ? `${theme.selectedBg}${focused ? theme.white : theme.selectedFg}${fitAnsi(text, width - 2)}`
      : `${theme.lineFill}${fitAnsi(`${theme.white}${text}${ansi.reset}`, width - 2)}`;
    writeLine(buffer, currentRow, col, `${theme.border}│${styled}${ansi.reset}${theme.border}│`);
  }

  panelBottom(theme, buffer, row + height - 1, col, width);
}

function chartBounds(candles: Candle[]): { min: number; max: number } {
  if (candles.length === 0) {
    return { min: 0, max: 1 };
  }

  let min = candles[0].low;
  let max = candles[0].high;
  for (const candle of candles) {
    min = Math.min(min, candle.low);
    max = Math.max(max, candle.high);
  }

  if (max === min) {
    max += 0.01;
    min -= 0.01;
  }

  return { min, max };
}

function renderChart(buffer: string[], row: number, col: number, width: number, height: number, state: AppState): void {
  const theme = getTheme(state);
  panelTop(theme, buffer, row, col, width, `Chart ${state.range} ${state.loadingChart ? "· loading" : ""}`);
  const chartHeight = Math.max(4, height - 4);
  const chartWidth = Math.max(8, width - 10);
  const market = selectedMarket(state);
  const candles = state.candles.slice(-chartWidth);
  const { min, max } = chartBounds(candles);
  const priceToY = (price: number) => {
    const ratio = (price - min) / (max - min);
    return row + 1 + chartHeight - 1 - Math.round(ratio * (chartHeight - 1));
  };

  for (let index = 0; index < chartHeight; index += 1) {
    const labelPrice = max - ((max - min) * index) / Math.max(1, chartHeight - 1);
    const label = formatPrice(labelPrice).padStart(7, " ");
    panelBodyLine(theme, buffer, row + 1 + index, col, width, "");
    writeLine(buffer, row + 1 + index, col + 1, `${theme.muted}${label}${ansi.reset}`);
    if (index % 2 === 0) {
      writeLine(buffer, row + 1 + index, col + 9, `${theme.grid}${repeat("·", Math.max(0, width - 11))}${ansi.reset}`);
    }
  }

  for (let index = 0; index < candles.length; index += 1) {
    const candle = candles[index];
    const x = col + 9 + index;
    const highY = priceToY(candle.high);
    const lowY = priceToY(candle.low);
    const openY = priceToY(candle.open);
    const closeY = priceToY(candle.close);
    const bullish = candle.close >= candle.open;
    const tone = bullish ? theme.green : theme.red;

    for (let y = highY; y <= lowY; y += 1) {
      writeLine(buffer, y, x, `${tone}│`);
    }

    const bodyTop = Math.min(openY, closeY);
    const bodyBottom = Math.max(openY, closeY);
    for (let y = bodyTop; y <= bodyBottom; y += 1) {
      writeLine(buffer, y, x, `${tone}█`);
    }
  }

  const detailRow = row + chartHeight + 1;
  const lastCandle = candles[candles.length - 1] ?? null;
  const detail = market && lastCandle
    ? `Outcome ${state.selectedOutcomeIndex + 1}/${market.outcomes.length}  O ${formatPrice(lastCandle.open)}  H ${formatPrice(lastCandle.high)}  L ${formatPrice(lastCandle.low)}  C ${formatPrice(lastCandle.close)}`
    : "No chart data available for this outcome.";
  panelBodyLine(theme, buffer, detailRow, col, width, detail);
  panelBottom(theme, buffer, row + height - 1, col, width);
}

function renderDetails(buffer: string[], row: number, col: number, width: number, height: number, state: AppState): void {
  const theme = getTheme(state);
  const market = selectedMarket(state);
  panelTop(theme, buffer, row, col, width, "Market Detail");
  const lines = market
    ? [
        `${theme.white}${truncate(market.question, width - 4)}${ansi.reset}`,
        `${theme.muted}${truncate(market.eventTitle ?? market.seriesTitle ?? providerLabel(market.provider), width - 4)}${ansi.reset}`,
        `Ends ${formatDate(market.endDate)}   Vol24 ${formatMoney(market.volume24hr)}   Liquidity ${formatMoney(market.liquidity)}`,
        `Bid ${formatPrice(market.bestBid)}   Ask ${formatPrice(market.bestAsk)}   Last ${formatPrice(market.lastTradePrice)}`,
        `1d ${formatPercent(market.oneDayPriceChange)}   Symbol ${truncate(market.symbol, Math.max(8, width - 28))}`,
        `Outcome ${state.selectedOutcomeIndex + 1}: ${market.outcomes[state.selectedOutcomeIndex]?.name ?? "-"}   Saved ${isSaved(state, market.id) ? "yes" : "no"}   Recent ${isRecent(state, market.id) ? "yes" : "no"}`,
        `Updated ${formatDateTime(state.chartPoints[state.chartPoints.length - 1]?.timestamp ?? null)}   Store ${truncate(state.storagePath, Math.max(12, width - 28))}`,
        `${theme.cyan}${truncate(state.liveStatusMessage || "Live feed inactive", width - 4)}${ansi.reset}`,
      ]
    : ["No market selected."];

  const bodyRows = Math.max(1, height - 2);
  for (let index = 0; index < bodyRows; index += 1) {
    panelBodyLine(theme, buffer, row + 1 + index, col, width, lines[index] ?? "");
  }
  panelBottom(theme, buffer, row + height - 1, col, width);
}

function renderPanelChart(
  buffer: string[],
  row: number,
  col: number,
  width: number,
  height: number,
  panel: ProviderPanelState,
): void {
  const theme = getThemeForProvider(panel.provider);
  panelTop(theme, buffer, row, col, width, `Chart ${panel.loadingChart ? "· loading" : ""}`);
  const chartHeight = Math.max(4, height - 4);
  const chartWidth = Math.max(8, width - 10);
  const market = selectedMarketFromPanel(panel);
  const candles = panel.candles.slice(-chartWidth);
  const { min, max } = chartBounds(candles);
  const priceToY = (price: number) => {
    const ratio = (price - min) / (max - min);
    return row + 1 + chartHeight - 1 - Math.round(ratio * (chartHeight - 1));
  };

  for (let index = 0; index < chartHeight; index += 1) {
    const labelPrice = max - ((max - min) * index) / Math.max(1, chartHeight - 1);
    const label = formatPrice(labelPrice).padStart(7, " ");
    panelBodyLine(theme, buffer, row + 1 + index, col, width, "");
    writeLine(buffer, row + 1 + index, col + 1, `${theme.muted}${label}${ansi.reset}`);
    if (index % 2 === 0) {
      writeLine(buffer, row + 1 + index, col + 9, `${theme.grid}${repeat("·", Math.max(0, width - 11))}${ansi.reset}`);
    }
  }

  for (let index = 0; index < candles.length; index += 1) {
    const candle = candles[index];
    const x = col + 9 + index;
    const highY = priceToY(candle.high);
    const lowY = priceToY(candle.low);
    const openY = priceToY(candle.open);
    const closeY = priceToY(candle.close);
    const bullish = candle.close >= candle.open;
    const tone = bullish ? theme.green : theme.red;

    for (let y = highY; y <= lowY; y += 1) {
      writeLine(buffer, y, x, `${tone}│`);
    }

    const bodyTop = Math.min(openY, closeY);
    const bodyBottom = Math.max(openY, closeY);
    for (let y = bodyTop; y <= bodyBottom; y += 1) {
      writeLine(buffer, y, x, `${tone}█`);
    }
  }

  const detailRow = row + chartHeight + 1;
  const lastCandle = candles[candles.length - 1] ?? null;
  const detail = market && lastCandle
    ? `Outcome ${panel.selectedOutcomeIndex + 1}/${market.outcomes.length}  O ${formatPrice(lastCandle.open)}  H ${formatPrice(lastCandle.high)}  L ${formatPrice(lastCandle.low)}  C ${formatPrice(lastCandle.close)}`
    : "No chart data available for this outcome.";
  panelBodyLine(theme, buffer, detailRow, col, width, detail);
  panelBottom(theme, buffer, row + height - 1, col, width);
}

function renderPanelDetails(
  buffer: string[],
  row: number,
  col: number,
  width: number,
  height: number,
  panel: ProviderPanelState,
  savedIds: Set<string>,
  recentIds: Set<string>,
): void {
  const theme = getThemeForProvider(panel.provider);
  const market = selectedMarketFromPanel(panel);
  panelTop(theme, buffer, row, col, width, "Market Detail");
  const lines = market
    ? [
        `${theme.white}${truncate(market.question, width - 4)}${ansi.reset}`,
        `${theme.muted}${truncate(market.eventTitle ?? market.seriesTitle ?? providerLabel(panel.provider), width - 4)}${ansi.reset}`,
        `Ends ${formatDate(market.endDate)}   Vol24 ${formatMoney(market.volume24hr)}   Liquidity ${formatMoney(market.liquidity)}`,
        `Bid ${formatPrice(market.bestBid)}   Ask ${formatPrice(market.bestAsk)}   Last ${formatPrice(market.lastTradePrice)}`,
        `1d ${formatPercent(market.oneDayPriceChange)}   Symbol ${truncate(market.symbol, Math.max(8, width - 28))}`,
        `Outcome ${panel.selectedOutcomeIndex + 1}: ${market.outcomes[panel.selectedOutcomeIndex]?.name ?? "-"}   Saved ${savedIds.has(market.id) ? "yes" : "no"}   Recent ${recentIds.has(market.id) ? "yes" : "no"}`,
        `Updated ${formatDateTime(panel.chartPoints[panel.chartPoints.length - 1]?.timestamp ?? null)}   ${providerLabel(panel.provider)} feed`,
        `${theme.cyan}${truncate(panel.liveStatusMessage || "Live feed inactive", width - 4)}${ansi.reset}`,
      ]
    : ["No market selected."];

  const bodyRows = Math.max(1, height - 2);
  for (let index = 0; index < bodyRows; index += 1) {
    panelBodyLine(theme, buffer, row + 1 + index, col, width, lines[index] ?? "");
  }
  panelBottom(theme, buffer, row + height - 1, col, width);
}

function renderFooter(buffer: string[], row: number, width: number, state: AppState): void {
  const theme = getTheme(state);
  const statusTone = state.errorMessage ? theme.red : theme.yellow;
  const status = state.errorMessage || state.statusMessage;
  const controls = state.layoutMode === "unified"
    ? "1 polymarket   2 kalshi   3 unified   h/l focus   j/k move   o outcome   [ ] range   f save"
    : "1 polymarket   2 kalshi   3 unified   t trending   v saved   u recent   f save   / search   j/k move";
  writeLine(buffer, row, 1, `${theme.panel}${repeat(" ", width)}${ansi.reset}`);
  writeLine(buffer, row, 2, `${theme.white}${truncate(controls, width - 2)}${ansi.reset}`);
  writeLine(buffer, row + 1, 1, `${theme.panel}${repeat(" ", width)}${ansi.reset}`);
  writeLine(buffer, row + 1, 2, `${statusTone}${truncate(status, width - 2)}${ansi.reset}`);
}

function renderHelp(buffer: string[], width: number, height: number): void {
  const theme = getThemeForProvider("polymarket");
  const lines = [
    "Move with j/k or up/down arrows.",
    "Use h/l or left/right to switch unified focus.",
    "Press / to focus search, then type and hit Enter.",
    "Selection previews the chart immediately and feeds recents.",
    "Press 1 or 2 to switch to a single provider.",
    "Press 3 to return to unified split mode.",
    "Press f to save or unsave the selected market.",
    "Press t, v, or u to switch between trending, saved, and recent lists.",
    "Press o to switch outcomes for the selected market.",
    "Use [ and ] to change the chart time window.",
    "Press r to refresh markets and chart.",
    "Press Esc to leave search and clear errors.",
    "Press q to quit.",
  ];
  const boxWidth = Math.min(64, width - 6);
  const boxHeight = Math.min(height - 4, lines.length + 2);
  const row = Math.max(3, Math.floor((height - boxHeight) / 2));
  const col = Math.max(3, Math.floor((width - boxWidth) / 2));
  panelTop(theme, buffer, row, col, boxWidth, "Help");
  for (let index = 0; index < boxHeight - 2; index += 1) {
    panelBodyLine(theme, buffer, row + 1 + index, col, boxWidth, lines[index] ?? "");
  }
  panelBottom(theme, buffer, row + boxHeight - 1, col, boxWidth);
}

function renderUnified(buffer: string[], width: number, height: number, state: AppState): void {
  const topOffset = 4;
  const footerHeight = 2;
  const footerTop = height - footerHeight + 1;
  const contentHeight = Math.max(18, footerTop - topOffset);
  const paneWidth = Math.max(40, Math.floor((width - 3) / 2));
  const gap = 1;
  const dividerCol = paneWidth + 1;
  const tableHeight = Math.max(8, Math.floor(contentHeight * 0.38));
  const lowerHeight = Math.max(11, contentHeight - tableHeight - gap);
  const detailHeight = Math.max(5, Math.floor(lowerHeight * 0.36));
  const chartHeight = Math.max(6, lowerHeight - detailHeight - gap);
  const savedIds = new Set(state.savedMarketIds);
  const recentIds = new Set(state.recentMarketIds);
  const focusedTheme = getThemeForProvider(state.unifiedFocus);
  const secondaryTheme = getThemeForProvider(state.unifiedFocus === "polymarket" ? "kalshi" : "polymarket");
  const focusBadge = `${focusedTheme.accentBg}${focusedTheme.white} Focus ${providerLabel(state.unifiedFocus)} ${ansi.reset}`;

  renderHeader(buffer, width, state);
  writeLine(
    buffer,
    3,
    1,
    `${getThemeForProvider("polymarket").accent}Polymarket${ansi.reset}${getTheme(state).muted} left${ansi.reset}  ${focusBadge}  ${secondaryTheme.accent}Kalshi${ansi.reset}${getTheme(state).muted} right${ansi.reset}`,
  );
  renderUnifiedDivider(buffer, topOffset, footerTop - topOffset, dividerCol, state.unifiedFocus);

  renderPanelTable(buffer, topOffset, 1, paneWidth, tableHeight, state.unifiedPanels.polymarket, state.unifiedFocus === "polymarket", savedIds, recentIds);
  renderPanelTable(buffer, topOffset, paneWidth + gap + 1, paneWidth, tableHeight, state.unifiedPanels.kalshi, state.unifiedFocus === "kalshi", savedIds, recentIds);

  const lowerTop = topOffset + tableHeight + 1;
  renderPanelChart(buffer, lowerTop, 1, paneWidth, chartHeight, state.unifiedPanels.polymarket);
  renderPanelChart(buffer, lowerTop, paneWidth + gap + 1, paneWidth, chartHeight, state.unifiedPanels.kalshi);
  renderPanelDetails(buffer, lowerTop + chartHeight + 1, 1, paneWidth, detailHeight, state.unifiedPanels.polymarket, savedIds, recentIds);
  renderPanelDetails(buffer, lowerTop + chartHeight + 1, paneWidth + gap + 1, paneWidth, detailHeight, state.unifiedPanels.kalshi, savedIds, recentIds);
  renderFooter(buffer, footerTop, width, state);
}

export function render(state: AppState): string {
  const width = Math.max(80, process.stdout.columns || 80);
  const height = Math.max(28, process.stdout.rows || 28);
  const buffer: string[] = [ansi.hideCursor, ansi.clear];

  if (state.layoutMode === "unified") {
    renderUnified(buffer, width, height, state);
    if (state.helpVisible) {
      renderHelp(buffer, width, height);
    }
    buffer.push(moveTo(height, width), ansi.reset);
    return buffer.join("");
  }

  const leftWidth = Math.max(34, Math.floor(width * 0.42));
  const rightWidth = width - leftWidth - 2;
  const topOffset = 4;
  const footerHeight = 2;
  const contentHeight = height - topOffset - footerHeight - 1;
  const chartHeight = Math.max(10, Math.floor(contentHeight * 0.62));
  const detailHeight = Math.max(6, contentHeight - chartHeight - 1);

  renderHeader(buffer, width, state);
  renderSearch(buffer, 3, 1, leftWidth - 2, state);
  renderModes(buffer, 3, leftWidth + 2, state);
  renderMarketTable(buffer, topOffset, 1, leftWidth, contentHeight, state);
  renderChart(buffer, topOffset, leftWidth + 2, rightWidth, chartHeight, state);
  renderDetails(buffer, topOffset + chartHeight + 1, leftWidth + 2, rightWidth, detailHeight, state);
  renderFooter(buffer, height - footerHeight + 1, width, state);

  if (state.helpVisible) {
    renderHelp(buffer, width, height);
  }

  buffer.push(moveTo(height, width), ansi.reset);
  return buffer.join("");
}
