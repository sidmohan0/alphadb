import { ansi, color, fitAnsi, moveTo, padAnsi, truncate, visibleWidth } from "../lib/ansi.js";
import { formatAgo, formatDate, formatDateTime, formatMoney, formatPercent, formatPrice } from "../lib/format.js";
import { AppState, Candle, MarketSummary } from "../types.js";

const theme = {
  border: color(38, 5, 117),
  muted: color(38, 5, 248),
  panel: color(48, 5, 234),
  headerBg: color(48, 5, 17),
  accent: color(38, 5, 228),
  accentBg: color(48, 5, 25),
  blue: color(38, 5, 81),
  green: color(38, 5, 84),
  red: color(38, 5, 203),
  yellow: color(38, 5, 221),
  magenta: color(38, 5, 213),
  gold: color(38, 5, 220),
  grid: color(38, 5, 238),
  white: color(97),
  selectedFg: color(30),
  selectedBg: color(48, 5, 117),
  inputBg: color(48, 5, 237),
  inputActiveBg: color(48, 5, 26),
};

function writeLine(buffer: string[], row: number, col: number, text: string): void {
  buffer.push(`${moveTo(row, col)}${text}${ansi.reset}`);
}

function repeat(char: string, count: number): string {
  return Array.from({ length: Math.max(0, count) }, () => char).join("");
}

function selectedMarket(state: AppState): MarketSummary | null {
  const list =
    state.mode === "search" ? state.searchResults :
    state.mode === "saved" ? state.savedMarkets :
    state.mode === "recent" ? state.recentMarkets :
    state.trendingMarkets;
  return list[state.selectedIndex] ?? null;
}

function isSaved(state: AppState, marketId: string): boolean {
  return state.savedMarkets.some((market) => market.id === marketId);
}

function isRecent(state: AppState, marketId: string): boolean {
  return state.recentMarkets.some((market) => market.id === marketId);
}

function panelTop(buffer: string[], row: number, col: number, width: number, title: string): void {
  const inner = Math.max(0, width - 2);
  const label = ` ${title} `;
  const left = Math.max(0, Math.floor((inner - label.length) / 2));
  const right = Math.max(0, inner - left - label.length);
  writeLine(buffer, row, col, `${theme.border}┌${repeat("─", left)}${theme.white}${label}${theme.border}${repeat("─", right)}┐`);
}

function panelBottom(buffer: string[], row: number, col: number, width: number): void {
  writeLine(buffer, row, col, `${theme.border}└${repeat("─", Math.max(0, width - 2))}┘`);
}

function panelBodyLine(buffer: string[], row: number, col: number, width: number, text = ""): void {
  const inner = Math.max(0, width - 2);
  writeLine(buffer, row, col, `${theme.border}│${ansi.reset}${fitAnsi(text, inner)}${theme.border}│`);
}

function renderHeader(buffer: string[], width: number, state: AppState): void {
  const market = selectedMarket(state);
  writeLine(buffer, 1, 1, `${theme.headerBg}${" ".repeat(width)}${ansi.reset}`);
  writeLine(buffer, 2, 1, `${theme.headerBg}${" ".repeat(width)}${ansi.reset}`);
  const left = `${theme.white}${theme.headerBg} AlphaDB ${ansi.reset}${theme.accent}${theme.headerBg} Polymarket ANSI ${ansi.reset}`;
  const middle = `${theme.blue}${theme.headerBg}${state.mode === "search" ? " Search results " : state.mode === "saved" ? " Saved markets " : state.mode === "recent" ? " Recent markets " : " Trending by 24h volume "}${ansi.reset}`;
  const right = `${theme.muted}${theme.headerBg} markets ${formatAgo(state.lastMarketRefreshAt)}  chart ${formatAgo(state.lastChartRefreshAt)} ${ansi.reset}`;
  const full = `${left}  ${middle}`;
  const rightWidth = visibleWidth(right);
  writeLine(buffer, 1, 1, padAnsi(full, Math.max(0, width - rightWidth - 1)));
  writeLine(buffer, 1, Math.max(1, width - rightWidth + 1), right);
  if (market) {
    writeLine(buffer, 2, 1, `${theme.muted}${truncate(market.question, width)}${ansi.reset}`);
  }
}

function renderSearch(buffer: string[], row: number, col: number, width: number, state: AppState): void {
  const label = state.focused === "search" ? `${theme.inputActiveBg}${theme.white}` : `${theme.inputBg}${theme.white}`;
  const prompt = `${theme.accent}Search${ansi.reset}`;
  const bodyWidth = Math.max(1, width - 10);
  const body = truncate(state.query || "type / to search markets", bodyWidth);
  writeLine(buffer, row, col, `${prompt} ${label} ${body} ${ansi.reset}`);
}

function renderModes(buffer: string[], row: number, col: number, state: AppState): void {
  const tabs = [
    { key: "t", label: "Trending", active: state.mode === "trending" },
    { key: "v", label: `Saved ${state.savedMarkets.length}`, active: state.mode === "saved" },
    { key: "u", label: `Recent ${state.recentMarkets.length}`, active: state.mode === "recent" },
    { key: "/", label: "Search", active: state.mode === "search" },
  ];

  const text = tabs.map((tab) => {
    const tone = tab.active ? `${theme.accentBg}${theme.white}` : `${theme.blue}`;
    return `${tone} ${tab.key}:${tab.label} ${ansi.reset}`;
  }).join(" ");

  writeLine(buffer, row, col, text);
}

