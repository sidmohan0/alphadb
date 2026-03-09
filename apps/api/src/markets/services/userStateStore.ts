import os from "node:os";
import path from "node:path";
import { mkdir, readFile, writeFile } from "node:fs/promises";

import { PoolClient } from "pg";

import { getPgPool } from "../../polymarket/infra/db/postgres";
import { ensureMarketStateSchema } from "../maintenance/marketStateSchema";
import { MarketSummary, PersistedMarketSnapshot, PersistentState } from "../types";

const RECENT_LIMIT = 24;
type UserStateBackend = "file" | "postgres";

interface UserStateFile {
  users: Record<string, PersistentState>;
}

let writeQueue = Promise.resolve();
let postgresReadyPromise: Promise<void> | null = null;

function cloneMarket(market: MarketSummary): MarketSummary {
  return {
    ...market,
    outcomes: market.outcomes.map((outcome) => ({ ...outcome })),
  };
}

export function normalizeMarketSummary(value: unknown): MarketSummary | null {
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

function defaultState(): PersistentState {
  return {
    savedMarkets: [],
    recentMarkets: [],
  };
}

function cloneSnapshot(snapshot: PersistedMarketSnapshot): PersistedMarketSnapshot {
  return {
    market: cloneMarket(snapshot.market),
    savedAt: snapshot.savedAt,
    viewedAt: snapshot.viewedAt,
  };
}

function statePath(): string {
  if (process.env.ALPHADB_API_USER_STATE_PATH?.trim()) {
    return process.env.ALPHADB_API_USER_STATE_PATH.trim();
  }

  return path.join(os.homedir(), ".config", "alphadb-platform", "user-state.json");
}

async function readAllStates(): Promise<UserStateFile> {
  try {
    const raw = await readFile(statePath(), "utf8");
    const parsed = JSON.parse(raw) as Partial<UserStateFile>;
    return {
      users: parsed.users && typeof parsed.users === "object" ? parsed.users as Record<string, PersistentState> : {},
    };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { users: {} };
    }

    throw error;
  }
}

