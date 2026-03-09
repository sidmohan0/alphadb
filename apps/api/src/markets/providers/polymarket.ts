import { MarketSummary, OutcomeToken, PricePoint, RangeKey } from "../types";

const GAMMA_BASE_URL = "https://gamma-api.polymarket.com";
const CLOB_BASE_URL = "https://clob.polymarket.com";

type JsonRecord = Record<string, unknown>;

interface SearchEvent {
  title?: string;
  volume24hr?: number;
  markets?: JsonRecord[];
}

const RANGE_WINDOWS: Record<RangeKey, number | null> = {
  "6h": 6 * 60 * 60,
  "24h": 24 * 60 * 60,
  "7d": 7 * 24 * 60 * 60,
  "30d": 30 * 24 * 60 * 60,
  max: null,
};

const FIDELITY_BY_RANGE: Record<RangeKey, number> = {
  "6h": 1,
  "24h": 5,
  "7d": 60,
  "30d": 240,
  max: 1440,
};

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

function toStringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function parseStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry));
  }

  if (typeof value !== "string" || !value.trim()) {
    return [];
  }

  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed) ? parsed.map((entry) => String(entry)) : [];
  } catch {
    return [];
  }
}

function parseOutcomes(record: JsonRecord): OutcomeToken[] {
  const names = parseStringArray(record.outcomes);
  const tokenIds = parseStringArray(record.clobTokenIds);
  const prices = parseStringArray(record.outcomePrices).map((entry) => {
    const parsed = Number(entry);
    return Number.isFinite(parsed) ? parsed : null;
  });

  return names
    .map((name, index) => ({
      name,
      tokenId: tokenIds[index] ?? "",
      price: prices[index] ?? null,
    }))
    .filter((outcome) => outcome.tokenId);
}

function normalizeMarket(record: JsonRecord): MarketSummary {
  const events = Array.isArray(record.events) ? (record.events as JsonRecord[]) : [];
  const firstEvent = events[0];
  const series = Array.isArray(firstEvent?.series) ? (firstEvent?.series as JsonRecord[]) : [];
  const firstSeries = series[0];

  return {
    id: `polymarket:${String(record.id ?? "")}`,
    provider: "polymarket",
    symbol: String(record.slug ?? record.id ?? ""),
    question: String(record.question ?? "Untitled market"),
    conditionId: String(record.conditionId ?? ""),
    slug: String(record.slug ?? ""),
    endDate: toStringValue(record.endDate),
    liquidity: toNumber(record.liquidityNum ?? record.liquidity),
    volume24hr: toNumber(record.volume24hr),
    volumeTotal: toNumber(record.volumeNum ?? record.volume),
    bestBid: toNullableNumber(record.bestBid),
    bestAsk: toNullableNumber(record.bestAsk),
    lastTradePrice: toNullableNumber(record.lastTradePrice),
    oneDayPriceChange: toNullableNumber(record.oneDayPriceChange),
    eventTitle: toStringValue(firstEvent?.title),
    seriesTitle: toStringValue(firstSeries?.title),
    image: toStringValue(record.image) ?? toStringValue(firstEvent?.image),
    outcomes: parseOutcomes(record),
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

export async function fetchPolymarketTrendingMarkets(limit = 24): Promise<MarketSummary[]> {
  const url =
    `${GAMMA_BASE_URL}/markets?closed=false&active=true&limit=${limit}` +
    "&order=volume24hr&ascending=false";

  const rows = await fetchJson<JsonRecord[]>(url);
  return rows.map(normalizeMarket).filter((market) => market.outcomes.length > 0);
}

export async function searchPolymarketMarkets(query: string, limit = 24): Promise<MarketSummary[]> {
  const trimmed = query.trim();
  if (!trimmed) {
    return [];
  }

  const url = `${GAMMA_BASE_URL}/public-search?q=${encodeURIComponent(trimmed)}&limit_per_type=${Math.max(limit, 20)}`;
  const payload = await fetchJson<{ events?: SearchEvent[] }>(url);
  const markets = new Map<string, MarketSummary>();

  for (const event of payload.events ?? []) {
    for (const rawMarket of event.markets ?? []) {
      const normalized = normalizeMarket({
        ...rawMarket,
        events: [{ title: event.title }],
        volume24hr: rawMarket.volume24hr ?? event.volume24hr ?? 0,
      });

      if (normalized.outcomes.length > 0) {
        markets.set(normalized.id, normalized);
      }
    }
  }

  return [...markets.values()]
    .sort((left, right) => right.volume24hr - left.volume24hr)
    .slice(0, limit);
}

export async function fetchPolymarketHistory(outcomeTokenId: string, range: RangeKey): Promise<PricePoint[]> {
  const fidelity = FIDELITY_BY_RANGE[range];
  const url = `${CLOB_BASE_URL}/prices-history?market=${encodeURIComponent(outcomeTokenId)}&interval=max&fidelity=${fidelity}`;
  const payload = await fetchJson<{ history?: Array<{ t?: number; p?: number }> }>(url);

  const points = (payload.history ?? [])
    .map((entry) => ({
      timestamp: Number(entry.t ?? 0),
      price: Number(entry.p ?? 0),
    }))
    .filter((entry) => Number.isFinite(entry.timestamp) && Number.isFinite(entry.price) && entry.timestamp > 0)
    .sort((left, right) => left.timestamp - right.timestamp);

  const windowSeconds = RANGE_WINDOWS[range];
  if (windowSeconds === null || points.length === 0) {
    return points;
  }

  const latest = points[points.length - 1].timestamp;
  return points.filter((point) => point.timestamp >= latest - windowSeconds);
}
