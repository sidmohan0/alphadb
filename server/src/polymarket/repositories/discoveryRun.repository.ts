import { randomUUID } from "crypto";
import { Pool } from "pg";

import { DiscoveryRunStatus, DiscoveryRunReadModel, DiscoveryRunSummary, MarketDiscoveryConfig, type MarketChannelRunResult } from "../types";
import { getPgPool } from "../infra/db/postgres";

export interface DiscoveryRunRepository {
  createRun(params: {
    dedupeKey: string;
    status: DiscoveryRunStatus;
    config: MarketDiscoveryConfig;
    requestId: string;
    expiresAt: Date;
    requestedAt?: Date;
    runId?: string;
  }): Promise<string>;

  findById(runId: string): Promise<DiscoveryRunRecord | null>;
  findActiveByDedupeKey(dedupeKey: string): Promise<DiscoveryRunRecord | null>;
  findLatest(): Promise<DiscoveryRunRecord | null>;
  findActiveRuns(limit?: number): Promise<DiscoveryRunRecord[]>;
  updateRun(runId: string, patch: DiscoveryRunPatch): Promise<void>;
  pruneExpired(before: Date): Promise<{ deleted: number; runs: { runId: string; dedupeKey: string }[] }>;
}

export interface DiscoveryRunRecord {
  id: string;
  dedupeKey: string;
  status: DiscoveryRunStatus;
  clobApiUrl: string;
  chainId: number;
  wsUrl: string | null;
  wsConnectTimeoutMs: number;
  wsChunkSize: number;
  marketFetchTimeoutMs: number;
  requestedAt: Date;
  startedAt: Date | null;
  completedAt: Date | null;
  marketCount: number;
  marketChannelCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  errorRetryable: boolean | null;
  errorDetails: unknown;
  requestId: string;
  expiresAt: Date;
  requestPayload: Record<string, unknown>;
}

export interface DiscoveryRunPatch {
  status?: DiscoveryRunStatus;
  startedAt?: Date | null;
  completedAt?: Date | null;
  marketCount?: number;
  marketChannelCount?: number;
  errorCode?: string | null;
  errorMessage?: string | null;
  errorRetryable?: boolean | null;
  errorDetails?: unknown;
}

interface DbDiscoveryRunRepositoryOptions {
  pool?: Pool;
}

function parseRequestPayload(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object") {
    return {};
  }

  return value as Record<string, unknown>;
}

