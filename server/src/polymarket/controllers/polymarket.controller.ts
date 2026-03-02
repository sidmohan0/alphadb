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
import { assertDiscoveryConfig } from "../services/marketChannelDiscoveryService";
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

function parsePositiveIntOrDefault(queryValue: unknown, field: string, fallback: number): number {
  const raw = toSingleString(queryValue);
  if (!raw) return fallback;

  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0 || !Number.isInteger(parsed)) {
    throw mapInvalidInput(`${field} must be a positive integer`, field);
  }

  return parsed;
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

function parseDiscoveryRequestFromQuery(query: Record<string, unknown>): MarketDiscoveryConfig {
  const clobApiUrl = toSingleString(query.clobApiUrl) || DEFAULT_CLOB_API_URL;
  const chainId = parsePositiveIntOrDefault(query.chainId, "chainId", DEFAULT_CHAIN_ID);
  const wsUrl = toSingleString(query.wsUrl) || undefined;
  const wsConnectTimeoutMs = parsePositiveIntOrDefault(
    query.wsConnectTimeoutMs,
    "wsConnectTimeoutMs",
    DEFAULT_WS_CONNECT_TIMEOUT_MS
  );
  const wsChunkSize = parsePositiveIntOrDefault(query.wsChunkSize, "wsChunkSize", DEFAULT_WS_CHUNK_SIZE);
  const marketFetchTimeoutMs = parsePositiveIntOrDefault(
    query.marketFetchTimeoutMs,
    "marketFetchTimeoutMs",
    DEFAULT_MARKET_FETCH_TIMEOUT_MS
  );

  return {
    clobApiUrl,
    chainId,
    wsUrl,
    wsConnectTimeoutMs,
    wsChunkSize,
    marketFetchTimeoutMs,
  };
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
    const config: MarketDiscoveryConfig = {
      clobApiUrl: toSingleString(body.clobApiUrl) || DEFAULT_CLOB_API_URL,
      chainId: parsePositiveIntOrDefault(body.chainId, "chainId", DEFAULT_CHAIN_ID),
      wsUrl: toSingleString(body.wsUrl) || undefined,
      wsConnectTimeoutMs: parsePositiveIntOrDefault(
        body.wsConnectTimeoutMs,
        "wsConnectTimeoutMs",
        DEFAULT_WS_CONNECT_TIMEOUT_MS
      ),
      wsChunkSize: parsePositiveIntOrDefault(body.wsChunkSize, "wsChunkSize", DEFAULT_WS_CHUNK_SIZE),
      marketFetchTimeoutMs: parsePositiveIntOrDefault(
        body.marketFetchTimeoutMs,
        "marketFetchTimeoutMs",
        DEFAULT_MARKET_FETCH_TIMEOUT_MS
      ),
    };

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
