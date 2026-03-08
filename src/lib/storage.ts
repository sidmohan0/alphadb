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
    if (!raw.market || typeof raw.market !== "object") {
      return [];
    }

    return [{
      market: cloneMarket(raw.market as MarketSummary),
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