function readFilteredDiscoveryPayload(payload: Record<string, unknown>): {
  maxMarkets?: number;
  acceptingOrders?: boolean;
  questionIdContains?: string;
  rewardsHasRates?: boolean;
  rewardsMinSizeMin?: number;
  rewardsMinSizeMax?: number;
  rewardsMaxSpreadMin?: number;
  rewardsMaxSpreadMax?: number;
  iconContains?: string;
  imageContains?: string;
  enableOrderBook?: boolean;
  minimumOrderSizeMin?: number;
  minimumOrderSizeMax?: number;
  minimumTickSizeMin?: number;
  minimumTickSizeMax?: number;
  makerBaseFeeMin?: number;
  makerBaseFeeMax?: number;
  takerBaseFeeMin?: number;
  takerBaseFeeMax?: number;
  notificationsEnabled?: boolean;
  negRisk?: boolean;
  fpmm?: string;
  secondsDelayMin?: number;
  secondsDelayMax?: number;
  acceptingOrderTimestampMin?: number;
  acceptingOrderTimestampMax?: number;
  descriptionContains?: string;
  conditionIdContains?: string;
  negRiskMarketIdContains?: string;
  negRiskRequestIdContains?: string;
  endDateIsoMin?: string;
  endDateIsoMax?: string;
  gameStartTimeMin?: string;
  gameStartTimeMax?: string;
  active?: boolean;
  closed?: boolean;
  archived?: boolean;
  isFiftyFiftyOutcome?: boolean;
  tags?: string[];
  questionContains?: string;
  marketSlugContains?: string;
} {
  const questionContains =
    typeof payload.questionContains === "string" && payload.questionContains.trim()
      ? payload.questionContains.trim()
      : undefined;
  const marketSlugContains =
    typeof payload.marketSlugContains === "string" && payload.marketSlugContains.trim()
      ? payload.marketSlugContains.trim()
      : undefined;
  const parseNonNegativeNumber = (raw: unknown): number | undefined => {
    if (typeof raw === "number" && Number.isFinite(raw)) {
      return raw;
    }

    if (typeof raw === "string") {
      const parsed = Number(raw);
      return Number.isFinite(parsed) ? parsed : undefined;
    }

    return undefined;
  };

  const parsePositiveInteger = (raw: unknown): number | undefined => {
    if (typeof raw === "number" && Number.isFinite(raw)) {
      return Number.isInteger(raw) && raw > 0 ? raw : undefined;
    }

    if (typeof raw === "string") {
      const trimmed = raw.trim();
      if (!trimmed) {
        return undefined;
      }

      const parsed = Number(trimmed);
      return Number.isInteger(parsed) && parsed > 0 && Number.isFinite(parsed) ? parsed : undefined;
    }

    return undefined;
  };

  const maxMarkets = parsePositiveInteger(payload.maxMarkets);
  const parseDate = (raw: unknown): string | undefined => {
    if (typeof raw === "string") {
      const trimmed = raw.trim();
      if (!trimmed) {
        return undefined;
      }

      const parsed = Date.parse(trimmed);
      return Number.isFinite(parsed) ? trimmed : undefined;
    }

    if (typeof raw === "number" && Number.isFinite(raw)) {
      const date = new Date(raw);
      return Number.isFinite(date.getTime()) ? date.toISOString() : undefined;
    }

    return undefined;
  };

  const minimumOrderSizeMin =
    typeof payload.minimumOrderSizeMin === "number" && Number.isFinite(payload.minimumOrderSizeMin)
      ? payload.minimumOrderSizeMin
      : typeof payload.minimumOrderSizeMin === "string"
      ? Number(payload.minimumOrderSizeMin)
      : undefined;
  const minimumOrderSizeMax =
    typeof payload.minimumOrderSizeMax === "number" && Number.isFinite(payload.minimumOrderSizeMax)
      ? payload.minimumOrderSizeMax
      : typeof payload.minimumOrderSizeMax === "string"
      ? Number(payload.minimumOrderSizeMax)
      : undefined;
  const safeMinimumOrderSizeMin =
    minimumOrderSizeMin !== undefined && Number.isFinite(minimumOrderSizeMin) ? minimumOrderSizeMin : undefined;
  const safeMinimumOrderSizeMax =
    minimumOrderSizeMax !== undefined && Number.isFinite(minimumOrderSizeMax) ? minimumOrderSizeMax : undefined;
  const minimumTickSizeMin = parseNonNegativeNumber(payload.minimumTickSizeMin);
  const minimumTickSizeMax = parseNonNegativeNumber(payload.minimumTickSizeMax);
  const makerBaseFeeMin = parseNonNegativeNumber(payload.makerBaseFeeMin);
  const makerBaseFeeMax = parseNonNegativeNumber(payload.makerBaseFeeMax);
  const takerBaseFeeMin = parseNonNegativeNumber(payload.takerBaseFeeMin);
  const takerBaseFeeMax = parseNonNegativeNumber(payload.takerBaseFeeMax);
  const secondsDelayMin = parseNonNegativeNumber(payload.secondsDelayMin);
  const secondsDelayMax = parseNonNegativeNumber(payload.secondsDelayMax);
  const acceptingOrderTimestampMin = parseNonNegativeNumber(payload.acceptingOrderTimestampMin);
  const acceptingOrderTimestampMax = parseNonNegativeNumber(payload.acceptingOrderTimestampMax);
  const endDateIsoMin = parseDate(payload.endDateIsoMin);
  const endDateIsoMax = parseDate(payload.endDateIsoMax);
  const gameStartTimeMin = parseDate(payload.gameStartTimeMin);
  const gameStartTimeMax = parseDate(payload.gameStartTimeMax);
  const questionIdContains =
    typeof payload.questionIdContains === "string" && payload.questionIdContains.trim()
      ? payload.questionIdContains.trim()
      : undefined;
  const fpmm =
    typeof payload.fpmm === "string" && payload.fpmm.trim() ? payload.fpmm.trim() : undefined;
  const descriptionContains =
    typeof payload.descriptionContains === "string" && payload.descriptionContains.trim()
      ? payload.descriptionContains.trim()
      : undefined;
  const conditionIdContains =
    typeof payload.conditionIdContains === "string" && payload.conditionIdContains.trim()
      ? payload.conditionIdContains.trim()
      : undefined;
  const negRiskMarketIdContains =
    typeof payload.negRiskMarketIdContains === "string" && payload.negRiskMarketIdContains.trim()
      ? payload.negRiskMarketIdContains.trim()
      : undefined;
  const negRiskRequestIdContains =
    typeof payload.negRiskRequestIdContains === "string" && payload.negRiskRequestIdContains.trim()
      ? payload.negRiskRequestIdContains.trim()
      : undefined;
  const rewardsMinSizeMin = parseNonNegativeNumber(payload.rewardsMinSizeMin);
  const rewardsMinSizeMax = parseNonNegativeNumber(payload.rewardsMinSizeMax);
  const rewardsMaxSpreadMin = parseNonNegativeNumber(payload.rewardsMaxSpreadMin);
  const rewardsMaxSpreadMax = parseNonNegativeNumber(payload.rewardsMaxSpreadMax);
  const iconContains =
    typeof payload.iconContains === "string" && payload.iconContains.trim()
      ? payload.iconContains.trim()
      : undefined;
  const imageContains =
    typeof payload.imageContains === "string" && payload.imageContains.trim()
      ? payload.imageContains.trim()
      : undefined;

  const tags = Array.isArray(payload.tags)
    ? payload.tags
        .map((tag) => {
          if (typeof tag !== "string") {
            return undefined;
          }

          const normalized = tag.trim();
          return normalized.length > 0 ? normalized : undefined;
        })
        .filter((tag): tag is string => tag !== undefined)
    : undefined;

  return {
    ...(maxMarkets !== undefined ? { maxMarkets } : {}),
    ...(typeof payload.questionIdContains === "string"
      ? { questionIdContains: payload.questionIdContains.trim() }
      : {}),
    ...(typeof payload.rewardsHasRates === "boolean" ? { rewardsHasRates: payload.rewardsHasRates } : {}),
    ...(rewardsMinSizeMin !== undefined && rewardsMinSizeMin >= 0 ? { rewardsMinSizeMin } : {}),
    ...(rewardsMinSizeMax !== undefined && rewardsMinSizeMax >= 0 ? { rewardsMinSizeMax } : {}),
    ...(rewardsMaxSpreadMin !== undefined && rewardsMaxSpreadMin >= 0 ? { rewardsMaxSpreadMin } : {}),
    ...(rewardsMaxSpreadMax !== undefined && rewardsMaxSpreadMax >= 0 ? { rewardsMaxSpreadMax } : {}),
    ...(iconContains ? { iconContains } : {}),
    ...(imageContains ? { imageContains } : {}),
    ...(typeof payload.acceptingOrders === "boolean" ? { acceptingOrders: payload.acceptingOrders } : {}),
    ...(typeof payload.enableOrderBook === "boolean" ? { enableOrderBook: payload.enableOrderBook } : {}),
    ...(safeMinimumOrderSizeMin !== undefined && safeMinimumOrderSizeMin >= 0
      ? { minimumOrderSizeMin: safeMinimumOrderSizeMin }
      : {}),
    ...(safeMinimumOrderSizeMax !== undefined && safeMinimumOrderSizeMax >= 0
      ? { minimumOrderSizeMax: safeMinimumOrderSizeMax }
      : {}),
    ...(minimumTickSizeMin !== undefined && minimumTickSizeMin >= 0
      ? { minimumTickSizeMin }
      : {}),
    ...(minimumTickSizeMax !== undefined && minimumTickSizeMax >= 0
      ? { minimumTickSizeMax }
      : {}),
    ...(makerBaseFeeMin !== undefined && makerBaseFeeMin >= 0 ? { makerBaseFeeMin } : {}),
    ...(makerBaseFeeMax !== undefined && makerBaseFeeMax >= 0 ? { makerBaseFeeMax } : {}),
    ...(takerBaseFeeMin !== undefined && takerBaseFeeMin >= 0 ? { takerBaseFeeMin } : {}),
    ...(takerBaseFeeMax !== undefined && takerBaseFeeMax >= 0 ? { takerBaseFeeMax } : {}),
    ...(typeof payload.notificationsEnabled === "boolean"
      ? { notificationsEnabled: payload.notificationsEnabled }
      : {}),
    ...(typeof payload.negRisk === "boolean" ? { negRisk: payload.negRisk } : {}),
    ...(fpmm ? { fpmm } : {}),
    ...(secondsDelayMin !== undefined && secondsDelayMin >= 0 ? { secondsDelayMin } : {}),
    ...(secondsDelayMax !== undefined && secondsDelayMax >= 0 ? { secondsDelayMax } : {}),
    ...(acceptingOrderTimestampMin !== undefined
      ? { acceptingOrderTimestampMin }
      : {}),
    ...(acceptingOrderTimestampMax !== undefined
      ? { acceptingOrderTimestampMax }
      : {}),
    ...(descriptionContains ? { descriptionContains } : {}),
    ...(conditionIdContains ? { conditionIdContains } : {}),
    ...(negRiskMarketIdContains ? { negRiskMarketIdContains } : {}),
    ...(negRiskRequestIdContains ? { negRiskRequestIdContains } : {}),
    ...(endDateIsoMin ? { endDateIsoMin } : {}),
    ...(endDateIsoMax ? { endDateIsoMax } : {}),
    ...(gameStartTimeMin ? { gameStartTimeMin } : {}),
    ...(gameStartTimeMax ? { gameStartTimeMax } : {}),
    ...(typeof payload.active === "boolean" ? { active: payload.active } : {}),
    ...(typeof payload.closed === "boolean" ? { closed: payload.closed } : {}),
    ...(typeof payload.archived === "boolean" ? { archived: payload.archived } : {}),
    ...(typeof payload.isFiftyFiftyOutcome === "boolean"
      ? { isFiftyFiftyOutcome: payload.isFiftyFiftyOutcome }
      : {}),
    ...(tags && tags.length > 0 ? { tags } : {}),
    ...(questionContains ? { questionContains } : {}),
    ...(marketSlugContains ? { marketSlugContains } : {}),
  };
}

