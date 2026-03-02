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
  updateRun(runId: string, patch: DiscoveryRunPatch): Promise<void>;
  pruneExpired(before: Date): Promise<number>;
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
        JSON.stringify({
          clobApiUrl: params.config.clobApiUrl,
          chainId: params.config.chainId,
          wsUrl: params.config.wsUrl,
          wsConnectTimeoutMs: params.config.wsConnectTimeoutMs,
          wsChunkSize: params.config.wsChunkSize,
          marketFetchTimeoutMs: params.config.marketFetchTimeoutMs,
        }),
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

  async pruneExpired(before: Date): Promise<number> {
    const result = await this.pool.query("DELETE FROM discovery_runs WHERE expires_at < $1", [before]);
    return result.rowCount ?? 0;
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
