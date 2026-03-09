import { Candle, MarketSummary, OutcomeToken, PricePoint, RangeKey } from "../types.js";
import { rankMarkets } from "../lib/fuzzy.js";

const KALSHI_BASE_URL = process.env.KALSHI_API_BASE_URL?.trim() || "https://api.elections.kalshi.com/trade-api/v2";

type JsonRecord = Record<string, unknown>;

interface EventContext {
  title: string | null;
  category: string | null;
  seriesTicker: string | null;
}

interface SearchMarketsOptions {
  localCandidates?: MarketSummary[];
  savedIds?: Set<string>;
  recentIds?: Set<string>;
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

function toDollarNumber(value: unknown): number {
  return toNumber(value);
}

function toNullableDollarNumber(value: unknown): number | null {
  return toNullableNumber(value);
}

function yesNoOutcomes(record: JsonRecord): OutcomeToken[] {
  const yesPrice = toNullableDollarNumber(record.last_price_dollars ?? record.yes_bid_dollars ?? record.yes_ask_dollars);
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
    return `${title} — ${yesSubtitle}`;
  }

  if (context?.title && context.title !== title && !title.toLowerCase().includes(context.title.toLowerCase())) {
    return `${context.title} — ${title}`;
  }

  return title;
}

function normalizeMarket(record: JsonRecord, context?: EventContext): MarketSummary {
  const ticker = String(record.ticker ?? "");
  const last = toNullableDollarNumber(record.last_price_dollars);
  const previous = toNullableDollarNumber(record.previous_price_dollars);
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
    liquidity: toDollarNumber(record.liquidity_dollars ?? record.liquidity),
    volume24hr: toDollarNumber(record.volume_24h_dollars ?? record.volume_24h),
    volumeTotal: toDollarNumber(record.volume_dollars ?? record.volume),
    bestBid: toNullableDollarNumber(record.yes_bid_dollars),
    bestAsk: toNullableDollarNumber(record.yes_ask_dollars),
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
      "User-Agent": "alphadb-polymarket-ansi-tui",
    },
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}`);
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

export async function searchKalshiMarkets(
  query: string,
  limit = 16,
  options: SearchMarketsOptions = {},
): Promise<MarketSummary[]> {
  const trimmed = query.trim();
  if (!trimmed) {
    return [];
  }

  const markets = new Map<string, MarketSummary>();
  const remote = await fetchOpenMarkets(4000);
  for (const market of remote) {
    markets.set(market.id, market);
  }

  for (const market of options.localCandidates ?? []) {
    if (!markets.has(market.id)) {
      markets.set(market.id, market);
    }
  }

  return rankMarkets(trimmed, [...markets.values()], {
    limit,
    remoteIds: new Set(remote.map((market) => market.id)),
    savedIds: options.savedIds,
    recentIds: options.recentIds,
  });
}

function midpoint(openBid: unknown, openAsk: unknown): number | null {
  const bid = toNullableDollarNumber(openBid);
  const ask = toNullableDollarNumber(openAsk);

  if (bid !== null && ask !== null) {
    return (bid + ask) / 2;
  }

  return bid ?? ask ?? null;
}

function toKalshiPointPrice(candle: JsonRecord): number | null {
  const previous = toNullableDollarNumber(candle.previous_price_dollars);
  const yesBid = candle.yes_bid && typeof candle.yes_bid === "object" ? (candle.yes_bid as JsonRecord) : {};
  const yesAsk = candle.yes_ask && typeof candle.yes_ask === "object" ? (candle.yes_ask as JsonRecord) : {};
  return midpoint(yesBid.close_dollars, yesAsk.close_dollars) ?? previous;
}

export async function fetchKalshiMarketHistory(market: MarketSummary, range: RangeKey): Promise<PricePoint[]> {
  const now = Math.floor(Date.now() / 1000);
  const start = now - RANGE_TO_WINDOW_SECONDS[range];
  const periodInterval = RANGE_TO_CANDLE_MINUTES[range];
  const url = new URL(`${KALSHI_BASE_URL}/markets/candlesticks`);
  url.searchParams.set("market_tickers", market.symbol);
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

export function buildKalshiCandles(points: PricePoint[], targetCount: number): Candle[] {
  if (points.length === 0 || targetCount <= 0) {
    return [];
  }

  if (points.length === 1) {
    const point = points[0];
    return [{
      startTime: point.timestamp,
      endTime: point.timestamp,
      open: point.price,
      high: point.price,
      low: point.price,
      close: point.price,
    }];
  }

  const bucketSize = Math.max(1, Math.ceil(points.length / targetCount));
  const candles: Candle[] = [];

  for (let index = 0; index < points.length; index += bucketSize) {
    const bucket = points.slice(index, index + bucketSize);
    candles.push({
      startTime: bucket[0].timestamp,
      endTime: bucket[bucket.length - 1].timestamp,
      open: bucket[0].price,
      high: Math.max(...bucket.map((point) => point.price)),
      low: Math.min(...bucket.map((point) => point.price)),
      close: bucket[bucket.length - 1].price,
    });
  }

  return candles;
}

export function applyKalshiTickerUpdate(market: MarketSummary, msg: JsonRecord): MarketSummary {
  const price = toNullableDollarNumber(msg.price_dollars);
  const yesBid = toNullableDollarNumber(msg.yes_bid_dollars);
  const yesAsk = toNullableDollarNumber(msg.yes_ask_dollars);
  const outcomes = market.outcomes.map((outcome, index) => {
    if (index === 0) {
      return { ...outcome, price };
    }

    return { ...outcome, price: price === null ? null : Math.max(0, 1 - price) };
  });

  return {
    ...market,
    bestBid: yesBid,
    bestAsk: yesAsk,
    lastTradePrice: price,
    volumeTotal: toNumber(msg.dollar_volume) || market.volumeTotal,
    outcomes,
  };
}