function renderMarketTable(buffer: string[], row: number, col: number, width: number, height: number, state: AppState): void {
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
  panelTop(buffer, row, col, width, title);
  const usableRows = Math.max(2, height - 2);
  const dataRows = usableRows - 1;
  const start = Math.max(0, state.selectedIndex - Math.floor(dataRows / 2));
  const page = markets.slice(start, start + dataRows);

  const questionWidth = Math.max(10, width - 27);
  const columns = `${theme.muted}${truncate("Question", questionWidth)} ${"Flg".padStart(3, " ")} ${"Price".padStart(6, " ")} ${"Vol24".padStart(7, " ")} ${"End".padStart(6, " ")}${ansi.reset}`;
  writeLine(buffer, row + 1, col, `${theme.border}│${columns.padEnd(width - 2, " ")}${theme.border}│`);

  for (let offset = 0; offset < dataRows; offset += 1) {
    const market = page[offset];
    const currentRow = row + 2 + offset;
    if (!market) {
      panelBodyLine(buffer, currentRow, col, width, "");
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

  panelBottom(buffer, row + height - 1, col, width);
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
  panelTop(buffer, row, col, width, `Chart ${state.range} ${state.loadingChart ? "· loading" : ""}`);
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
    panelBodyLine(buffer, row + 1 + index, col, width, "");
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
  panelBodyLine(buffer, detailRow, col, width, detail);
  panelBottom(buffer, row + height - 1, col, width);
}

function renderDetails(buffer: string[], row: number, col: number, width: number, height: number, state: AppState): void {
  const market = selectedMarket(state);
  panelTop(buffer, row, col, width, "Market Detail");
  const lines = market
    ? [
        `${theme.white}${truncate(market.question, width - 4)}${ansi.reset}`,
        `${theme.muted}${truncate(market.eventTitle ?? market.seriesTitle ?? "Polymarket", width - 4)}${ansi.reset}`,
        `Ends ${formatDate(market.endDate)}   Vol24 ${formatMoney(market.volume24hr)}   Liquidity ${formatMoney(market.liquidity)}`,
        `Bid ${formatPrice(market.bestBid)}   Ask ${formatPrice(market.bestAsk)}   Last ${formatPrice(market.lastTradePrice)}`,
        `1d ${formatPercent(market.oneDayPriceChange)}   Condition ${truncate(market.conditionId, Math.max(8, width - 20))}`,
        `Outcome ${state.selectedOutcomeIndex + 1}: ${market.outcomes[state.selectedOutcomeIndex]?.name ?? "-"}   Saved ${isSaved(state, market.id) ? "yes" : "no"}   Recent ${isRecent(state, market.id) ? "yes" : "no"}`,
        `Updated ${formatDateTime(state.chartPoints[state.chartPoints.length - 1]?.timestamp ?? null)}   Store ${truncate(state.storagePath, Math.max(12, width - 28))}`,
      ]
    : ["No market selected."];

  const bodyRows = Math.max(1, height - 2);
  for (let index = 0; index < bodyRows; index += 1) {
    panelBodyLine(buffer, row + 1 + index, col, width, lines[index] ?? "");
  }
  panelBottom(buffer, row + height - 1, col, width);
}

function renderFooter(buffer: string[], row: number, width: number, state: AppState): void {
  const statusTone = state.errorMessage ? theme.red : theme.yellow;
  const status = state.errorMessage || state.statusMessage;
  const controls = "t trending   v saved   u recent   f save   / search   j/k move   o outcome   [ ] range";
  writeLine(buffer, row, 1, `${theme.panel}${repeat(" ", width)}${ansi.reset}`);
  writeLine(buffer, row, 2, `${theme.white}${truncate(controls, width - 2)}${ansi.reset}`);
  writeLine(buffer, row + 1, 1, `${theme.panel}${repeat(" ", width)}${ansi.reset}`);
  writeLine(buffer, row + 1, 2, `${statusTone}${truncate(status, width - 2)}${ansi.reset}`);
}

function renderHelp(buffer: string[], width: number, height: number): void {
  const boxWidth = Math.min(64, width - 6);
  const boxHeight = 11;
  const row = Math.max(3, Math.floor((height - boxHeight) / 2));
  const col = Math.max(3, Math.floor((width - boxWidth) / 2));
  panelTop(buffer, row, col, boxWidth, "Help");
  const lines = [
    "Move with j/k or arrow keys.",
    "Press / to focus search, then type and hit Enter.",
    "Selection previews the chart immediately and feeds recents.",
    "Press f to save or unsave the selected market.",
    "Press t, v, or u to switch between trending, saved, and recent lists.",
    "Press o to switch outcomes for the selected market.",
    "Use [ and ] to change the chart time window.",
    "Press r to refresh markets and chart.",
    "Press Esc to leave search and clear errors.",
    "Press q to quit.",
  ];
  for (let index = 0; index < boxHeight - 2; index += 1) {
    panelBodyLine(buffer, row + 1 + index, col, boxWidth, lines[index] ?? "");
  }
  panelBottom(buffer, row + boxHeight - 1, col, boxWidth);
}

export function render(state: AppState): string {
  const width = Math.max(80, process.stdout.columns || 80);
  const height = Math.max(28, process.stdout.rows || 28);
  const buffer: string[] = [ansi.hideCursor, ansi.clear];
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
