import { randomUUID } from "crypto";
import { Router } from "express";

import { mapInvalidInput, toHttpErrorResponse } from "../errors";
import { marketDataService } from "../services/marketDataService";
import { ProviderId, RangeKey } from "../types";

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

function parseProvider(value: unknown): ProviderId {
  const provider = toSingleString(value);
  if (provider === "polymarket" || provider === "kalshi") {
    return provider;
  }

  throw mapInvalidInput("provider must be one of polymarket or kalshi", "provider");
}

function parseRange(value: unknown): RangeKey {
  const range = toSingleString(value);
  if (range === "6h" || range === "24h" || range === "7d" || range === "30d" || range === "max") {
    return range;
  }

  throw mapInvalidInput("range must be one of 6h, 24h, 7d, 30d, or max", "range");
}

function parsePositiveInt(value: unknown, field: string, fallback: number): number {
  const raw = toSingleString(value);
  if (!raw) {
    return fallback;
  }

  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw mapInvalidInput(`${field} must be a positive integer`, field);
  }

  return parsed;
}

router.get("/trending", async (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();

  try {
    const provider = parseProvider(req.query.provider);
    const limit = parsePositiveInt(req.query.limit, "limit", 24);
    const markets = await marketDataService.getTrendingMarkets(provider, limit);
    res.json({ provider, markets, requestId });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    res.status(status).json(body);
  }
});

router.get("/unified/trending", async (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();

  try {
    const limit = parsePositiveInt(req.query.limit, "limit", 16);
    const markets = await marketDataService.getUnifiedTrendingMarkets(limit);
    res.json({ markets, requestId });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    res.status(status).json(body);
  }
});

router.get("/search", async (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();

  try {
    const provider = parseProvider(req.query.provider);
    const query = toSingleString(req.query.q);
    if (!query) {
      throw mapInvalidInput("q is required", "q");
    }

    const limit = parsePositiveInt(req.query.limit, "limit", 24);
    const markets = await marketDataService.searchMarkets(provider, query, limit);
    res.json({ provider, query, markets, requestId });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    res.status(status).json(body);
  }
});

router.get("/history", async (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();

  try {
    const provider = parseProvider(req.query.provider);
    const marketId = toSingleString(req.query.marketId);
    if (!marketId) {
      throw mapInvalidInput("marketId is required", "marketId");
    }

    const range = parseRange(req.query.range);
    const outcomeTokenId = toSingleString(req.query.outcomeTokenId);
    const points = await marketDataService.getMarketHistory(provider, marketId, outcomeTokenId, range);
    res.json({ provider, marketId, outcomeTokenId: outcomeTokenId ?? null, range, points, requestId });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    res.status(status).json(body);
  }
});

export const marketsRouter = router;
