import { randomUUID } from "crypto";
import { Router } from "express";

import {
  DEFAULT_CLOB_API_URL,
  DEFAULT_CHAIN_ID,
  DEFAULT_MARKET_FETCH_TIMEOUT_MS,
  DEFAULT_WS_CHUNK_SIZE,
  DEFAULT_WS_CONNECT_TIMEOUT_MS,
  type MarketChannelRunResult,
} from "../types";
import { assertDiscoveryConfig, discoverMarketChannels } from "../services/marketChannelDiscoveryService";
import {
  mapInvalidInput,
  toHttpErrorResponse,
} from "../errors";

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

/**
 * GET /api/polymarket/market-channels
 */
router.get("/market-channels", async (req, res) => {
  const requestId = req.header("x-request-id") || randomUUID();

  try {
    const clobApiUrl = toSingleString(req.query.clobApiUrl) || DEFAULT_CLOB_API_URL;
    const chainId = parsePositiveIntOrDefault(req.query.chainId, "chainId", DEFAULT_CHAIN_ID);
    const wsUrl = toSingleString(req.query.wsUrl) || undefined;
    const wsConnectTimeoutMs = parsePositiveIntOrDefault(
      req.query.wsConnectTimeoutMs,
      "wsConnectTimeoutMs",
      DEFAULT_WS_CONNECT_TIMEOUT_MS
    );
    const wsChunkSize = parsePositiveIntOrDefault(req.query.wsChunkSize, "wsChunkSize", DEFAULT_WS_CHUNK_SIZE);
    const marketFetchTimeoutMs = parsePositiveIntOrDefault(
      req.query.marketFetchTimeoutMs,
      "marketFetchTimeoutMs",
      DEFAULT_MARKET_FETCH_TIMEOUT_MS
    );

    assertDiscoveryConfig({
      clobApiUrl,
      chainId,
      wsUrl,
      wsConnectTimeoutMs,
      wsChunkSize,
      marketFetchTimeoutMs,
    });

    const result: MarketChannelRunResult = await discoverMarketChannels({
      clobApiUrl,
      chainId,
      wsUrl,
      wsConnectTimeoutMs,
      wsChunkSize,
      marketFetchTimeoutMs,
    });

    return res.status(200).json(result);
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    return res.status(status).json(body);
  }
});

export const polymarketRouter = router;
