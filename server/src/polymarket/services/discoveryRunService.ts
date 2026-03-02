import { randomUUID } from "crypto";

import {
  DEFAULT_MARKET_DISCOVERY_CONCURRENCY_LIMIT,
  DiscoveryRunReadModel,
  DiscoveryRunSummary,
  MarketChannel,
  MarketChannelRunResult,
  MarketDiscoveryConfig,
} from "../types";
import { assertDiscoveryConfig, discoverMarketChannels } from "./marketChannelDiscoveryService";
import { mapDiscoveryConcurrencyLimit, mapRunNotFound, toHttpErrorResponse, PolymarketDiscoveryError } from "../errors";
import { createDiscoveryChannelRepository, DiscoveryChannelRepository } from "../repositories/discoveryChannel.repository";
import {
  createDiscoveryRunRepository,
  DiscoveryRunPatch,
  DiscoveryRunRecord,
  DiscoveryRunRepository,
  rowToReadModel,
} from "../repositories/discoveryRun.repository";
import { createDiscoveryRunWsScanRepository, DiscoveryRunWsScanRepository } from "../repositories/discoveryWsScan.repository";
import { DiscoveryRunCache, createDiscoveryRunCache } from "../infra/cache/run-cache";
import {
  createDiscoveryRunEventRepository,
  DiscoveryRunEventRepository,
} from "../repositories/discoveryRunEvent.repository";

const DEFAULT_SCOPE = "default";

type LogContext = Record<string, unknown>;

interface DiscoveryServiceDeps {
  runRepository: DiscoveryRunRepository;
  channelRepository: DiscoveryChannelRepository;
  wsScanRepository: DiscoveryRunWsScanRepository;
  eventRepository: DiscoveryRunEventRepository;
  cache: DiscoveryRunCache;
  runTtlSec: number;
  cacheTtlSec: number;
  concurrencyLimit: number;
  semaphoreTtlSec: number;
  scope: string;
}

function parseIntEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }

  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 && Number.isInteger(parsed) ? parsed : fallback;
}

