import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type MarketChannel,
  type MarketDiscoveryConfig,
  type DiscoveryRunReadModel,
  DiscoveryRunSummary,
} from "../src/polymarket/types";
import {
  createOrAttachRun,
  getRun,
  getLatestRun,
  pruneExpiredRuns,
} from "../src/polymarket/services/discoveryRunService";
import { DiscoveryRunCache } from "../src/polymarket/infra/cache/run-cache";
import { DiscoveryRunRepository } from "../src/polymarket/repositories/discoveryRun.repository";
import { DiscoveryRunEventRepository } from "../src/polymarket/repositories/discoveryRunEvent.repository";
import { DiscoveryChannelRepository } from "../src/polymarket/repositories/discoveryChannel.repository";
import { DiscoveryRunWsScanRepository } from "../src/polymarket/repositories/discoveryWsScan.repository";
import { DiscoveryRunRetryQueueRepository } from "../src/polymarket/repositories/discoveryRunRetryQueue.repository";
import * as marketChannelDiscoveryService from "../src/polymarket/services/marketChannelDiscoveryService";

function makeConfig(): MarketDiscoveryConfig {
  return {
    clobApiUrl: "https://clob.polymarket.com",
    chainId: 137,
    wsConnectTimeoutMs: 12_000,
    wsChunkSize: 500,
    marketFetchTimeoutMs: 15_000,
  };
}

function makeRepositoryMocks() {
  const runs = new Map<string, {
    id: string;
    dedupeKey: string;
    status: "queued" | "running" | "succeeded" | "partial" | "failed";
    clobApiUrl: string;
    chainId: number;
    wsUrl: string | null;
    wsConnectTimeoutMs: number;
    wsChunkSize: number;
    marketFetchTimeoutMs: number;
    requestedAt: string;
    startedAt: string | null;
    completedAt: string | null;
    marketCount: number;
    marketChannelCount: number;
    errorCode: string | null;
    errorMessage: string | null;
    errorRetryable: boolean | null;
    errorDetails: unknown;
    requestId: string;
    expiresAt: string;
  }>();

  const channels = new Map<string, MarketChannel[]>();

  const runRepository: DiscoveryRunRepository = {
    createRun: vi.fn(async (params) => {
      const id = `run-${runs.size + 1}`;
      runs.set(id, {
        id,
        dedupeKey: params.dedupeKey,
        status: params.status,
        clobApiUrl: params.config.clobApiUrl,
        chainId: params.config.chainId,
        wsUrl: params.config.wsUrl ?? null,
        wsConnectTimeoutMs: params.config.wsConnectTimeoutMs,
        wsChunkSize: params.config.wsChunkSize,
        marketFetchTimeoutMs: params.config.marketFetchTimeoutMs,
        requestedAt: new Date().toISOString(),
        startedAt: null,
        completedAt: null,
        marketCount: 0,
        marketChannelCount: 0,
        errorCode: null,
        errorMessage: null,
        errorRetryable: null,
        errorDetails: null,
        requestId: params.requestId,
        expiresAt: params.expiresAt.toISOString(),
      });
      channels.set(id, []);
      return id;
    }),
    findById: vi.fn(async (runId) => {
      const run = runs.get(runId);
      if (!run) return null;

      return {
        ...run,
        requestedAt: new Date(run.requestedAt),
        startedAt: run.startedAt ? new Date(run.startedAt) : null,
        completedAt: run.completedAt ? new Date(run.completedAt) : null,
        expiresAt: new Date(run.expiresAt),
      };
    }),
    findActiveByDedupeKey: vi.fn(async () => null),
    findLatest: vi.fn(async () => {
      const rows = [...runs.values()].sort((a, b) => (a.requestedAt < b.requestedAt ? 1 : -1));
      if (!rows.length) return null;
      const run = rows[0];

      return {
        ...run,
        requestedAt: new Date(run.requestedAt),
        startedAt: run.startedAt ? new Date(run.startedAt) : null,
        completedAt: run.completedAt ? new Date(run.completedAt) : null,
        expiresAt: new Date(run.expiresAt),
      };
    }),
    updateRun: vi.fn(async (runId, patch) => {
      const existing = runs.get(runId);
      if (!existing) {
        return;
      }

      Object.assign(existing, {
        ...patch,
        requestedAt: existing.requestedAt,
        startedAt: patch.startedAt ? patch.startedAt.toISOString() : existing.startedAt,
        completedAt: patch.completedAt ? patch.completedAt.toISOString() : existing.completedAt,
      });
    }),
    pruneExpired: vi.fn(async () => ({
      deleted: 0,
      runs: [],
    })),
  };

  const channelRepository: DiscoveryChannelRepository = {
    replaceChannels: vi.fn(async (runId, rows) => {
      channels.set(runId, rows);
    }),
    listChannels: vi.fn(async (runId, offset, limit) => {
      const all = channels.get(runId) ?? [];
      return {
        items: all.slice(offset, offset + limit),
        total: all.length,
      };
    }),
  };

  const wsScanRepository: DiscoveryRunWsScanRepository = {
    upsertScan: vi.fn(async () => undefined),
    getScan: vi.fn(async () => null),
  };

  const eventRepository: DiscoveryRunEventRepository = {
    appendRunEvent: vi.fn(async () => `event-${runs.size + 1}`),
    listRunEvents: vi.fn(async () => []),
  };

  const retryQueueRepository: DiscoveryRunRetryQueueRepository = {
    get: vi.fn(async () => null),
    upsert: vi.fn(async () => undefined),
    markDone: vi.fn(async () => undefined),
    markDead: vi.fn(async () => undefined),
    claimDue: vi.fn(async () => []),
  };

  return {
    runRepository,
    channelRepository,
    wsScanRepository,
    eventRepository,
    retryQueueRepository,
  };
}

