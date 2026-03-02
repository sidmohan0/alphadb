import { randomUUID } from "crypto";
import { Router } from "express";

import {
  DEFAULT_CLOB_API_URL,
  DEFAULT_CHAIN_ID,
  DEFAULT_MARKET_FETCH_TIMEOUT_MS,
  DEFAULT_WS_CHUNK_SIZE,
  DEFAULT_WS_CONNECT_TIMEOUT_MS,
  type MarketDiscoveryConfig,
} from "../types";
import { assertDiscoveryConfig, estimateMarketChannels } from "../services/marketChannelDiscoveryService";
import { discoveryRunService, WaitResult } from "../services/discoveryRunService";
import { mapInvalidInput, toHttpErrorResponse } from "../errors";

const router = Router();

function toSingleString(value: unknown): string | undefined {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length ? trimmed : undefined;
  }

  if (Array.isArray(value) && value.length > 0 && typeof value[0] === "string") {
    const trimmed = value[0].trim();
    return trimmed.length ? trimmed : undefined;
  }

  return undefined;
}

function firstValueOrUndefined(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value[0];
  }

  return value;
}

function parsePositiveIntOrDefault(queryValue: unknown, field: string, fallback: number): number {
  const raw = firstValueOrUndefined(queryValue);
  if (raw === undefined || raw === null) {
    return fallback;
  }

  let parsed: number;
  if (typeof raw === "number") {
    parsed = raw;
  } else if (typeof raw === "string") {
    const normalized = raw.trim();
    if (!normalized) {
      return fallback;
    }
    parsed = Number(normalized);
  } else {
    throw mapInvalidInput(`${field} must be a positive integer`, field);
  }

  if (!Number.isFinite(parsed) || parsed <= 0 || !Number.isInteger(parsed)) {
    throw mapInvalidInput(`${field} must be a positive integer`, field);
  }

  return parsed;
}

function parsePositiveIntOrUndefined(queryValue: unknown, field: string): number | undefined {
  const raw = firstValueOrUndefined(queryValue);
  if (raw === undefined || raw === null) {
    return undefined;
  }

  let parsed: number;
  if (typeof raw === "number") {
    parsed = raw;
  } else if (typeof raw === "string") {
    const normalized = raw.trim();
    if (!normalized) {
      return undefined;
    }

    parsed = Number(normalized);
  } else {
    throw mapInvalidInput(`${field} must be a positive integer`, field);
  }

  if (!Number.isFinite(parsed) || parsed <= 0 || !Number.isInteger(parsed)) {
    throw mapInvalidInput(`${field} must be a positive integer`, field);
  }

  return parsed;
}

function parseBooleanOrUndefined(queryValue: unknown, field: string): boolean | undefined {
  const raw = firstValueOrUndefined(queryValue);
  if (raw === undefined || raw === null) {
    return undefined;
  }

  if (typeof raw === "boolean") {
    return raw;
  }

  if (typeof raw === "number") {
    if (raw === 1) {
      return true;
    }

    if (raw === 0) {
      return false;
    }

    throw mapInvalidInput(`${field} must be a boolean`, field);
  }

  if (typeof raw !== "string") {
    throw mapInvalidInput(`${field} must be a boolean`, field);
  }

  const normalized = raw.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }

  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }

  throw mapInvalidInput(`${field} must be a boolean`, field);
}

function parseTagList(queryValue: unknown, field: string): string[] | undefined {
  const raw = queryValue;
  const values = Array.isArray(raw) ? raw : [raw];
  const parsed: string[] = [];
  const seen = new Set<string>();

  for (const candidate of values) {
    if (candidate == null) {
      continue;
    }

    if (Array.isArray(candidate)) {
      for (const nested of candidate) {
        const str = toSingleString(nested);
        if (!str) {
          continue;
        }

        for (const split of str.split(",")) {
          const tag = split.trim();
          if (!tag) {
            continue;
          }

          const normalized = tag.trim();
          if (!seen.has(normalized)) {
            seen.add(normalized);
            parsed.push(normalized);
          }
        }
      }
      continue;
    }

    const str = toSingleString(candidate);
    if (!str) {
      continue;
    }

    for (const split of str.split(",")) {
      const tag = split.trim();
      if (!tag) {
        continue;
      }

      if (!seen.has(tag)) {
        seen.add(tag);
        parsed.push(tag);
      }
    }
  }

  if (!parsed.length) {
    return undefined;
  }

  return parsed.sort((left, right) => left.localeCompare(right));
}