function createRequestPayload(config: MarketDiscoveryConfig): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    clobApiUrl: config.clobApiUrl,
    chainId: config.chainId,
    maxMarkets: config.maxMarkets,
    wsUrl: config.wsUrl,
    wsConnectTimeoutMs: config.wsConnectTimeoutMs,
    wsChunkSize: config.wsChunkSize,
    marketFetchTimeoutMs: config.marketFetchTimeoutMs,
  };

  if (config.active !== undefined) {
    payload.active = config.active;
  }

  if (config.closed !== undefined) {
    payload.closed = config.closed;
  }

  if (config.archived !== undefined) {
    payload.archived = config.archived;
  }

  if (config.acceptingOrders !== undefined) {
    payload.acceptingOrders = config.acceptingOrders;
  }

  if (config.enableOrderBook !== undefined) {
    payload.enableOrderBook = config.enableOrderBook;
  }

  if (config.minimumOrderSizeMin !== undefined) {
    payload.minimumOrderSizeMin = config.minimumOrderSizeMin;
  }

  if (config.minimumOrderSizeMax !== undefined) {
    payload.minimumOrderSizeMax = config.minimumOrderSizeMax;
  }

  if (config.minimumTickSizeMin !== undefined) {
    payload.minimumTickSizeMin = config.minimumTickSizeMin;
  }

  if (config.minimumTickSizeMax !== undefined) {
    payload.minimumTickSizeMax = config.minimumTickSizeMax;
  }

  if (config.makerBaseFeeMin !== undefined) {
    payload.makerBaseFeeMin = config.makerBaseFeeMin;
  }

  if (config.makerBaseFeeMax !== undefined) {
    payload.makerBaseFeeMax = config.makerBaseFeeMax;
  }

  if (config.takerBaseFeeMin !== undefined) {
    payload.takerBaseFeeMin = config.takerBaseFeeMin;
  }

  if (config.takerBaseFeeMax !== undefined) {
    payload.takerBaseFeeMax = config.takerBaseFeeMax;
  }

  if (config.notificationsEnabled !== undefined) {
    payload.notificationsEnabled = config.notificationsEnabled;
  }

  if (config.negRisk !== undefined) {
    payload.negRisk = config.negRisk;
  }

  if (config.fpmm !== undefined) {
    payload.fpmm = config.fpmm;
  }

  if (config.secondsDelayMin !== undefined) {
    payload.secondsDelayMin = config.secondsDelayMin;
  }

  if (config.secondsDelayMax !== undefined) {
    payload.secondsDelayMax = config.secondsDelayMax;
  }

  if (config.acceptingOrderTimestampMin !== undefined) {
    payload.acceptingOrderTimestampMin = config.acceptingOrderTimestampMin;
  }

  if (config.acceptingOrderTimestampMax !== undefined) {
    payload.acceptingOrderTimestampMax = config.acceptingOrderTimestampMax;
  }

  if (config.descriptionContains !== undefined) {
    payload.descriptionContains = config.descriptionContains;
  }

  if (config.conditionIdContains !== undefined) {
    payload.conditionIdContains = config.conditionIdContains;
  }

  if (config.negRiskMarketIdContains !== undefined) {
    payload.negRiskMarketIdContains = config.negRiskMarketIdContains;
  }

  if (config.negRiskRequestIdContains !== undefined) {
    payload.negRiskRequestIdContains = config.negRiskRequestIdContains;
  }

  if (config.endDateIsoMin !== undefined) {
    payload.endDateIsoMin = config.endDateIsoMin;
  }

  if (config.endDateIsoMax !== undefined) {
    payload.endDateIsoMax = config.endDateIsoMax;
  }

  if (config.gameStartTimeMin !== undefined) {
    payload.gameStartTimeMin = config.gameStartTimeMin;
  }

  if (config.gameStartTimeMax !== undefined) {
    payload.gameStartTimeMax = config.gameStartTimeMax;
  }

  if (config.isFiftyFiftyOutcome !== undefined) {
    payload.isFiftyFiftyOutcome = config.isFiftyFiftyOutcome;
  }

  if (config.tags && config.tags.length > 0) {
    payload.tags = config.tags;
  }

  if (config.questionContains) {
    payload.questionContains = config.questionContains;
  }

  if (config.marketSlugContains) {
    payload.marketSlugContains = config.marketSlugContains;
  }

  if (config.questionIdContains !== undefined) {
    payload.questionIdContains = config.questionIdContains;
  }

  if (config.rewardsHasRates !== undefined) {
    payload.rewardsHasRates = config.rewardsHasRates;
  }

  if (config.rewardsMinSizeMin !== undefined) {
    payload.rewardsMinSizeMin = config.rewardsMinSizeMin;
  }

  if (config.rewardsMinSizeMax !== undefined) {
    payload.rewardsMinSizeMax = config.rewardsMinSizeMax;
  }

  if (config.rewardsMaxSpreadMin !== undefined) {
    payload.rewardsMaxSpreadMin = config.rewardsMaxSpreadMin;
  }

  if (config.rewardsMaxSpreadMax !== undefined) {
    payload.rewardsMaxSpreadMax = config.rewardsMaxSpreadMax;
  }

  if (config.iconContains !== undefined) {
    payload.iconContains = config.iconContains;
  }

  if (config.imageContains !== undefined) {
    payload.imageContains = config.imageContains;
  }

  return payload;
}