function resolveDeps(overrides?: Partial<DiscoveryServiceDeps>): DiscoveryServiceDeps {
  return {
    runRepository: overrides?.runRepository ?? createDiscoveryRunRepository(),
    channelRepository: overrides?.channelRepository ?? createDiscoveryChannelRepository(),
    wsScanRepository: overrides?.wsScanRepository ?? createDiscoveryRunWsScanRepository(),
    eventRepository: overrides?.eventRepository ?? createDiscoveryRunEventRepository(),
    cache: overrides?.cache ?? createDiscoveryRunCache(process.env.DISCOVERY_RUN_ALLOW_IN_MEMORY_CACHE === "1"),
    runTtlSec: overrides?.runTtlSec ?? parseIntEnv("DISCOVERY_RUN_TTL_SECONDS", 60 * 60 * 24),
    cacheTtlSec: overrides?.cacheTtlSec ?? parseIntEnv("DISCOVERY_RUN_CACHE_TTL_SECONDS", 10 * 60),
    concurrencyLimit: overrides?.concurrencyLimit ?? parseIntEnv("MARKET_DISCOVERY_CONCURRENCY_LIMIT", DEFAULT_MARKET_DISCOVERY_CONCURRENCY_LIMIT),
    semaphoreTtlSec: overrides?.semaphoreTtlSec ?? parseIntEnv("DISCOVERY_SEMAPHORE_TTL_SECONDS", 60),
    scope: overrides?.scope ?? process.env.DISCOVERY_SCOPE ?? DEFAULT_SCOPE,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildDedupeKey(config: MarketDiscoveryConfig): string {
  return JSON.stringify({
    clobApiUrl: config.clobApiUrl,
    chainId: config.chainId,
    wsUrl: config.wsUrl ?? null,
    wsConnectTimeoutMs: config.wsConnectTimeoutMs,
    wsChunkSize: config.wsChunkSize,
    marketFetchTimeoutMs: config.marketFetchTimeoutMs,
  });
}

function dedupeLockTtlSec(deps: DiscoveryServiceDeps): number {
  // Keep lock alive for the expected run TTL while still allowing conservative failover.
  return Math.max(deps.runTtlSec, 1);
}

function logDiscoveryEvent(message: string, context: LogContext): void {
  if (process.env.NODE_ENV === "test" && process.env.DISCOVERY_RUN_LOGS !== "1") {
    return;
  }

  console.log(`[discovery-run] ${message}`, JSON.stringify(context));
}

async function emitRunEvent(
  eventRepository: DiscoveryRunEventRepository,
  runId: string,
  eventType: string,
  message: string,
  metadata?: Record<string, unknown>
): Promise<void> {
  try {
    await eventRepository.appendRunEvent(runId, eventType, message, metadata);
  } catch (error) {
    logDiscoveryEvent("run_event_failed", {
      runId,
      eventType,
      message,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

function toRunModel(
  run: DiscoveryRunRecord,
  channels: { items: MarketChannel[]; total: number },
  offset: number,
  limit: number,
  wsScan: DiscoveryRunReadModel["wsScan"]
): DiscoveryRunReadModel {
  const base = rowToReadModel(run);

  return {
    run: {
      ...base.run,
    },
    channels: {
      items: channels.items,
      page: {
        offset,
        limit,
        total: channels.total,
        hasMore: offset + channels.items.length < channels.total,
      },
    },
    wsScan,
  };
}

function toShell(run: DiscoveryRunRecord): DiscoveryRunSummary {
  return {
    runId: run.id,
    status: run.status,
    dedupeKey: run.dedupeKey,
    pollUrl: `/api/polymarket/market-channels/runs/${run.id}`,
    requestId: run.requestId,
  };
}

async function refreshRunCache(deps: DiscoveryServiceDeps, runId: string, readModel: DiscoveryRunReadModel): Promise<void> {
  await Promise.all([
    deps.cache.setCachedRun(runId, readModel, deps.cacheTtlSec),
    deps.cache.setLatestRunId(deps.scope, runId, deps.cacheTtlSec),
  ]);
}

async function attachRunIfActive(deps: DiscoveryServiceDeps, dedupeKey: string): Promise<DiscoveryRunRecord | null> {
  const cachedRunId = await deps.cache.getActiveRunIdByDedupeKey(dedupeKey);
  if (cachedRunId) {
    const cachedRun = await deps.runRepository.findById(cachedRunId);
    if (cachedRun) {
      if (cachedRun.status === "queued" || cachedRun.status === "running") {
        return cachedRun;
      }

      await deps.cache.deleteActiveRunIdByDedupeKey(dedupeKey);
      return null;
    }

    await deps.cache.deleteActiveRunIdByDedupeKey(dedupeKey);
  }

  const dbRun = await deps.runRepository.findActiveByDedupeKey(dedupeKey);
  if (!dbRun) {
    return null;
  }

  await deps.cache.setActiveRunIdByDedupeKey(dedupeKey, dbRun.id, dedupeLockTtlSec(deps));
  return dbRun;
}

export async function createOrAttachRun(
  config: MarketDiscoveryConfig,
  requestId?: string,
  overrides?: Partial<DiscoveryServiceDeps>,
  attempt = 0
): Promise<DiscoveryRunSummary> {
  const deps = resolveDeps(overrides);
  assertDiscoveryConfig(config);

  const requestIdSafe = requestId || randomUUID();
  const dedupeKey = buildDedupeKey(config);

  const active = await attachRunIfActive(deps, dedupeKey);
  if (active) {
    logDiscoveryEvent("run_attached", {
      action: "attach",
      runId: active.id,
      dedupeKey,
      requestId: requestIdSafe,
    });
    return toShell(active);
  }

  const runId = randomUUID();
  const lockAcquired = await deps.cache.setActiveRunIdByDedupeKey(dedupeKey, runId, dedupeLockTtlSec(deps));
  if (!lockAcquired) {
    const raced = await attachRunIfActive(deps, dedupeKey);
    if (raced) {
      logDiscoveryEvent("run_race_attach", {
        action: "attach-after-lock-fail",
        runId: raced.id,
        dedupeKey,
        requestId: requestIdSafe,
      });
      return toShell(raced);
    }

    if (attempt < 1) {
      return createOrAttachRun(config, requestIdSafe, overrides, attempt + 1);
    }

    logDiscoveryEvent("run_dedupe_lock_denied", {
      action: "dedupe",
      dedupeKey,
      requestId: requestIdSafe,
    });

    throw mapDiscoveryConcurrencyLimit(deps.concurrencyLimit, {
      operation: "createOrAttachRun",
      dedupeKey,
      note: "Unable to reserve dedupe lock",
    });
  }

  let slotAcquired = false;
  try {
    const slot = await deps.cache.acquireSlot("global", deps.concurrencyLimit, deps.semaphoreTtlSec);
    if (!slot.ok) {
      throw mapDiscoveryConcurrencyLimit(deps.concurrencyLimit, {
        operation: "createOrAttachRun",
        active: slot.active,
      });
    }
    slotAcquired = true;

    const createdRunId = await deps.runRepository.createRun({
      dedupeKey,
      status: "queued",
      config,
      requestId: requestIdSafe,
      expiresAt: new Date(Date.now() + deps.runTtlSec * 1000),
      requestedAt: new Date(),
      runId,
    });

    await deps.cache.setActiveRunIdByDedupeKey(dedupeKey, createdRunId, dedupeLockTtlSec(deps));
    await deps.cache.setLatestRunId(deps.scope, createdRunId, deps.cacheTtlSec);

    logDiscoveryEvent("run_created", {
      action: "created",
      runId: createdRunId,
      dedupeKey,
      requestId: requestIdSafe,
    });

    await emitRunEvent(
      deps.eventRepository,
      createdRunId,
      "run_created",
      "queued run created",
      {
        requestId: requestIdSafe,
        dedupeKey,
      }
    );

    void runDiscoveryInBackground(createdRunId, config, requestIdSafe, dedupeKey, deps);

    return {
      runId: createdRunId,
      status: "queued",
      dedupeKey,
      pollUrl: `/api/polymarket/market-channels/runs/${createdRunId}`,
      requestId: requestIdSafe,
    };
  } catch (error) {
    await deps.cache.deleteActiveRunIdByDedupeKey(dedupeKey);
    if (slotAcquired) {
      await deps.cache.releaseSlot("global");
    }

    throw error;
  }
}

export async function getRun(
  runId: string,
  offset: number,
  limit: number,
  overrides?: Partial<DiscoveryServiceDeps>
): Promise<DiscoveryRunReadModel> {
  const deps = resolveDeps(overrides);

  const runRecord = await deps.runRepository.findById(runId);
  if (!runRecord) {
    throw mapRunNotFound(`Run ${runId} was not found`);
  }

  const [channels, wsScan] = await Promise.all([
    deps.channelRepository.listChannels(runId, offset, limit),
    deps.wsScanRepository.getScan(runId),
  ]);

  const runModel = toRunModel(
    runRecord,
    channels,
    offset,
    limit,
    wsScan
  );

  await refreshRunCache(deps, runId, runModel);
  return runModel;
}

export async function getLatestRun(overrides?: Partial<DiscoveryServiceDeps>): Promise<DiscoveryRunReadModel> {
  const deps = resolveDeps(overrides);

  const cachedId = await deps.cache.getLatestRunId(deps.scope);
  if (cachedId) {
    try {
      return await getRun(cachedId, 0, 100, deps);
    } catch (error) {
      if (!(error instanceof PolymarketDiscoveryError && error.code === "run_not_found")) {
        throw error;
      }
    }
  }

  const latest = await deps.runRepository.findLatest();
  if (!latest) {
    throw mapRunNotFound("No discovery runs found");
  }

  await deps.cache.setLatestRunId(deps.scope, latest.id, deps.cacheTtlSec);
  return getRun(latest.id, 0, 100, deps);
}

export interface WaitResult {
  status: "running" | "queued" | "succeeded" | "failed" | "partial";
  runId: string;
  pollUrl: string;
  requestId: string;
  payload?: MarketChannelRunResult;
  errorCode?: string | null;
  errorMessage?: string | null;
  errorRetryable?: boolean | null;
}

export async function waitForRunIfAllowed(
  config: MarketDiscoveryConfig,
  requestId: string,
  waitMs: number,
  overrides?: Partial<DiscoveryServiceDeps>
): Promise<WaitResult> {
  const shell = await createOrAttachRun(config, requestId, overrides);
  const timeoutMs = Math.max(0, waitMs);

  if (timeoutMs === 0) {
    return {
      status: shell.status,
      runId: shell.runId,
      pollUrl: shell.pollUrl,
      requestId: shell.requestId,
    };
  }

  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const run = await getRun(shell.runId, 0, 200, overrides);
    if (run.run.status === "succeeded" || run.run.status === "partial") {
      return {
        status: run.run.status,
        runId: shell.runId,
        pollUrl: shell.pollUrl,
        requestId: shell.requestId,
        payload: {
          source: {
            clobApiUrl: run.run.source.clobApiUrl,
            chainId: run.run.source.chainId,
            marketCount: run.run.marketCount,
            marketChannelCount: run.run.marketChannelCount,
          },
          channels: run.channels.items,
          wsScan: run.wsScan,
        },
      };
    }

    if (run.run.status === "failed") {
      return {
        status: run.run.status,
        runId: shell.runId,
        pollUrl: shell.pollUrl,
        requestId: shell.requestId,
        errorCode: run.run.errorCode,
        errorMessage: run.run.errorMessage,
        errorRetryable: run.run.errorRetryable,
      };
    }

    await sleep(Math.min(250, Math.max(0, end - Date.now())));
  }

  return {
    status: shell.status,
    runId: shell.runId,
    pollUrl: shell.pollUrl,
    requestId: shell.requestId,
  };
}

export async function pruneExpiredRuns(overrides?: Partial<DiscoveryServiceDeps>): Promise<number> {
  const deps = resolveDeps(overrides);
  const pruneResult = await deps.runRepository.pruneExpired(new Date());

  if (pruneResult.deleted > 0) {
    await deps.cache.clearLatestRunId(deps.scope);
    await Promise.all(
      pruneResult.runs.map(async (run) => {
        await Promise.all([
          deps.cache.clearCachedRun(run.runId),
          deps.cache.deleteActiveRunIdByDedupeKey(run.dedupeKey),
          emitRunEvent(deps.eventRepository, run.runId, "run_pruned", "run expired and removed", {
            dedupeKey: run.dedupeKey,
          }),
        ]);
      })
    );

    logDiscoveryEvent("runs_pruned", {
      deleted: pruneResult.deleted,
      scope: deps.scope,
      runs: pruneResult.runs.map((run) => run.runId),
    });
  }

  return pruneResult.deleted;
}

export interface DiscoveryRunPrunerHandle {
  stop: () => void;
}

export function startDiscoveryRunPruner(overrides?: Partial<DiscoveryServiceDeps>): DiscoveryRunPrunerHandle {
  const intervalSeconds = parseIntEnv("DISCOVERY_PRUNE_INTERVAL_SECONDS", 300);
  const intervalMs = Math.max(5, intervalSeconds) * 1000;
  let running = false;

  const runOnce = async () => {
    if (running) {
      return;
    }

    running = true;
    try {
      const deleted = await pruneExpiredRuns(overrides);
      if (deleted > 0 && process.env.NODE_ENV !== "test") {
        logDiscoveryEvent("pruner_tick", { deleted, intervalSeconds, scope: overrides?.scope ?? process.env.DISCOVERY_SCOPE ?? DEFAULT_SCOPE });
      }
    } catch (error) {
      if (process.env.NODE_ENV !== "test") {
        console.error("[discovery-run] pruner_failed", error);
      }
    } finally {
      running = false;
    }
  };

  void runOnce();
  const timer = setInterval(() => {
    void runOnce();
  }, intervalMs);

  return {
    stop: () => {
      clearInterval(timer);
    },
  };
}

async function runDiscoveryInBackground(
  runId: string,
  config: MarketDiscoveryConfig,
  requestId: string,
  dedupeKey: string,
  overrides?: Partial<DiscoveryServiceDeps>
): Promise<void> {
  const deps = resolveDeps(overrides);

  try {
    await deps.runRepository.updateRun(runId, {
      status: "running",
      startedAt: new Date(),
    } satisfies DiscoveryRunPatch);

    logDiscoveryEvent("run_status", {
      action: "running",
      runId,
    });

    await emitRunEvent(deps.eventRepository, runId, "run_started", "run transitioned to running", {
      dedupeKey,
    });

    const result = await discoverMarketChannels(config);

    await deps.channelRepository.replaceChannels(runId, result.channels);

    if (result.wsScan) {
      await deps.wsScanRepository.upsertScan(runId, result.wsScan);
    }

    await deps.runRepository.updateRun(runId, {
      status: "succeeded",
      completedAt: new Date(),
      marketCount: result.source.marketCount,
      marketChannelCount: result.source.marketChannelCount,
      errorCode: null,
      errorMessage: null,
      errorRetryable: null,
      errorDetails: null,
    });

    logDiscoveryEvent("run_status", {
      action: "succeeded",
      runId,
      marketCount: result.source.marketCount,
      marketChannelCount: result.source.marketChannelCount,
    });

    await emitRunEvent(
      deps.eventRepository,
      runId,
      "run_succeeded",
      "run completed successfully",
      {
        marketCount: result.source.marketCount,
        marketChannelCount: result.source.marketChannelCount,
      }
    );

    const read = await getRun(runId, 0, 100, deps);
    await refreshRunCache(deps, runId, read);
  } catch (error) {
    const converted = toHttpErrorResponse(error, requestId).body;

    logDiscoveryEvent("run_status", {
      action: "failed",
      runId,
      errorCode: converted.code,
      errorMessage: converted.message,
    });

    await deps.runRepository.updateRun(runId, {
      status: "failed",
      completedAt: new Date(),
      errorCode: converted.code,
      errorMessage: converted.message,
      errorRetryable: converted.retryable,
      errorDetails: converted.details,
      marketCount: 0,
      marketChannelCount: 0,
    });

    await emitRunEvent(
      deps.eventRepository,
      runId,
      "run_failed",
      "run failed",
      {
        errorCode: converted.code,
        errorMessage: converted.message,
        retryable: converted.retryable,
      }
    );
  } finally {
    await deps.cache.deleteActiveRunIdByDedupeKey(dedupeKey);
    await deps.cache.releaseSlot("global");
  }
}

export const discoveryRunService = {
  createOrAttachRun,
  getRun,
  getLatestRun,
  waitForRunIfAllowed,
  pruneExpiredRuns,
  startDiscoveryRunPruner,
};

export {
  createDiscoveryRunRepository,
  createDiscoveryChannelRepository,
  createDiscoveryRunWsScanRepository,
  createDiscoveryRunEventRepository,
};

export type { DiscoveryServiceDeps };