function parseNonNegativeNumberOrUndefined(queryValue: unknown, field: string): number | undefined {
  const raw = firstValueOrUndefined(queryValue);
  if (raw === undefined || raw === null) {
    return undefined;
  }

  let parsed: number;
  if (typeof raw === "number") {
    parsed = raw;
  } else if (typeof raw === "string") {
    const normalized = raw.trim();
    if (!normalized) {
      return undefined;
    }

    parsed = Number(normalized);
  } else {
    throw mapInvalidInput(`${field} must be a non-negative number`, field);
  }

  if (!Number.isFinite(parsed) || parsed < 0) {
    throw mapInvalidInput(`${field} must be a non-negative number`, field);
  }

  return parsed;
}

function parseDateOrUndefined(queryValue: unknown, field: string): string | undefined {
  const raw = firstValueOrUndefined(queryValue);
  if (raw === undefined || raw === null) {
    return undefined;
  }

  let parsed: number;
  if (typeof raw === "number") {
    parsed = raw;
  } else if (typeof raw === "string") {
    const normalized = raw.trim();
    if (!normalized) {
      return undefined;
    }

    parsed = Date.parse(normalized);
  } else {
    throw mapInvalidInput(`${field} must be a valid date`, field);
  }

  if (!Number.isFinite(parsed)) {
    throw mapInvalidInput(`${field} must be a valid date`, field);
  }

  return new Date(parsed).toISOString();
}

function parseMarketDiscoveryFilters(input: Record<string, unknown>): Pick<
  MarketDiscoveryConfig,
  | "acceptingOrders"
  | "enableOrderBook"
  | "maxMarkets"
  | "minimumOrderSizeMin"
  | "minimumOrderSizeMax"
  | "minimumTickSizeMin"
  | "minimumTickSizeMax"
  | "makerBaseFeeMin"
  | "makerBaseFeeMax"
  | "takerBaseFeeMin"
  | "takerBaseFeeMax"
  | "notificationsEnabled"
  | "negRisk"
  | "fpmm"
  | "secondsDelayMin"
  | "secondsDelayMax"
  | "acceptingOrderTimestampMin"
  | "acceptingOrderTimestampMax"
  | "descriptionContains"
  | "questionIdContains"
  | "rewardsHasRates"
  | "rewardsMinSizeMin"
  | "rewardsMinSizeMax"
  | "rewardsMaxSpreadMin"
  | "rewardsMaxSpreadMax"
  | "iconContains"
  | "imageContains"
  | "conditionIdContains"
  | "negRiskMarketIdContains"
  | "negRiskRequestIdContains"
  | "endDateIsoMin"
  | "endDateIsoMax"
  | "gameStartTimeMin"
  | "gameStartTimeMax"
  | "active"
  | "closed"
  | "archived"
  | "isFiftyFiftyOutcome"
  | "tags"
  | "questionContains"
  | "marketSlugContains"