export class DbDiscoveryRunRepository implements DiscoveryRunRepository {
  private readonly pool: Pool;

  constructor(options?: DbDiscoveryRunRepositoryOptions) {
    this.pool = options?.pool ?? getPgPool();
  }

  private mapRow(row: Record<string, unknown>): DiscoveryRunRecord {
    return {
      id: String(row.id),
      dedupeKey: String(row.dedupe_key),
      status: String(row.status) as DiscoveryRunStatus,
      clobApiUrl: String(row.clob_api_url),
      chainId: Number(row.chain_id),
      wsUrl: row.ws_url == null ? null : String(row.ws_url),
      wsConnectTimeoutMs: Number(row.ws_connect_timeout_ms),
      wsChunkSize: Number(row.ws_chunk_size),
      marketFetchTimeoutMs: Number(row.market_fetch_timeout_ms),
      requestedAt: new Date(row.requested_at as string),
      startedAt: row.started_at == null ? null : new Date(row.started_at as string),
      completedAt: row.completed_at == null ? null : new Date(row.completed_at as string),
      marketCount: Number(row.market_count),
      marketChannelCount: Number(row.market_channel_count),
      errorCode: row.error_code == null ? null : String(row.error_code),
      errorMessage: row.error_message == null ? null : String(row.error_message),
      errorRetryable: row.error_retryable == null ? null : Boolean(row.error_retryable),
      errorDetails: row.error_details ?? null,
      requestId: String(row.request_id),
      expiresAt: new Date(row.expires_at as string),
      requestPayload: parseRequestPayload(row.request_payload),
    };
  }

