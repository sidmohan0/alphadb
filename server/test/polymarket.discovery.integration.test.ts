import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "fs";
import { resolve } from "path";

import { createDiscoveryRunRepository } from "../src/polymarket/repositories/discoveryRun.repository";
import { createDiscoveryChannelRepository } from "../src/polymarket/repositories/discoveryChannel.repository";
import { createDiscoveryRunWsScanRepository } from "../src/polymarket/repositories/discoveryWsScan.repository";
import { createDiscoveryRunCache } from "../src/polymarket/infra/cache/run-cache";
import { closeRedisClient } from "../src/polymarket/infra/cache/redis";
import { closePgPool, getPgPool } from "../src/polymarket/infra/db/postgres";
import { getRun, pruneExpiredRuns } from "../src/polymarket/services/discoveryRunService";

const hasIntegrationConfig = Boolean(process.env.DISCOVERY_INTEGRATION_TESTS && process.env.DATABASE_URL && process.env.REDIS_URL);

if (hasIntegrationConfig) {
  describe("discovery run persistence integration (Postgres + Redis)", () => {
    const runRepository = createDiscoveryRunRepository();
    const channelRepository = createDiscoveryChannelRepository();
    const wsScanRepository = createDiscoveryRunWsScanRepository();
    const cache = createDiscoveryRunCache(false);
    const scope = `integration-${Date.now()}`;

    const commonConfig = {
      clobApiUrl: "https://clob.polymarket.com",
      chainId: 137,
      wsUrl: undefined as string | undefined,
      wsConnectTimeoutMs: 12_000,
      wsChunkSize: 500,
      marketFetchTimeoutMs: 15_000,
    };

    beforeAll(async () => {
      const pool = getPgPool();
      const localSchemaPath = resolve(process.cwd(), "src/polymarket/infra/db/schemas.sql");
      const fallbackSchemaPath = resolve(process.cwd(), "server/src/polymarket/infra/db/schemas.sql");
      const schemaPath = existsSync(localSchemaPath) ? localSchemaPath : fallbackSchemaPath;
      const schema = readFileSync(schemaPath, "utf8");
      await pool.query(schema);
    });

    afterEach(async () => {
      const pool = getPgPool();
      await pool.query("DELETE FROM discovery_runs WHERE dedupe_key LIKE $1", ["%integration-%"]);
    });

    afterAll(async () => {
      await closePgPool();
      await closeRedisClient();
    });

    it("persists run payloads and writes read-model cache", async () => {
      const dedupeKey = JSON.stringify({
        ...commonConfig,
        marker: `it-run-${Date.now()}`,
      });

      const runId = `run-${Date.now()}-${Math.random().toString(16).slice(2)}`;

      await runRepository.createRun({
        dedupeKey,
        status: "succeeded",
        config: {
          ...commonConfig,
        },
        requestId: "integration-test",
        expiresAt: new Date(Date.now() + 60_000),
        requestedAt: new Date(),
        runId,
      });

      await channelRepository.replaceChannels(runId, [
        {
          assetId: "0xabcdef123",
          conditionId: "cond-1",
          question: "Will this integration test pass?",
          marketSlug: "integration",
          outcome: "YES",
        },
      ]);

      await wsScanRepository.upsertScan(runId, {
        wsUrl: "wss://example.com/market",
        connected: true,
        observedChannels: ["0xabcdef123"],
        messageCount: 2,
        sampleEventCount: 1,
        errors: [],
      });

      const run = await getRun(runId, 0, 10, {
        runRepository,
        channelRepository,
        wsScanRepository,
        cache,
        runTtlSec: 60,
        cacheTtlSec: 60,
        concurrencyLimit: 4,
        semaphoreTtlSec: 30,
        scope,
      });

      expect(run.run.id).toBe(runId);
      expect(run.run.status).toBe("succeeded");
      expect(run.channels.items).toHaveLength(1);
      expect(run.channels.items[0]).toMatchObject({
        assetId: "0xabcdef123",
        question: "Will this integration test pass?",
      });

      const cached = await cache.getCachedRun(runId);
      expect(cached?.run.id).toBe(runId);
      expect(cached?.channels.items[0].assetId).toBe("0xabcdef123");
    });

    it("prunes expired runs via service-level cleanup", async () => {
      const dedupeKey = JSON.stringify({
        ...commonConfig,
        marker: `it-expired-${Date.now()}`,
      });

      const expiredRunId = `run-expired-${Date.now()}-${Math.random().toString(16).slice(2)}`;

      await runRepository.createRun({
        dedupeKey,
        status: "queued",
        config: {
          ...commonConfig,
        },
        requestId: "integration-test",
        expiresAt: new Date(Date.now() - 1000),
        requestedAt: new Date(Date.now() - 1000),
        runId: expiredRunId,
      });

      const deleted = await pruneExpiredRuns({
        runRepository,
        channelRepository,
        wsScanRepository,
        cache,
        runTtlSec: 60,
        cacheTtlSec: 60,
        concurrencyLimit: 4,
        semaphoreTtlSec: 30,
        scope,
      });

      expect(deleted).toBeGreaterThan(0);

      const afterPrune = await runRepository.findById(expiredRunId);
      expect(afterPrune).toBeNull();
    });
  });
} else {
  describe.skip("discovery run persistence integration (Postgres + Redis)", () => {
    it("is skipped when integration env vars are not provided", () => {
      expect(true).toBe(true);
    });
  });
}