> {
  const enableOrderBook = parseBooleanOrUndefined(input.enableOrderBook, "enableOrderBook");
  const maxMarkets = parsePositiveIntOrUndefined(input.maxMarkets, "maxMarkets");
  const questionContains = toSingleString(input.questionContains);
  const marketSlugContains = toSingleString(input.marketSlugContains);
  const descriptionContains = toSingleString(input.descriptionContains);
  const conditionIdContains = toSingleString(input.conditionIdContains);
  const fpmm = toSingleString(input.fpmm);
  const negRiskMarketIdContains = toSingleString(input.negRiskMarketIdContains);
  const negRiskRequestIdContains = toSingleString(input.negRiskRequestIdContains);
  const minimumOrderSizeMin = parseNonNegativeNumberOrUndefined(
    input.minimumOrderSizeMin,
    "minimumOrderSizeMin"
  );
  const minimumOrderSizeMax = parseNonNegativeNumberOrUndefined(
    input.minimumOrderSizeMax,
    "minimumOrderSizeMax"
  );
  const minimumTickSizeMin = parseNonNegativeNumberOrUndefined(
    input.minimumTickSizeMin,
    "minimumTickSizeMin"
  );
  const minimumTickSizeMax = parseNonNegativeNumberOrUndefined(
    input.minimumTickSizeMax,
    "minimumTickSizeMax"
  );
  const makerBaseFeeMin = parseNonNegativeNumberOrUndefined(input.makerBaseFeeMin, "makerBaseFeeMin");
  const makerBaseFeeMax = parseNonNegativeNumberOrUndefined(input.makerBaseFeeMax, "makerBaseFeeMax");
  const takerBaseFeeMin = parseNonNegativeNumberOrUndefined(input.takerBaseFeeMin, "takerBaseFeeMin");
  const takerBaseFeeMax = parseNonNegativeNumberOrUndefined(input.takerBaseFeeMax, "takerBaseFeeMax");
  const secondsDelayMin = parseNonNegativeNumberOrUndefined(input.secondsDelayMin, "secondsDelayMin");
  const secondsDelayMax = parseNonNegativeNumberOrUndefined(input.secondsDelayMax, "secondsDelayMax");
  const rewardsHasRates = parseBooleanOrUndefined(input.rewardsHasRates, "rewardsHasRates");
  const rewardsMinSizeMin = parseNonNegativeNumberOrUndefined(
    input.rewardsMinSizeMin,
    "rewardsMinSizeMin"
  );
  const rewardsMinSizeMax = parseNonNegativeNumberOrUndefined(
    input.rewardsMinSizeMax,
    "rewardsMinSizeMax"
  );
  const rewardsMaxSpreadMin = parseNonNegativeNumberOrUndefined(
    input.rewardsMaxSpreadMin,
    "rewardsMaxSpreadMin"
  );
  const rewardsMaxSpreadMax = parseNonNegativeNumberOrUndefined(
    input.rewardsMaxSpreadMax,
    "rewardsMaxSpreadMax"
  );
  const acceptingOrderTimestampMin = parseNonNegativeNumberOrUndefined(
    input.acceptingOrderTimestampMin,
    "acceptingOrderTimestampMin"
  );
  const acceptingOrderTimestampMax = parseNonNegativeNumberOrUndefined(
    input.acceptingOrderTimestampMax,
    "acceptingOrderTimestampMax"
  );
  const questionIdContains = toSingleString(input.questionIdContains);
  const iconContains = toSingleString(input.iconContains);
  const imageContains = toSingleString(input.imageContains);
  const endDateIsoMin = parseDateOrUndefined(input.endDateIsoMin, "endDateIsoMin");
  const endDateIsoMax = parseDateOrUndefined(input.endDateIsoMax, "endDateIsoMax");
  const gameStartTimeMin = parseDateOrUndefined(input.gameStartTimeMin, "gameStartTimeMin");
  const gameStartTimeMax = parseDateOrUndefined(input.gameStartTimeMax, "gameStartTimeMax");
  const tags = parseTagList(input.tags, "tags");

  if (
    minimumOrderSizeMin !== undefined &&
    minimumOrderSizeMax !== undefined &&
    minimumOrderSizeMax < minimumOrderSizeMin
  ) {
    throw mapInvalidInput("minimumOrderSizeMax must be >= minimumOrderSizeMin", "minimumOrderSizeMax");
  }

  if (minimumTickSizeMin !== undefined && minimumTickSizeMax !== undefined && minimumTickSizeMax < minimumTickSizeMin) {
    throw mapInvalidInput("minimumTickSizeMax must be >= minimumTickSizeMin", "minimumTickSizeMax");
  }

  if (makerBaseFeeMin !== undefined && makerBaseFeeMax !== undefined && makerBaseFeeMax < makerBaseFeeMin) {
    throw mapInvalidInput("makerBaseFeeMax must be >= makerBaseFeeMin", "makerBaseFeeMax");
  }

  if (takerBaseFeeMin !== undefined && takerBaseFeeMax !== undefined && takerBaseFeeMax < takerBaseFeeMin) {
    throw mapInvalidInput("takerBaseFeeMax must be >= takerBaseFeeMin", "takerBaseFeeMax");
  }

  if (secondsDelayMin !== undefined && secondsDelayMax !== undefined && secondsDelayMax < secondsDelayMin) {
    throw mapInvalidInput("secondsDelayMax must be >= secondsDelayMin", "secondsDelayMax");
  }

  if (
    acceptingOrderTimestampMin !== undefined &&
    acceptingOrderTimestampMax !== undefined &&
    acceptingOrderTimestampMax < acceptingOrderTimestampMin
  ) {
    throw mapInvalidInput(
      "acceptingOrderTimestampMax must be >= acceptingOrderTimestampMin",
      "acceptingOrderTimestampMax"
    );
  }

  if (endDateIsoMin !== undefined && endDateIsoMax !== undefined && Date.parse(endDateIsoMax) < Date.parse(endDateIsoMin)) {
    throw mapInvalidInput("endDateIsoMax must be >= endDateIsoMin", "endDateIsoMax");
  }

  if (gameStartTimeMin !== undefined && gameStartTimeMax !== undefined && Date.parse(gameStartTimeMax) < Date.parse(gameStartTimeMin)) {
    throw mapInvalidInput("gameStartTimeMax must be >= gameStartTimeMin", "gameStartTimeMax");
  }

  if (
    rewardsMinSizeMin !== undefined &&
    rewardsMinSizeMax !== undefined &&
    rewardsMinSizeMax < rewardsMinSizeMin
  ) {
    throw mapInvalidInput("rewardsMinSizeMax must be >= rewardsMinSizeMin", "rewardsMinSizeMax");
  }

  if (
    rewardsMaxSpreadMin !== undefined &&
    rewardsMaxSpreadMax !== undefined &&
    rewardsMaxSpreadMax < rewardsMaxSpreadMin
  ) {
    throw mapInvalidInput("rewardsMaxSpreadMax must be >= rewardsMaxSpreadMin", "rewardsMaxSpreadMax");
  }

  return {
    ...(parseBooleanOrUndefined(input.acceptingOrders, "acceptingOrders") !== undefined
      ? { acceptingOrders: parseBooleanOrUndefined(input.acceptingOrders, "acceptingOrders") }
      : {}),
    ...(enableOrderBook !== undefined ? { enableOrderBook } : {}),
    ...(maxMarkets !== undefined ? { maxMarkets } : {}),
    ...(minimumOrderSizeMin !== undefined ? { minimumOrderSizeMin } : {}),
    ...(minimumOrderSizeMax !== undefined ? { minimumOrderSizeMax } : {}),
    ...(minimumTickSizeMin !== undefined ? { minimumTickSizeMin } : {}),
    ...(minimumTickSizeMax !== undefined ? { minimumTickSizeMax } : {}),
    ...(makerBaseFeeMin !== undefined ? { makerBaseFeeMin } : {}),
    ...(makerBaseFeeMax !== undefined ? { makerBaseFeeMax } : {}),
    ...(takerBaseFeeMin !== undefined ? { takerBaseFeeMin } : {}),
    ...(takerBaseFeeMax !== undefined ? { takerBaseFeeMax } : {}),
    ...(questionIdContains ? { questionIdContains } : {}),
    ...(rewardsHasRates !== undefined ? { rewardsHasRates } : {}),
    ...(rewardsMinSizeMin !== undefined ? { rewardsMinSizeMin } : {}),
    ...(rewardsMinSizeMax !== undefined ? { rewardsMinSizeMax } : {}),
    ...(rewardsMaxSpreadMin !== undefined ? { rewardsMaxSpreadMin } : {}),
    ...(rewardsMaxSpreadMax !== undefined ? { rewardsMaxSpreadMax } : {}),
    ...(iconContains ? { iconContains } : {}),
    ...(imageContains ? { imageContains } : {}),
    ...(parseBooleanOrUndefined(input.notificationsEnabled, "notificationsEnabled") !== undefined
      ? {
          notificationsEnabled: parseBooleanOrUndefined(
            input.notificationsEnabled,
            "notificationsEnabled"
          ),
        }
      : {}),
    ...(parseBooleanOrUndefined(input.negRisk, "negRisk") !== undefined
      ? { negRisk: parseBooleanOrUndefined(input.negRisk, "negRisk") }
      : {}),
    ...(fpmm ? { fpmm } : {}),
    ...(secondsDelayMin !== undefined ? { secondsDelayMin } : {}),
    ...(secondsDelayMax !== undefined ? { secondsDelayMax } : {}),
    ...(acceptingOrderTimestampMin !== undefined ? { acceptingOrderTimestampMin } : {}),
    ...(acceptingOrderTimestampMax !== undefined ? { acceptingOrderTimestampMax } : {}),
    ...(descriptionContains ? { descriptionContains } : {}),
    ...(conditionIdContains ? { conditionIdContains } : {}),
    ...(negRiskMarketIdContains ? { negRiskMarketIdContains } : {}),
    ...(negRiskRequestIdContains ? { negRiskRequestIdContains } : {}),
    ...(endDateIsoMin ? { endDateIsoMin } : {}),
    ...(endDateIsoMax ? { endDateIsoMax } : {}),
    ...(gameStartTimeMin ? { gameStartTimeMin } : {}),
    ...(gameStartTimeMax ? { gameStartTimeMax } : {}),
    ...(parseBooleanOrUndefined(input.active, "active") !== undefined
      ? { active: parseBooleanOrUndefined(input.active, "active") }
      : {}),
    ...(parseBooleanOrUndefined(input.closed, "closed") !== undefined
      ? { closed: parseBooleanOrUndefined(input.closed, "closed") }
      : {}),
    ...(parseBooleanOrUndefined(input.archived, "archived") !== undefined
      ? { archived: parseBooleanOrUndefined(input.archived, "archived") }
      : {}),
    ...(parseBooleanOrUndefined(input.isFiftyFiftyOutcome, "isFiftyFiftyOutcome") !== undefined
      ? {
          isFiftyFiftyOutcome: parseBooleanOrUndefined(
            input.isFiftyFiftyOutcome,
            "isFiftyFiftyOutcome"
          ),
        }
      : {}),
    ...(tags ? { tags } : {}),
    ...(questionContains ? { questionContains } : {}),
    ...(marketSlugContains ? { marketSlugContains } : {}),
  };
}