function makeCache(activeRunId?: string, slot = true): DiscoveryRunCache {
  let activeKey = activeRunId;
  let latestId = "";
  let semaphore = 0;

  return {
    getLatestRunId: vi.fn(async () => latestId || null),
    setLatestRunId: vi.fn(async (scope, runId) => {
      latestId = runId;
    }),
    clearLatestRunId: vi.fn(async () => {
      latestId = "";
    }),

    getCachedRun: vi.fn(async () => null),
    setCachedRun: vi.fn(async () => undefined),
    clearCachedRun: vi.fn(async () => undefined),

    getActiveRunIdByDedupeKey: vi.fn(async () => activeKey),
    setActiveRunIdByDedupeKey: vi.fn(async () => {
      return !activeKey;
    }),
    deleteActiveRunIdByDedupeKey: vi.fn(async () => {
      activeKey = undefined;
    }),

    acquireSlot: vi.fn(async () => {
      if (!slot || semaphore + 1 > 1) {
        return { ok: false, active: semaphore + 1, limit: 1 };
      }
      semaphore += 1;
      return { ok: true, active: semaphore, limit: 1 };
    }),
    releaseSlot: vi.fn(async () => {
      semaphore = Math.max(0, semaphore - 1);
    }),
  };
}

describe("discovery run service", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });
  it("returns active run for identical in-flight dedupe key", async () => {
    const config = makeConfig();
    const { runRepository, channelRepository, wsScanRepository, eventRepository, retryQueueRepository } = makeRepositoryMocks();

    const existing: DiscoveryRunSummary = {
      runId: "active-1",
      status: "running",
      dedupeKey: JSON.stringify({
        clobApiUrl: config.clobApiUrl,
        chainId: config.chainId,
        wsUrl: null,
        wsConnectTimeoutMs: config.wsConnectTimeoutMs,
        wsChunkSize: config.wsChunkSize,
        marketFetchTimeoutMs: config.marketFetchTimeoutMs,
      }),
      pollUrl: "/api/polymarket/market-channels/runs/active-1",
      requestId: "req-1",
    };

    (runRepository.findById as any).mockResolvedValue({
      id: "active-1",
      dedupeKey: existing.dedupeKey,
      status: "running",
      clobApiUrl: config.clobApiUrl,
      chainId: config.chainId,
      wsUrl: null,
      wsConnectTimeoutMs: config.wsConnectTimeoutMs,
      wsChunkSize: config.wsChunkSize,
      marketFetchTimeoutMs: config.marketFetchTimeoutMs,
      requestedAt: new Date(),
      startedAt: new Date(),
      completedAt: null,
      marketCount: 0,
      marketChannelCount: 0,
      errorCode: null,
      errorMessage: null,
      errorRetryable: null,
      errorDetails: null,
      requestId: "req-1",
      expiresAt: new Date(),
    });

    const result = await createOrAttachRun(config, "req-1", {
      runRepository,
      channelRepository,
      wsScanRepository,
      eventRepository,
      retryQueueRepository,
      cache: makeCache("active-1"),
      runTtlSec: 3600,
      cacheTtlSec: 600,
      concurrencyLimit: 1,
      semaphoreTtlSec: 30,
      scope: "default",
    });

    expect(result.runId).toBe("active-1");
    expect(runRepository.createRun).not.toHaveBeenCalled();
  });

  it("returns explicit concurrency limit when slot is unavailable", async () => {
    const config = makeConfig();
    const { runRepository, channelRepository, wsScanRepository, eventRepository, retryQueueRepository } = makeRepositoryMocks();

    await expect(
      createOrAttachRun(config, "req-1", {
        runRepository,
        channelRepository,
        wsScanRepository,
        eventRepository,
        retryQueueRepository,
        cache: makeCache(undefined, false),
        runTtlSec: 3600,
        cacheTtlSec: 600,
        concurrencyLimit: 1,
        semaphoreTtlSec: 30,
        scope: "default",
      })
    ).rejects.toMatchObject({
      code: "discovery_concurrency_limit",
      status: 429,
    });

    expect(runRepository.createRun).not.toHaveBeenCalled();
  });

  it("returns paged run data", async () => {
    const config = makeConfig();
    const { runRepository, channelRepository, wsScanRepository, eventRepository, retryQueueRepository } = makeRepositoryMocks();

    const run: DiscoveryRunReadModel = {
      run: {
        id: "run-1",
        status: "succeeded",
        dedupeKey: JSON.stringify({
          clobApiUrl: config.clobApiUrl,
          chainId: config.chainId,
          wsUrl: null,
          wsConnectTimeoutMs: config.wsConnectTimeoutMs,
          wsChunkSize: config.wsChunkSize,
          marketFetchTimeoutMs: config.marketFetchTimeoutMs,
        }),
        requestedAt: new Date().toISOString(),
        source: {
          clobApiUrl: config.clobApiUrl,
          chainId: config.chainId,
          wsConnectTimeoutMs: config.wsConnectTimeoutMs,
          wsChunkSize: config.wsChunkSize,
          marketFetchTimeoutMs: config.marketFetchTimeoutMs,
        },
        marketCount: 1,
        marketChannelCount: 1,
        requestId: "req-1",
      },
      channels: {
        items: [{ assetId: "0xabc", conditionId: "cond", question: "Q", outcome: "YES", marketSlug: "slug" }],
        page: {
          offset: 0,
          limit: 1,
          total: 1,
          hasMore: false,
        },
      },
      wsScan: null,
    };

    (channelRepository.listChannels as any).mockResolvedValue({
      items: [{ assetId: "0xabc", conditionId: "cond", question: "Q", outcome: "YES", marketSlug: "slug" }],
      total: 1,
    });

    const row = {
      id: "run-1",
      dedupeKey: run.run.dedupeKey,
      status: "succeeded",
      clobApiUrl: config.clobApiUrl,
      chainId: config.chainId,
      wsUrl: null,
      wsConnectTimeoutMs: config.wsConnectTimeoutMs,
      wsChunkSize: config.wsChunkSize,
      marketFetchTimeoutMs: config.marketFetchTimeoutMs,
      requestedAt: new Date(),
      startedAt: new Date(),
      completedAt: new Date(),
      marketCount: 1,
      marketChannelCount: 1,
      errorCode: null,
      errorMessage: null,
      errorRetryable: null,
      errorDetails: null,
      requestId: "req-1",
      expiresAt: new Date(),
    };

    (runRepository.findById as any).mockResolvedValue(row);

    const response = await getRun("run-1", 0, 1, {
      runRepository,
      channelRepository,
      wsScanRepository,
      eventRepository,
      retryQueueRepository,
      cache: makeCache("run-1"),
      runTtlSec: 3600,
      cacheTtlSec: 600,
      concurrencyLimit: 1,
      semaphoreTtlSec: 30,
      scope: "default",
    });

    expect(response).toMatchObject({
      run: {
        id: "run-1",
        status: "succeeded",
      },
      channels: {
        items: [{ assetId: "0xabc", conditionId: "cond", question: "Q", outcome: "YES", marketSlug: "slug" }],
        page: {
          offset: 0,
          limit: 1,
          total: 1,
          hasMore: false,
        },
      },
    });
  });

  it("attaches to an active DB row when the in-memory/redis lock is absent", async () => {
    const config = makeConfig();
    const { runRepository, channelRepository, wsScanRepository, eventRepository, retryQueueRepository } = makeRepositoryMocks();

    (runRepository.findActiveByDedupeKey as any).mockResolvedValue({
      id: "active-db",
      dedupeKey: JSON.stringify({
        clobApiUrl: config.clobApiUrl,
        chainId: config.chainId,
        wsUrl: null,
        wsConnectTimeoutMs: config.wsConnectTimeoutMs,
        wsChunkSize: config.wsChunkSize,
        marketFetchTimeoutMs: config.marketFetchTimeoutMs,
      }),
      status: "queued",
      clobApiUrl: config.clobApiUrl,
      chainId: config.chainId,
      wsUrl: null,
      wsConnectTimeoutMs: config.wsConnectTimeoutMs,
      wsChunkSize: config.wsChunkSize,
      marketFetchTimeoutMs: config.marketFetchTimeoutMs,
      requestedAt: new Date(),
      startedAt: null,
      completedAt: null,
      marketCount: 0,
      marketChannelCount: 0,
      errorCode: null,
      errorMessage: null,
      errorRetryable: null,
      errorDetails: null,
      requestId: "req-1",
      expiresAt: new Date(),
    });

    const result = await createOrAttachRun(config, "req-1", {
      runRepository,
      channelRepository,
      wsScanRepository,
      eventRepository,
      retryQueueRepository,
      cache: makeCache(undefined),
      runTtlSec: 3600,
      cacheTtlSec: 600,
      concurrencyLimit: 1,
      semaphoreTtlSec: 30,
      scope: "default",
    });

    expect(result.runId).toBe("active-db");
    expect(runRepository.createRun).not.toHaveBeenCalled();
  });

  it("falls back to DB latest when cached latest run id is missing", async () => {
    const config = makeConfig();
    const { runRepository, channelRepository, wsScanRepository, eventRepository, retryQueueRepository } = makeRepositoryMocks();
    const cache = makeCache("stale-latest-id");

    const latestRow = {
      id: "run-latest",
      dedupeKey: JSON.stringify({
        clobApiUrl: config.clobApiUrl,
        chainId: config.chainId,
        wsUrl: null,
        wsConnectTimeoutMs: config.wsConnectTimeoutMs,
        wsChunkSize: config.wsChunkSize,
        marketFetchTimeoutMs: config.marketFetchTimeoutMs,
      }),
      status: "succeeded",
      clobApiUrl: config.clobApiUrl,
      chainId: config.chainId,
      wsUrl: null,
      wsConnectTimeoutMs: config.wsConnectTimeoutMs,
      wsChunkSize: config.wsChunkSize,
      marketFetchTimeoutMs: config.marketFetchTimeoutMs,
      requestedAt: new Date(),
      startedAt: new Date(),
      completedAt: new Date(),
      marketCount: 10,
      marketChannelCount: 10,
      errorCode: null,
      errorMessage: null,
      errorRetryable: null,
      errorDetails: null,
      requestId: "req-latest",
      expiresAt: new Date(),
    };

    (runRepository.findById as any).mockImplementation(async (runId: string) => {
      if (runId === "stale-latest-id") {
        return null;
      }

      if (runId === "run-latest") {
        return latestRow;
      }

      return null;
    });

    (runRepository.findLatest as any).mockResolvedValue(latestRow);

    const read = await getLatestRun({
      runRepository,
      channelRepository,
      wsScanRepository,
      eventRepository,
      retryQueueRepository,
      cache,
      runTtlSec: 3600,
      cacheTtlSec: 600,
      concurrencyLimit: 1,
      semaphoreTtlSec: 30,
      scope: "default",
    });

    expect(read.run.id).toBe("run-latest");
    expect(read.run.marketCount).toBe(10);
    expect(runRepository.findLatest).toHaveBeenCalledTimes(1);
    expect((cache.setLatestRunId as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("default", "run-latest", 600);
  });

  it("schedules retry entry for retryable failure when enabled", async () => {
    const config = makeConfig();
    const { runRepository, channelRepository, wsScanRepository, eventRepository, retryQueueRepository } = makeRepositoryMocks();

    vi.spyOn(marketChannelDiscoveryService, "discoverMarketChannels").mockRejectedValue(new Error("market discovery timeout"));

    await createOrAttachRun(config, "req-retry", {
      runRepository,
      channelRepository,
      wsScanRepository,
      eventRepository,
      retryQueueRepository,
      cache: makeCache(undefined),
      runTtlSec: 3600,
      cacheTtlSec: 600,
      concurrencyLimit: 1,
      semaphoreTtlSec: 30,
      retryEnabled: true,
      retryMaxAttempts: 3,
      retryBaseDelayMs: 1,
      retryMaxDelayMs: 1,
      retryWorkerEnabled: false,
      retryWorkerBatchSize: 1,
      retryWorkerIntervalSeconds: 1,
      scope: "default",
    });

    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(retryQueueRepository.upsert).toHaveBeenCalledWith(
      "run-1",
      1,
      3,
      expect.any(Date),
      expect.objectContaining({
        code: "clob_request_timeout",
        message: expect.any(String),
        retryable: true,
      })
    );
    expect(runRepository.updateRun).toHaveBeenCalledWith(
      "run-1",
      expect.objectContaining({
        status: "queued",
        errorCode: "clob_request_timeout",
        errorRetryable: true,
      })
    );
  });

  it("cleans stale cache and dedupe state when pruning expired runs", async () => {
    const config = makeConfig();
    const { runRepository, channelRepository, wsScanRepository, eventRepository, retryQueueRepository } = makeRepositoryMocks();
    const cache = makeCache();
    const pruneSpy = runRepository.pruneExpired as unknown as ReturnType<typeof vi.fn>;

    (runRepository.pruneExpired as any).mockResolvedValue({
      deleted: 1,
      runs: [{ runId: "run-1", dedupeKey: "dedupe-1" }],
    });

    const deleted = await pruneExpiredRuns({
      runRepository,
      channelRepository,
      wsScanRepository,
      eventRepository,
      retryQueueRepository,
      cache,
      runTtlSec: 3600,
      cacheTtlSec: 600,
      concurrencyLimit: 1,
      semaphoreTtlSec: 30,
      scope: "default",
    });

    expect(deleted).toBe(1);
    expect((cache.clearCachedRun as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("run-1");
    expect((cache.deleteActiveRunIdByDedupeKey as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("dedupe-1");
    expect((retryQueueRepository.markDead as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith("run-1");
    expect(pruneSpy).toHaveBeenCalled();
  });
});