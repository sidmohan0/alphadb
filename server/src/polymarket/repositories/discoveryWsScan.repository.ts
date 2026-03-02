import { randomUUID } from "crypto";
import { Pool } from "pg";

import { WsScanSummary } from "../types";
import { getPgPool } from "../infra/db/postgres";

export interface DiscoveryRunWsScanRepository {
  upsertScan(runId: string, scan: WsScanSummary): Promise<void>;
  getScan(runId: string): Promise<WsScanSummary | null>;
}

interface DbDiscoveryRunWsScanRepositoryOptions {
  pool?: Pool;
}

export class DbDiscoveryRunWsScanRepository implements DiscoveryRunWsScanRepository {
  private readonly pool: Pool;

  constructor(options?: DbDiscoveryRunWsScanRepositoryOptions) {
    this.pool = options?.pool ?? getPgPool();
  }

  async upsertScan(runId: string, scan: WsScanSummary): Promise<void> {
    await this.pool.query(
      `INSERT INTO discovery_run_ws_scans
      (id, discovery_run_id, ws_url, connected, observed_channels, message_count, sample_event_count, errors)
      VALUES
      ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
      ON CONFLICT (discovery_run_id) DO UPDATE SET
        ws_url = EXCLUDED.ws_url,
        connected = EXCLUDED.connected,
        observed_channels = EXCLUDED.observed_channels,
        message_count = EXCLUDED.message_count,
        sample_event_count = EXCLUDED.sample_event_count,
        errors = EXCLUDED.errors,
        created_at = NOW()` ,
      [
        randomUUID(),
        runId,
        scan.wsUrl,
        scan.connected,
        scan.observedChannels,
        scan.messageCount,
        scan.sampleEventCount,
        JSON.stringify(scan.errors),
      ]
    );
  }

  async getScan(runId: string): Promise<WsScanSummary | null> {
    const result = await this.pool.query(
      "SELECT ws_url, connected, observed_channels, message_count, sample_event_count, errors FROM discovery_run_ws_scans WHERE discovery_run_id=$1 LIMIT 1",
      [runId]
    );

    if (!result.rowCount) {
      return null;
    }

    const row = result.rows[0] as {
      ws_url: unknown;
      connected: unknown;
      observed_channels: unknown;
      message_count: unknown;
      sample_event_count: unknown;
      errors: unknown;
    };

    return {
      wsUrl: String(row.ws_url),
      connected: Boolean(row.connected),
      observedChannels: Array.isArray(row.observed_channels) ? (row.observed_channels as string[]) : [],
      messageCount: Number(row.message_count),
      sampleEventCount: Number(row.sample_event_count),
      errors: Array.isArray(row.errors)
        ? (row.errors as string[])
        : typeof row.errors === "string"
          ? JSON.parse(row.errors)
          : [],
    };
  }
}

export function createDiscoveryRunWsScanRepository(): DiscoveryRunWsScanRepository {
  return new DbDiscoveryRunWsScanRepository();
}
