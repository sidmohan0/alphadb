import { randomUUID } from "crypto";
import { Pool } from "pg";

import { getPgPool } from "../infra/db/postgres";

export interface DiscoveryRunRetryQueueRecord {
  id: string;
  runId: string;
  attempt: number;
  maxAttempts: number;
  nextAttemptAt: Date;
  status: "queued" | "processing" | "dead";
  lastErrorCode: string | null;
  lastErrorMessage: string | null;
  lastErrorRetryable: boolean | null;
  lastErrorDetails: unknown;
}

export interface DiscoveryRunRetryQueueRepository {
  get(runId: string): Promise<DiscoveryRunRetryQueueRecord | null>;
  upsert(
    runId: string,
    attempt: number,
    maxAttempts: number,
    nextAttemptAt: Date,
    lastError: {
      code: string;
      message: string;
      retryable: boolean | null;
      details?: unknown;
    }
  ): Promise<void>;
  markDone(runId: string): Promise<void>;
  markDead(runId: string): Promise<void>;
  claimDue(now: Date, batchSize: number): Promise<DiscoveryRunRetryQueueRecord[]>;
}

interface DbDiscoveryRunRetryQueueRepositoryOptions {
  pool?: Pool;
}

export class DbDiscoveryRunRetryQueueRepository implements DiscoveryRunRetryQueueRepository {
  private readonly pool: Pool;

  constructor(options?: DbDiscoveryRunRetryQueueRepositoryOptions) {
    this.pool = options?.pool ?? getPgPool();
  }

  async get(runId: string): Promise<DiscoveryRunRetryQueueRecord | null> {
    const result = await this.pool.query(
      `SELECT id, discovery_run_id, attempt, max_attempts, next_attempt_at, status, last_error_code, last_error_message, last_error_retryable, last_error_details
       FROM discovery_run_retries
       WHERE discovery_run_id=$1`,
      [runId]
    );

    if (!result.rowCount) {
      return null;
    }

    return this.mapRow(result.rows[0] as Record<string, unknown>);
  }

  async upsert(
    runId: string,
    attempt: number,
    maxAttempts: number,
    nextAttemptAt: Date,
    lastError: {
      code: string;
      message: string;
      retryable: boolean | null;
      details?: unknown;
    }
  ): Promise<void> {
    await this.pool.query(
      `INSERT INTO discovery_run_retries
        (id, discovery_run_id, attempt, max_attempts, next_attempt_at, status, last_error_code, last_error_message, last_error_retryable, last_error_details)
      VALUES
        ($1, $2, $3, $4, $5, 'queued', $6, $7, $8, $9)
      ON CONFLICT (discovery_run_id) DO UPDATE SET
        attempt = EXCLUDED.attempt,
        max_attempts = EXCLUDED.max_attempts,
        next_attempt_at = EXCLUDED.next_attempt_at,
        status = EXCLUDED.status,
        last_error_code = EXCLUDED.last_error_code,
        last_error_message = EXCLUDED.last_error_message,
        last_error_retryable = EXCLUDED.last_error_retryable,
        last_error_details = EXCLUDED.last_error_details,
        updated_at = NOW()`,
      [
        randomUUID(),
        runId,
        attempt,
        maxAttempts,
        nextAttemptAt,
        lastError.code,
        lastError.message,
        lastError.retryable,
        lastError.details == null ? null : lastError.details,
      ]
    );
  }

  async markDone(runId: string): Promise<void> {
    await this.pool.query("DELETE FROM discovery_run_retries WHERE discovery_run_id=$1", [runId]);
  }

  async markDead(runId: string): Promise<void> {
    await this.pool.query(
      `UPDATE discovery_run_retries
       SET status='dead', updated_at=NOW()
       WHERE discovery_run_id=$1`,
      [runId]
    );
  }

  async claimDue(now: Date, batchSize: number): Promise<DiscoveryRunRetryQueueRecord[]> {
    const result = await this.pool.query(
      `
      WITH due AS (
        SELECT id
        FROM discovery_run_retries
        WHERE status='queued' AND next_attempt_at <= $1
        ORDER BY next_attempt_at ASC
        LIMIT $2
      )
      UPDATE discovery_run_retries r
      SET status='processing', updated_at=NOW()
      FROM due
      WHERE r.id = due.id
      RETURNING r.id, r.discovery_run_id, r.attempt, r.max_attempts, r.next_attempt_at, r.status,
                r.last_error_code, r.last_error_message, r.last_error_retryable, r.last_error_details
      `,
      [now, batchSize]
    );

    return result.rows.map((row) => this.mapRow(row as Record<string, unknown>));
  }

  private mapRow(row: Record<string, unknown>): DiscoveryRunRetryQueueRecord {
    return {
      id: String(row.id),
      runId: String(row.discovery_run_id),
      attempt: Number(row.attempt),
      maxAttempts: Number(row.max_attempts),
      nextAttemptAt: new Date(row.next_attempt_at as string),
      status: String(row.status) as DiscoveryRunRetryQueueRecord["status"],
      lastErrorCode: row.last_error_code == null ? null : String(row.last_error_code),
      lastErrorMessage: row.last_error_message == null ? null : String(row.last_error_message),
      lastErrorRetryable: row.last_error_retryable == null ? null : Boolean(row.last_error_retryable),
      lastErrorDetails: row.last_error_details ?? null,
    };
  }
}

export function createDiscoveryRunRetryQueueRepository(): DiscoveryRunRetryQueueRepository {
  return new DbDiscoveryRunRetryQueueRepository();
}
