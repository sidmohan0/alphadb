import { randomUUID } from "crypto";
import { Pool } from "pg";

import { getPgPool } from "../infra/db/postgres";

export interface DiscoveryRunEvent {
  id: string;
  runId: string;
  eventType: string;
  message: string;
  metadata?: unknown;
  eventAt: Date;
}

export interface DiscoveryRunEventRepository {
  appendRunEvent(runId: string, eventType: string, message: string, metadata?: unknown): Promise<string>;
  listRunEvents(runId: string): Promise<DiscoveryRunEvent[]>;
}

interface DbDiscoveryRunEventRepositoryOptions {
  pool?: Pool;
}

export class DbDiscoveryRunEventRepository implements DiscoveryRunEventRepository {
  private readonly pool: Pool;

  constructor(options?: DbDiscoveryRunEventRepositoryOptions) {
    this.pool = options?.pool ?? getPgPool();
  }

  async appendRunEvent(runId: string, eventType: string, message: string, metadata?: unknown): Promise<string> {
    const eventId = randomUUID();
    await this.pool.query(
      `INSERT INTO discovery_run_events
        (id, discovery_run_id, event_type, message, metadata)
      VALUES
        ($1, $2, $3, $4, $5::jsonb)`,
      [
        eventId,
        runId,
        eventType,
        message,
        metadata == null ? null : JSON.stringify(metadata),
      ]
    );

    return eventId;
  }

  async listRunEvents(runId: string): Promise<DiscoveryRunEvent[]> {
    const result = await this.pool.query(
      "SELECT id, discovery_run_id, event_type, message, metadata, event_at FROM discovery_run_events WHERE discovery_run_id=$1 ORDER BY event_at ASC",
      [runId]
    );

    return result.rows.map((row) => ({
      id: String(row.id),
      runId: String(row.discovery_run_id),
      eventType: String(row.event_type),
      message: String(row.message),
      metadata: row.metadata ?? null,
      eventAt: new Date(row.event_at as string),
    }));
  }
}

export function createDiscoveryRunEventRepository(): DiscoveryRunEventRepository {
  return new DbDiscoveryRunEventRepository();
}
