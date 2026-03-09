import { randomUUID } from "crypto";
import { Router } from "express";

import { mapInvalidInput, toHttpErrorResponse } from "../errors";
import { kalshiRealtimeHub } from "../services/kalshiRealtimeHub";
import { marketDataService } from "../services/marketDataService";
import {
  getUserMarketState,
  normalizeMarketSummary,
  removeSavedMarketForUser,
  resolveUserId,
  saveMarketForUser,
  touchRecentMarketForUser,
} from "../services/userStateStore";
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

function parseUserId(value: unknown): string {
  return resolveUserId(toSingleString(value));
}

function parseTickers(value: unknown): string[] {
  const raw = toSingleString(value);
  if (!raw) {
    return [];
  }

  return [...new Set(raw.split(",").map((ticker) => ticker.trim()).filter(Boolean))];
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
    const userId = parseUserId(req.header("x-alphadb-user-id") ?? req.query.userId);
    const query = toSingleString(req.query.q);
    if (!query) {
      throw mapInvalidInput("q is required", "q");
    }

    const limit = parsePositiveInt(req.query.limit, "limit", 24);
    const markets = await marketDataService.searchMarketsForUser(provider, query, limit, userId);
    res.json({ provider, userId, query, markets, requestId });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    res.status(status).json(body);
  }
});

router.get("/unified/search", async (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();

  try {
    const userId = parseUserId(req.header("x-alphadb-user-id") ?? req.query.userId);
    const query = toSingleString(req.query.q);
    if (!query) {
      throw mapInvalidInput("q is required", "q");
    }

    const limit = parsePositiveInt(req.query.limit, "limit", 16);
    const markets = await marketDataService.getUnifiedSearchMarkets(query, limit, userId);
    res.json({ userId, query, markets, requestId });
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

router.get("/state", async (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();

  try {
    const userId = parseUserId(req.header("x-alphadb-user-id") ?? req.query.userId);
    const state = await getUserMarketState(userId);
    res.json({ userId, state, requestId });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    res.status(status).json(body);
  }
});

router.put("/state/saved", async (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();

  try {
    const userId = parseUserId(req.header("x-alphadb-user-id") ?? req.query.userId);
    const market = normalizeMarketSummary((req.body as { market?: unknown }).market);
    if (!market) {
      throw mapInvalidInput("market is required", "market");
    }

    const result = await saveMarketForUser(userId, market);
    res.json({ userId, state: result.state, saved: result.saved, requestId });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    res.status(status).json(body);
  }
});

router.delete("/state/saved", async (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();

  try {
    const userId = parseUserId(req.header("x-alphadb-user-id") ?? req.query.userId);
    const marketId = toSingleString(req.query.marketId);
    if (!marketId) {
      throw mapInvalidInput("marketId is required", "marketId");
    }

    const result = await removeSavedMarketForUser(userId, marketId);
    res.json({ userId, state: result.state, saved: result.saved, requestId });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    res.status(status).json(body);
  }
});

router.post("/state/recent", async (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();

  try {
    const userId = parseUserId(req.header("x-alphadb-user-id") ?? req.query.userId);
    const market = normalizeMarketSummary((req.body as { market?: unknown }).market);
    if (!market) {
      throw mapInvalidInput("market is required", "market");
    }

    const state = await touchRecentMarketForUser(userId, market);
    res.json({ userId, state, requestId });
  } catch (error) {
    const { status, body } = toHttpErrorResponse(error, requestId);
    res.status(status).json(body);
  }
});

router.get("/stream", (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();
  const tickers = parseTickers(req.query.tickers);

  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache, no-transform");
  res.setHeader("Connection", "keep-alive");
  res.flushHeaders?.();

  const writeEvent = (event: string, data: unknown) => {
    res.write(`event: ${event}\n`);
    res.write(`data: ${JSON.stringify(data)}\n\n`);
  };

  writeEvent("ready", { requestId, tickers });

  const subscription = kalshiRealtimeHub.subscribe(
    tickers,
    (message) => writeEvent("status", { message }),
    (payload) => writeEvent("ticker", payload),
  );

  const heartbeat = setInterval(() => {
    res.write(": ping\n\n");
  }, 15_000);

  req.on("close", () => {
    clearInterval(heartbeat);
    subscription.close();
    res.end();
  });
});

export const marketsRouter = router;