  async createRun(params: {
    dedupeKey: string;
    status: DiscoveryRunStatus;
    config: MarketDiscoveryConfig;
    requestId: string;
    expiresAt: Date;
    requestedAt?: Date;
    runId?: string;
  }): Promise<string> {
    const runId = params.runId ?? randomUUID();
    const requestedAt = params.requestedAt ?? new Date();

    await this.pool.query(
      `INSERT INTO discovery_runs
        (id, dedupe_key, status, clob_api_url, chain_id, ws_url, ws_connect_timeout_ms, ws_chunk_size, market_fetch_timeout_ms, requested_at, market_count, market_channel_count, error_code, error_message, error_retryable, error_details, request_id, expires_at, request_payload, dedupe_key_normalized)
      VALUES
        ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 0, 0, NULL, NULL, NULL, NULL, $11, $12, $13::jsonb, $2)
      `,
      [
        runId,
        params.dedupeKey,
        params.status,
        params.config.clobApiUrl,
        params.config.chainId,
        params.config.wsUrl ?? null,
        params.config.wsConnectTimeoutMs,
        params.config.wsChunkSize,
        params.config.marketFetchTimeoutMs,
        requestedAt,
        params.requestId,
        params.expiresAt,
        JSON.stringify(createRequestPayload(params.config)),
      ]
    );

    return runId;
  }