function parseDiscoveryConfig(input: Record<string, unknown>): MarketDiscoveryConfig {
  return {
    clobApiUrl: toSingleString(input.clobApiUrl) || DEFAULT_CLOB_API_URL,
    chainId: parsePositiveIntOrDefault(input.chainId, "chainId", DEFAULT_CHAIN_ID),
    maxMarkets: parsePositiveIntOrUndefined(input.maxMarkets, "maxMarkets"),
    wsUrl: toSingleString(input.wsUrl) || undefined,
    wsConnectTimeoutMs: parsePositiveIntOrDefault(
      input.wsConnectTimeoutMs,
      "wsConnectTimeoutMs",
      DEFAULT_WS_CONNECT_TIMEOUT_MS
    ),
    wsChunkSize: parsePositiveIntOrDefault(input.wsChunkSize, "wsChunkSize", DEFAULT_WS_CHUNK_SIZE),
    marketFetchTimeoutMs: parsePositiveIntOrDefault(
      input.marketFetchTimeoutMs,
      "marketFetchTimeoutMs",
      DEFAULT_MARKET_FETCH_TIMEOUT_MS
    ),
    ...parseMarketDiscoveryFilters(input),
  };
}

function parseNonNegativeIntOrDefault(queryValue: unknown, field: string, fallback: number): number {
  const raw = toSingleString(queryValue);
  if (!raw) return fallback;

  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 0 || !Number.isInteger(parsed)) {
    throw mapInvalidInput(`${field} must be a non-negative integer`, field);
  }

  return parsed;
}

