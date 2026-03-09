import { MarketSummary, OutcomeToken, PricePoint, RangeKey } from "../types";

const KALSHI_BASE_URL = process.env.KALSHI_API_BASE_URL?.trim() || "https://api.elections.kalshi.com/trade-api/v2";

type JsonRecord = Record<string, unknown>;

interface EventContext {
  title: string | null;
  category: string | null;
  seriesTicker: string | null;
}

const RANGE_TO_CANDLE_MINUTES: Record<RangeKey, number> = {
  "6h": 1,
  "24h": 60,
  "7d": 60,
  "30d": 1440,
  max: 1440,
};

const RANGE_TO_WINDOW_SECONDS: Record<RangeKey, number> = {
  "6h": 6 * 60 * 60,
  "24h": 24 * 60 * 60,
  "7d": 7 * 24 * 60 * 60,
  "30d": 30 * 24 * 60 * 60,
  max: 120 * 24 * 60 * 60,
};

const MARKET_CACHE_TTL_MS = 60_000;

let marketCache:
  | {
      expiresAt: number;
      markets: MarketSummary[];
    }
  | null = null;

function isMultivariateMarket(market: MarketSummary): boolean {
  return market.symbol.startsWith("KXMVE");
}

function toStringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function toNumber(value: unknown): number {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : 0;
  }

  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  return 0;
}

function toNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function yesNoOutcomes(record: JsonRecord): OutcomeToken[] {
  const yesPrice = toNullableNumber(record.last_price_dollars ?? record.yes_bid_dollars ?? record.yes_ask_dollars);
  const ticker = String(record.ticker ?? "");
  return [
    {
      name: "Yes",
      tokenId: `${ticker}:yes`,
      price: yesPrice,
    },
    {
      name: "No",
      tokenId: `${ticker}:no`,
      price: yesPrice === null ? null : Math.max(0, 1 - yesPrice),
    },
  ];
}

function buildQuestion(record: JsonRecord, context?: EventContext): string {
  const title = String(record.title ?? "Untitled market");
  const yesSubtitle = toStringValue(record.yes_sub_title);

  if (yesSubtitle && !title.toLowerCase().includes(yesSubtitle.toLowerCase())) {
    return `${title} - ${yesSubtitle}`;
  }

  if (context?.title && context.title !== title && !title.toLowerCase().includes(context.title.toLowerCase())) {
    return `${context.title} - ${title}`;
  }

  return title;
}

function normalizeMarket(record: JsonRecord, context?: EventContext): MarketSummary {
  const ticker = String(record.ticker ?? "");
  const last = toNullableNumber(record.last_price_dollars);
  const previous = toNullableNumber(record.previous_price_dollars);
  const oneDayChange =
    last !== null && previous !== null && previous > 0 ? ((last - previous) / previous) * 100 : null;

  return {
    id: `kalshi:${ticker}`,
    provider: "kalshi",
    symbol: ticker,
    question: buildQuestion(record, context),
    conditionId: ticker,
    slug: ticker.toLowerCase(),
    endDate: toStringValue(record.close_time ?? record.expiration_time ?? record.expected_expiration_time),
    liquidity: toNumber(record.liquidity_dollars ?? record.liquidity),
    volume24hr: toNumber(record.volume_24h_dollars ?? record.volume_24h),
    volumeTotal: toNumber(record.volume_dollars ?? record.volume),
    bestBid: toNullableNumber(record.yes_bid_dollars),
    bestAsk: toNullableNumber(record.yes_ask_dollars),
    lastTradePrice: last,
    oneDayPriceChange: oneDayChange,
    eventTitle: context?.title ?? toStringValue(record.subtitle),
    seriesTitle: context?.category ?? toStringValue(record.event_ticker) ?? context?.seriesTicker ?? null,
    image: null,
    outcomes: yesNoOutcomes(record),
  };
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
      "User-Agent": "alphadb-platform-api",
    },
  });

  if (!response.ok) {
    const error = new Error(`HTTP ${response.status} for ${url}`) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }

  return response.json() as Promise<T>;
}

async function fetchOpenMarkets(limit: number): Promise<MarketSummary[]> {
  const cached = marketCache;
  if (cached && cached.expiresAt > Date.now() && cached.markets.length >= limit) {
    return cached.markets.slice(0, limit);
  }

  const markets: MarketSummary[] = [];
  let cursor: string | undefined;

  while (markets.length < limit) {
    const url = new URL(`${KALSHI_BASE_URL}/events`);
    url.searchParams.set("status", "open");
    url.searchParams.set("limit", String(Math.min(200, Math.max(25, Math.ceil(limit / 4)))));
    url.searchParams.set("with_nested_markets", "true");
    if (cursor) {
      url.searchParams.set("cursor", cursor);
    }

    const payload = await fetchJson<{
      cursor?: string;
      events?: Array<JsonRecord & { markets?: JsonRecord[] }>;
    }>(url.toString());

    const normalized = (payload.events ?? []).flatMap((event) => {
      const context: EventContext = {
        title: toStringValue(event.title),
        category: toStringValue(event.category),
        seriesTicker: toStringValue(event.series_ticker),
      };

      return (event.markets ?? []).map((market) => normalizeMarket(market, context));
    });

    markets.push(...normalized);

    if (!payload.cursor || normalized.length === 0) {
      break;
    }

    cursor = payload.cursor;
  }

  const deduped = [...new Map(markets.map((market) => [market.id, market])).values()];
  marketCache = {
    expiresAt: Date.now() + MARKET_CACHE_TTL_MS,
    markets: deduped,
  };

  return deduped.slice(0, limit);
}