  async findById(runId: string): Promise<DiscoveryRunRecord | null> {
    const result = await this.pool.query("SELECT * FROM discovery_runs WHERE id=$1", [runId]);
    if (!result.rowCount) {
      return null;
    }

    return this.mapRow(result.rows[0] as Record<string, unknown>);
  }

  async findActiveByDedupeKey(dedupeKey: string): Promise<DiscoveryRunRecord | null> {
    const result = await this.pool.query(
      "SELECT * FROM discovery_runs WHERE dedupe_key=$1 AND status IN ('queued', 'running') ORDER BY requested_at DESC LIMIT 1",
      [dedupeKey]
    );

    if (!result.rowCount) {
      return null;
    }

    return this.mapRow(result.rows[0] as Record<string, unknown>);
  }

  async findLatest(): Promise<DiscoveryRunRecord | null> {
    const result = await this.pool.query(
      "SELECT * FROM discovery_runs ORDER BY requested_at DESC, id DESC LIMIT 1"
    );

    if (!result.rowCount) {
      return null;
    }

    return this.mapRow(result.rows[0] as Record<string, unknown>);
  }

  async findActiveRuns(limit = 50): Promise<DiscoveryRunRecord[]> {
    const safeLimit = Number.isFinite(limit) && Number.isInteger(limit) && limit > 0
      ? Math.min(limit, 500)
      : 50;

    const result = await this.pool.query(
      "SELECT * FROM discovery_runs WHERE status IN ('queued', 'running') ORDER BY requested_at DESC, id DESC LIMIT $1",
      [safeLimit]
    );

    return result.rows.map((row) => this.mapRow(row as Record<string, unknown>));
  }