function parseLimitOrDefault(queryValue: unknown, field: string, fallback: number): number {
  const parsed = parsePositiveIntOrDefault(queryValue, field, fallback);
  return Math.min(parsed, 200);
}

function parseDiscoveryRequestFromQuery(query: Record<string, unknown>): MarketDiscoveryConfig {
  return parseDiscoveryConfig(query);
}

function parseRunId(runId: unknown): string {
  if (typeof runId === "string" && runId.trim().length > 0) {
    return runId.trim();
  }

  if (Array.isArray(runId) && typeof runId[0] === "string" && runId[0].trim().length > 0) {
    return runId[0].trim();
  }

  throw mapInvalidInput("runId is required", "runId");
}

function parseOffsetLimit(query: Record<string, unknown>): { offset: number; limit: number } {
  const offset = parseNonNegativeIntOrDefault(query.offset, "offset", 0);
  const limit = parsePositiveIntOrDefault(query.limit, "limit", 200);
  return { offset, limit };
}

function parseWaitMs(query: Record<string, unknown>): number {
  const raw = toSingleString(query.waitMs);
  if (!raw) return 0;

  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 0 || !Number.isInteger(parsed)) {
    throw mapInvalidInput("waitMs must be a non-negative integer", "waitMs");
  }

  return parsed;
}