function scoreSearchMatch(market: MarketSummary, query: string): number {
  const normalizedQuery = query.trim().toLowerCase();
  const haystack = [
    market.symbol,
    market.question,
    market.eventTitle ?? "",
    market.seriesTitle ?? "",
  ].join(" ").toLowerCase();

  if (!haystack.includes(normalizedQuery)) {
    return -1;
  }

  let score = 0;
  if (market.symbol.toLowerCase() === normalizedQuery) {
    score += 200;
  }
  if (market.question.toLowerCase().startsWith(normalizedQuery)) {
    score += 120;
  }
  if (market.question.toLowerCase().includes(normalizedQuery)) {
    score += 80;
  }
  if ((market.eventTitle ?? "").toLowerCase().includes(normalizedQuery)) {
    score += 50;
  }
  if ((market.seriesTitle ?? "").toLowerCase().includes(normalizedQuery)) {
    score += 30;
  }

  score += Math.min(market.volume24hr, 250_000) / 10_000;
  score += Math.min(market.liquidity, 250_000) / 25_000;

  return score;
}

function marketTickerFromRef(marketId: string, outcomeTokenId?: string): string | null {
  if (outcomeTokenId) {
    const [ticker] = outcomeTokenId.split(":");
    if (ticker) {
      return ticker;
    }
  }

  const [, ticker] = marketId.split(":");
  return ticker || null;
}

function midpoint(openBid: unknown, openAsk: unknown): number | null {
  const bid = toNullableNumber(openBid);
  const ask = toNullableNumber(openAsk);

  if (bid !== null && ask !== null) {
    return (bid + ask) / 2;
  }

  return bid ?? ask ?? null;
}

function toKalshiPointPrice(candle: JsonRecord): number | null {
  const previous = toNullableNumber(candle.previous_price_dollars);
  const yesBid = candle.yes_bid && typeof candle.yes_bid === "object" ? (candle.yes_bid as JsonRecord) : {};
  const yesAsk = candle.yes_ask && typeof candle.yes_ask === "object" ? (candle.yes_ask as JsonRecord) : {};
  return midpoint(yesBid.close_dollars, yesAsk.close_dollars) ?? previous;
}

export async function fetchKalshiTrendingMarkets(limit = 24): Promise<MarketSummary[]> {
  const markets = await fetchOpenMarkets(Math.max(limit * 120, 4000));
  return markets
    .sort((left, right) => {
      const leftMulti = isMultivariateMarket(left) ? 1 : 0;
      const rightMulti = isMultivariateMarket(right) ? 1 : 0;
      if (leftMulti !== rightMulti) {
        return leftMulti - rightMulti;
      }

      if (right.volume24hr !== left.volume24hr) {
        return right.volume24hr - left.volume24hr;
      }

      if (right.liquidity !== left.liquidity) {
        return right.liquidity - left.liquidity;
      }

      return left.question.length - right.question.length;
    })
    .slice(0, limit);
}

export async function searchKalshiMarkets(query: string, limit = 24): Promise<MarketSummary[]> {
  const trimmed = query.trim();
  if (!trimmed) {
    return [];
  }

  const markets = await fetchOpenMarkets(4000);
  return markets
    .map((market) => ({ market, score: scoreSearchMatch(market, trimmed) }))
    .filter((entry) => entry.score >= 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, limit)
    .map((entry) => entry.market);
}

export async function fetchKalshiHistory(marketId: string, outcomeTokenId: string | undefined, range: RangeKey): Promise<PricePoint[]> {
  const ticker = marketTickerFromRef(marketId, outcomeTokenId);
  if (!ticker) {
    return [];
  }

  const now = Math.floor(Date.now() / 1000);
  const start = now - RANGE_TO_WINDOW_SECONDS[range];
  const periodInterval = RANGE_TO_CANDLE_MINUTES[range];
  const url = new URL(`${KALSHI_BASE_URL}/markets/candlesticks`);
  url.searchParams.set("market_tickers", ticker);
  url.searchParams.set("start_ts", String(start));
  url.searchParams.set("end_ts", String(now));
  url.searchParams.set("period_interval", String(periodInterval));
  url.searchParams.set("include_latest_before_start", "true");

  const payload = await fetchJson<{
    markets?: Array<{
      market_ticker?: string;
      candlesticks?: JsonRecord[];
    }>;
  }>(url.toString());

  const candles = payload.markets?.[0]?.candlesticks ?? [];
  return candles
    .map((entry) => ({
      timestamp: toNumber(entry.end_period_ts),
      price: toKalshiPointPrice(entry),
    }))
    .filter((entry): entry is PricePoint => entry.timestamp > 0 && entry.price !== null)
    .sort((left, right) => left.timestamp - right.timestamp);
}