  async updateRun(runId: string, patch: DiscoveryRunPatch): Promise<void> {
    const fields: string[] = [];
    const values: unknown[] = [];
    let index = 1;

    const push = (field: string, value: unknown): void => {
      fields.push(`${field} = $${index++}`);
      values.push(value);
    };

    if (patch.status !== undefined) {
      push("status", patch.status);
    }
    if (patch.startedAt !== undefined) {
      push("started_at", patch.startedAt);
    }
    if (patch.completedAt !== undefined) {
      push("completed_at", patch.completedAt);
    }
    if (patch.marketCount !== undefined) {
      push("market_count", patch.marketCount);
    }
    if (patch.marketChannelCount !== undefined) {
      push("market_channel_count", patch.marketChannelCount);
    }
    if (patch.errorCode !== undefined) {
      push("error_code", patch.errorCode);
    }
    if (patch.errorMessage !== undefined) {
      push("error_message", patch.errorMessage);
    }
    if (patch.errorRetryable !== undefined) {
      push("error_retryable", patch.errorRetryable);
    }
    if (patch.errorDetails !== undefined) {
      push("error_details", patch.errorDetails == null ? null : JSON.stringify(patch.errorDetails));
    }

    if (!fields.length) return;

    values.push(runId);
    await this.pool.query(`UPDATE discovery_runs SET ${fields.join(", ")} WHERE id=$${index}`, values);
  }

  async pruneExpired(before: Date): Promise<{ deleted: number; runs: { runId: string; dedupeKey: string }[] }> {
    const result = await this.pool.query(
      "DELETE FROM discovery_runs WHERE expires_at < $1 RETURNING id, dedupe_key",
      [before]
    );

    const rows = result.rows.map((row) => ({
      runId: String(row.id),
      dedupeKey: String(row.dedupe_key),
    }));

    return { deleted: result.rowCount ?? 0, runs: rows };
  }
}

export function createDiscoveryRunRepository(): DiscoveryRunRepository {
  return new DbDiscoveryRunRepository();
}

export function rowToShell(row: DiscoveryRunRecord, scope: string = "default"): DiscoveryRunSummary {
  return {
    runId: row.id,
    status: row.status,
    dedupeKey: row.dedupeKey,
    pollUrl: `/api/polymarket/market-channels/runs/${row.id}`,
    requestId: row.requestId,
  };
}

export function rowToReadModel(row: DiscoveryRunRecord): DiscoveryRunReadModel {
  return {
    run: {
      id: row.id,
      status: row.status,
      dedupeKey: row.dedupeKey,
      requestedAt: row.requestedAt.toISOString(),
      startedAt: row.startedAt?.toISOString(),
      completedAt: row.completedAt?.toISOString(),
      source: {
        clobApiUrl: row.clobApiUrl,
        chainId: row.chainId,
        wsUrl: row.wsUrl ?? undefined,
        wsConnectTimeoutMs: row.wsConnectTimeoutMs,
        wsChunkSize: row.wsChunkSize,
        marketFetchTimeoutMs: row.marketFetchTimeoutMs,
        ...(readFilteredDiscoveryPayload(row.requestPayload)),
      },
      marketCount: row.marketCount,
      marketChannelCount: row.marketChannelCount,
      errorCode: row.errorCode,
      errorMessage: row.errorMessage,
      errorRetryable: row.errorRetryable,
      requestId: row.requestId,
    },
    channels: {
      items: [],
      page: {
        offset: 0,
        limit: 0,
        total: 0,
        hasMore: false,
      },
    },
    wsScan: null,
  };
}

export { createDiscoveryRunRepository as default };