function respondCompatibilityResult(result: WaitResult, res: any): void {
  if (!result.payload && (result.status === "queued" || result.status === "running")) {
    res.status(202).json({
      runId: result.runId,
      status: result.status,
      pollUrl: result.pollUrl,
      requestId: result.requestId,
    });
    return;
  }

  if (result.payload) {
    res.status(200).json(result.payload);
    return;
  }

  res.status(500).json({
    error: "Failed to discover market channels",
    code: result.errorCode ?? "unexpected_error",
    message: result.errorMessage ?? "Discovery run failed",
    retryable: Boolean(result.errorRetryable),
    details: {
      component: "service",
      runId: result.runId,
    },
    requestId: result.requestId,
  });
}

/**
 * POST /api/polymarket/market-channels/runs
 * Primary async API entrypoint.
 */
router.post("/market-channels/runs", async (req, res) => {
  const requestId = req.header("x-request-id") || randomUUID();

  try {
    const body = req.body as Record<string, unknown>;
    const config = parseDiscoveryConfig(body);

    assertDiscoveryConfig(config);

    const shell = await discoveryRunService.createOrAttachRun(config, requestId);

    return res.status(202).json({
      status: shell.status,
      runId: shell.runId,
      pollUrl: shell.pollUrl,
      requestId: shell.requestId,
    });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    return res.status(status).json(body);
  }
});

/**
 * POST /api/polymarket/market-channels/runs/estimate
 * Fast sampled estimate for previewing likely matches before full discovery.
 */
router.post("/market-channels/runs/estimate", async (req, res) => {
  const requestId = req.header("x-request-id") || randomUUID();

  try {
    const body = req.body as Record<string, unknown>;
    const sampleLimit = parsePositiveIntOrDefault(
      body.sampleLimit !== undefined ? body.sampleLimit : body.maxMarkets,
      "sampleLimit",
      10
    );
    const cappedSampleLimit = Math.min(sampleLimit, 1000);
    const config = parseDiscoveryConfig(body);

    const estimate = await estimateMarketChannels(
      {
        ...config,
        maxMarkets: cappedSampleLimit,
      },
      cappedSampleLimit
    );

    return res.status(200).json({
      source: estimate.source,
      channels: estimate.channels,
      requestId,
      sampleLimit: cappedSampleLimit,
      pagesScanned: estimate.source.pagesScanned,
      stoppedByLimit: estimate.source.stoppedByLimit,
      hasMore: estimate.source.hasMore,
    });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    return res.status(status).json(body);
  }
});

/**
 * GET /api/polymarket/market-channels/runs/latest
 */
router.get("/market-channels/runs/latest", async (req, res) => {
  const requestId = req.header("x-request-id") || randomUUID();

  try {
    const latest = await discoveryRunService.getLatestRun();
    return res.status(200).json(latest);
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    return res.status(status).json(body);
  }
});

/**
 * GET /api/polymarket/market-channels/runs/active
 */
router.get("/market-channels/runs/active", async (req, res) => {
  const requestId = req.header("x-request-id") || randomUUID();

  try {
    const limit = parseLimitOrDefault(req.query.limit, "limit", 50);
    const runs = await discoveryRunService.listActiveRuns(limit);
    return res.status(200).json(runs);
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    return res.status(status).json(body);
  }
});

/**
 * POST /api/polymarket/market-channels/runs/:runId/cancel
 */
router.post("/market-channels/runs/:runId/cancel", async (req, res) => {
  const requestId = req.header("x-request-id") || randomUUID();

  try {
    const runId = parseRunId(req.params.runId);
    const shell = await discoveryRunService.cancelRun(runId, requestId);
    return res.status(200).json(shell);
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    return res.status(status).json(body);
  }
});

/**
 * GET /api/polymarket/market-channels/runs/:runId
 */
router.get("/market-channels/runs/:runId", async (req, res) => {
  const requestId = req.header("x-request-id") || randomUUID();

  try {
    const runId = parseRunId(req.params.runId);
    const { offset, limit } = parseOffsetLimit(req.query);

    const run = await discoveryRunService.getRun(runId, offset, limit);
    return res.status(200).json(run);
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    return res.status(status).json(body);
  }
});

/**
 * GET /api/polymarket/market-channels
 * Compatibility wrapper for older callers and quick local testing.
 */
router.get("/market-channels", async (req, res) => {
  const requestId = req.header("x-request-id") || randomUUID();

  try {
    const config = parseDiscoveryRequestFromQuery(req.query);
    const waitMs = parseWaitMs(req.query);

    const result = await discoveryRunService.waitForRunIfAllowed(config, requestId, waitMs);
    return respondCompatibilityResult(result, res);
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    return res.status(status).json(body);
  }
});

export const polymarketRouter = router;
