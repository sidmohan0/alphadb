import { randomUUID } from "crypto";
import { Pool } from "pg";

import { MarketChannel } from "../types";
import { getPgPool } from "../infra/db/postgres";

export interface DiscoveryChannelRow extends MarketChannel {
  id: string;
  discoveryRunId: string;
}

export interface ChannelPage {
  items: MarketChannel[];
  total: number;
}

export interface DiscoveryChannelRepository {
  replaceChannels(runId: string, channels: MarketChannel[]): Promise<void>;
  listChannels(runId: string, offset: number, limit: number): Promise<ChannelPage>;
}

interface DbDiscoveryChannelRepositoryOptions {
  pool?: Pool;
}

export class DbDiscoveryChannelRepository implements DiscoveryChannelRepository {
  private readonly pool: Pool;

  constructor(options?: DbDiscoveryChannelRepositoryOptions) {
    this.pool = options?.pool ?? getPgPool();
  }

  async replaceChannels(runId: string, channels: MarketChannel[]): Promise<void> {
    const client = await this.pool.connect();

    try {
      await client.query("BEGIN");
      await client.query("DELETE FROM discovery_run_channels WHERE discovery_run_id=$1", [runId]);

      for (const channel of channels) {
        await client.query(
          `INSERT INTO discovery_run_channels
            (id, discovery_run_id, asset_id, condition_id, question, outcome, market_slug)
          VALUES
            ($1, $2, $3, $4, $5, $6, $7)
          ON CONFLICT (discovery_run_id, asset_id) DO UPDATE SET
            condition_id = EXCLUDED.condition_id,
            question = EXCLUDED.question,
            outcome = EXCLUDED.outcome,
            market_slug = EXCLUDED.market_slug`,
          [
            randomUUID(),
            runId,
            channel.assetId,
            channel.conditionId ?? null,
            channel.question ?? null,
            channel.outcome ?? null,
            channel.marketSlug ?? null,
          ]
        );
      }

      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async listChannels(runId: string, offset: number, limit: number): Promise<ChannelPage> {
    const [listResult, countResult] = await Promise.all([
      this.pool.query(
        "SELECT asset_id, condition_id, question, outcome, market_slug FROM discovery_run_channels WHERE discovery_run_id=$1 ORDER BY id ASC LIMIT $2 OFFSET $3",
        [runId, limit, offset]
      ),
      this.pool.query("SELECT COUNT(*)::int AS total FROM discovery_run_channels WHERE discovery_run_id=$1", [runId]),
    ]);

    const items = listResult.rows.map((row) => ({
      assetId: String(row.asset_id),
      conditionId: row.condition_id == null ? undefined : String(row.condition_id),
      question: row.question == null ? undefined : String(row.question),
      outcome: row.outcome == null ? undefined : String(row.outcome),
      marketSlug: row.market_slug == null ? undefined : String(row.market_slug),
    }));

    const total = Number((countResult.rows[0] as { total: number }).total ?? 0);
    return { items, total };
  }
}

export function createDiscoveryChannelRepository(): DiscoveryChannelRepository {
  return new DbDiscoveryChannelRepository();
}