async function writeAllStates(state: UserStateFile): Promise<void> {
  const outputPath = statePath();
  writeQueue = writeQueue.then(async () => {
    await mkdir(path.dirname(outputPath), { recursive: true });
    await writeFile(outputPath, JSON.stringify(state, null, 2), "utf8");
  }).catch(() => undefined);

  await writeQueue;
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

function normalizeState(value: unknown): PersistentState {
  if (!value || typeof value !== "object") {
    return defaultState();
  }

  const raw = value as Partial<PersistentState>;
  return {
    savedMarkets: normalizeSnapshots(raw.savedMarkets),
    recentMarkets: normalizeSnapshots(raw.recentMarkets),
  };
}

function cloneState(state: PersistentState): PersistentState {
  return {
    savedMarkets: state.savedMarkets.map(cloneSnapshot),
    recentMarkets: state.recentMarkets.map(cloneSnapshot),
  };
}

export function getUserStateBackend(): UserStateBackend {
  const configured = process.env.ALPHADB_API_USER_STATE_BACKEND?.trim().toLowerCase();

  if (!configured || configured === "auto") {
    return process.env.DATABASE_URL ? "postgres" : "file";
  }

  if (configured === "postgres" || configured === "file") {
    return configured;
  }

  throw new Error("ALPHADB_API_USER_STATE_BACKEND must be one of auto, postgres, or file");
}

export function isPostgresUserStateEnabled(): boolean {
  return getUserStateBackend() === "postgres";
}

async function ensurePostgresUserStateReady(): Promise<void> {
  if (!isPostgresUserStateEnabled()) {
    return;
  }

  if (!postgresReadyPromise) {
    postgresReadyPromise = ensureMarketStateSchema({ closePoolAfter: false })
      .then(() => undefined)
      .catch((error) => {
        postgresReadyPromise = null;
        throw error;
      });
  }

  await postgresReadyPromise;
}

async function readPostgresState(userId: string): Promise<PersistentState> {
  await ensurePostgresUserStateReady();
  const pool = getPgPool();

  await pool.query(
    "INSERT INTO market_user_states (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
    [userId],
  );

  const result = await pool.query(
    "SELECT saved_markets, recent_markets FROM market_user_states WHERE user_id=$1",
    [userId],
  );

  const row = result.rows[0] as { saved_markets?: unknown; recent_markets?: unknown } | undefined;
  return normalizeState({
    savedMarkets: row?.saved_markets,
    recentMarkets: row?.recent_markets,
  });
}

async function updatePostgresState(
  userId: string,
  updater: (state: PersistentState) => PersistentState,
): Promise<PersistentState> {
  await ensurePostgresUserStateReady();
  const pool = getPgPool();
  const client = await pool.connect();

  try {
    await client.query("BEGIN");
    await ensurePostgresUserRow(client, userId);

    const current = await readPostgresStateForUpdate(client, userId);
    const next = updater(current);

    await client.query(
      `UPDATE market_user_states
       SET saved_markets=$2::jsonb,
           recent_markets=$3::jsonb,
           updated_at=NOW()
       WHERE user_id=$1`,
      [userId, JSON.stringify(next.savedMarkets), JSON.stringify(next.recentMarkets)],
    );

    await client.query("COMMIT");
    return cloneState(next);
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

async function ensurePostgresUserRow(client: PoolClient, userId: string): Promise<void> {
  await client.query(
    "INSERT INTO market_user_states (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
    [userId],
  );
}

async function readPostgresStateForUpdate(client: PoolClient, userId: string): Promise<PersistentState> {
  const result = await client.query(
    "SELECT saved_markets, recent_markets FROM market_user_states WHERE user_id=$1 FOR UPDATE",
    [userId],
  );

  const row = result.rows[0] as { saved_markets?: unknown; recent_markets?: unknown } | undefined;
  return normalizeState({
    savedMarkets: row?.saved_markets,
    recentMarkets: row?.recent_markets,
  });
}

export function resolveUserId(explicit?: string): string {
  if (explicit?.trim()) {
    return explicit.trim();
  }

  if (process.env.ALPHADB_DEFAULT_USER_ID?.trim()) {
    return process.env.ALPHADB_DEFAULT_USER_ID.trim();
  }

  return "local-user";
}

export async function getUserMarketState(userId: string): Promise<PersistentState> {
  if (isPostgresUserStateEnabled()) {
    return readPostgresState(userId);
  }

  const state = await readAllStates();
  return normalizeState(state.users[userId]);
}

async function updateState(userId: string, updater: (state: PersistentState) => PersistentState): Promise<PersistentState> {
  if (isPostgresUserStateEnabled()) {
    return updatePostgresState(userId, updater);
  }

  const allStates = await readAllStates();
  const current = normalizeState(allStates.users[userId]);
  const next = updater(current);
  allStates.users[userId] = next;
  await writeAllStates(allStates);
  return cloneState(next);
}

export async function saveMarketForUser(userId: string, market: MarketSummary): Promise<{ state: PersistentState; saved: boolean }> {
  const state = await updateState(userId, (current) => {
    if (current.savedMarkets.some((entry) => entry.market.id === market.id)) {
      return current;
    }

    const savedAt = Date.now();
    return {
      ...current,
      savedMarkets: [{
        market: cloneMarket(market),
        savedAt,
        viewedAt: current.recentMarkets.find((entry) => entry.market.id === market.id)?.viewedAt ?? savedAt,
      }, ...current.savedMarkets],
    };
  });

  return { state, saved: true };
}

export async function removeSavedMarketForUser(userId: string, marketId: string): Promise<{ state: PersistentState; saved: boolean }> {
  const state = await updateState(userId, (current) => ({
    ...current,
    savedMarkets: current.savedMarkets.filter((entry) => entry.market.id !== marketId),
  }));

  return { state, saved: false };
}

export async function touchRecentMarketForUser(userId: string, market: MarketSummary): Promise<PersistentState> {
  return updateState(userId, (current) => {
    const now = Date.now();
    const filtered = current.recentMarkets.filter((entry) => entry.market.id !== market.id);

    return {
      ...current,
      recentMarkets: [{
        market: cloneMarket(market),
        savedAt: current.savedMarkets.find((entry) => entry.market.id === market.id)?.savedAt,
        viewedAt: now,
      }, ...filtered].slice(0, RECENT_LIMIT),
    };
  });
}
