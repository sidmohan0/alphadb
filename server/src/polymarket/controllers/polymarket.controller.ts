import { Router } from "express";

import {
  DEFAULT_CLOB_API_URL,
  DEFAULT_CHAIN_ID,
  DEFAULT_WS_CHUNK_SIZE,
  DEFAULT_WS_CONNECT_TIMEOUT_MS,
  type MarketChannelRunResult,
} from "../types";
import { parseNumber } from "../utils";
import { discoverMarketChannels } from "../services/marketChannelDiscoveryService";

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

/**
 * GET /api/polymarket/market-channels
 */
router.get("/market-channels", async (req, res) => {
  const clobApiUrl = toSingleString(req.query.clobApiUrl) || DEFAULT_CLOB_API_URL;
  const chainId = parseNumber(toSingleString(req.query.chainId), DEFAULT_CHAIN_ID);
  const wsUrl = toSingleString(req.query.wsUrl) || undefined;
  const wsConnectTimeoutMs = parseNumber(
    toSingleString(req.query.wsConnectTimeoutMs),
    DEFAULT_WS_CONNECT_TIMEOUT_MS
  );
  const wsChunkSize = parseNumber(toSingleString(req.query.wsChunkSize), DEFAULT_WS_CHUNK_SIZE);

  try {
    const result: MarketChannelRunResult = await discoverMarketChannels({
      clobApiUrl,
      chainId,
      wsUrl,
      wsConnectTimeoutMs,
      wsChunkSize,
    });

    return res.status(200).json(result);
  } catch (error) {
    return res.status(502).json({
      error: "Failed to discover market channels",
      details: String(error instanceof Error ? error.message : error),
    });
  }
});

export const polymarketRouter = router;
