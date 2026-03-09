import os from "node:os";
import path from "node:path";
import { mkdir, readFile, writeFile } from "node:fs/promises";

import { MarketSummary, PersistedMarketSnapshot, PersistentState } from "../types.js";

const RECENT_LIMIT = 24;

let writeQueue = Promise.resolve();

function cloneMarket(market: MarketSummary): MarketSummary {
  return {
    ...market,
    outcomes: market.outcomes.map((outcome) => ({ ...outcome })),
  };
}

function normalizeMarketSummary(value: unknown): MarketSummary | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const raw = value as Partial<MarketSummary>;
  const provider = raw.provider === "kalshi" ? "kalshi" : "polymarket";
  const rawId = typeof raw.id === "string" ? raw.id : "";
  const id = rawId.includes(":") ? rawId : `${provider}:${rawId}`;
  const symbol =
    typeof raw.symbol === "string" && raw.symbol.trim()
      ? raw.symbol
      : provider === "kalshi"
        ? String(raw.conditionId ?? raw.slug ?? raw.id ?? "")
        : String(raw.slug ?? raw.id ?? "");

  return {
    provider,
    id,
    symbol,
    question: String(raw.question ?? "Untitled market"),
    conditionId: String(raw.conditionId ?? ""),
    slug: String(raw.slug ?? ""),
    endDate: typeof raw.endDate === "string" ? raw.endDate : null,
    liquidity: Number(raw.liquidity ?? 0),
    volume24hr: Number(raw.volume24hr ?? 0),
    volumeTotal: Number(raw.volumeTotal ?? 0),
    bestBid: raw.bestBid === null || raw.bestBid === undefined ? null : Number(raw.bestBid),
    bestAsk: raw.bestAsk === null || raw.bestAsk === undefined ? null : Number(raw.bestAsk),
    lastTradePrice: raw.lastTradePrice === null || raw.lastTradePrice === undefined ? null : Number(raw.lastTradePrice),
    oneDayPriceChange: raw.oneDayPriceChange === null || raw.oneDayPriceChange === undefined ? null : Number(raw.oneDayPriceChange),
    eventTitle: typeof raw.eventTitle === "string" ? raw.eventTitle : null,
    seriesTitle: typeof raw.seriesTitle === "string" ? raw.seriesTitle : null,
    image: typeof raw.image === "string" ? raw.image : null,
    outcomes: Array.isArray(raw.outcomes)
      ? raw.outcomes.map((outcome) => ({
          name: String(outcome.name ?? ""),
          tokenId: String(outcome.tokenId ?? ""),
          price: outcome.price === null || outcome.price === undefined ? null : Number(outcome.price),
        }))
      : [],
  };
}

function cloneSnapshot(snapshot: PersistedMarketSnapshot): PersistedMarketSnapshot {
  return {
    market: cloneMarket(snapshot.market),
    savedAt: snapshot.savedAt,
    viewedAt: snapshot.viewedAt,
  };
}

function normalizeSnapshots(value: unknown): PersistedMarketSnapshot[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((entry) => {
    if (!entry || typeof entry !== "object") {
      return [];
    }

    const raw = entry as Partial<PersistedMarketSnapshot>;
    const market = normalizeMarketSummary(raw.market);
    if (!market) {
      return [];
    }

    return [{
      market,
      savedAt: typeof raw.savedAt === "number" ? raw.savedAt : undefined,
      viewedAt: typeof raw.viewedAt === "number" ? raw.viewedAt : Date.now(),
    }];
  });
}

export function getStoragePath(): string {
  if (process.env.ALPHADB_TUI_STATE_PATH?.trim()) {
    return process.env.ALPHADB_TUI_STATE_PATH.trim();
  }

  return path.join(os.homedir(), ".config", "alphadb-tui", "state.json");
}

export async function loadPersistentState(): Promise<{ path: string; state: PersistentState }> {
  const storagePath = getStoragePath();

  try {
    const raw = await readFile(storagePath, "utf8");
    const parsed = JSON.parse(raw) as Partial<PersistentState>;

    return {
      path: storagePath,
      state: {
        savedMarkets: normalizeSnapshots(parsed.savedMarkets),
        recentMarkets: normalizeSnapshots(parsed.recentMarkets),
      },
    };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return {
        path: storagePath,
        state: {
          savedMarkets: [],
          recentMarkets: [],
        },
      };
    }

    throw error;
  }
}

export function queuePersistentStateWrite(state: PersistentState, storagePath: string): void {
  const payload = JSON.stringify(state, null, 2);
  writeQueue = writeQueue.then(async () => {
    await mkdir(path.dirname(storagePath), { recursive: true });
    await writeFile(storagePath, payload, "utf8");
  }).catch(() => undefined);
}

export function mergeMarketsIntoPersistentState(
  state: PersistentState,
  markets: MarketSummary[],
): PersistentState {
  if (markets.length === 0) {
    return state;
  }

  const byId = new Map(markets.map((market) => [market.id, cloneMarket(market)]));
  const merge = (snapshots: PersistedMarketSnapshot[]) =>
    snapshots.map((snapshot) => ({
      ...snapshot,
      market: byId.get(snapshot.market.id) ?? snapshot.market,
    }));

  return {
    savedMarkets: merge(state.savedMarkets),
    recentMarkets: merge(state.recentMarkets),
  };
}

export function touchRecentMarket(state: PersistentState, market: MarketSummary): PersistentState {
  const now = Date.now();
  const filtered = state.recentMarkets.filter((entry) => entry.market.id !== market.id);

  return {
    ...state,
    recentMarkets: [{
      market: cloneMarket(market),
      savedAt: state.savedMarkets.find((entry) => entry.market.id === market.id)?.savedAt,
      viewedAt: now,
    }, ...filtered].slice(0, RECENT_LIMIT),
  };
}

export function toggleSavedMarket(
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
      savedMarkets: [{
        market: cloneMarket(market),
        savedAt,
        viewedAt: state.recentMarkets.find((entry) => entry.market.id === market.id)?.viewedAt ?? savedAt,
      }, ...state.savedMarkets].map(cloneSnapshot),
    },
  };
}
