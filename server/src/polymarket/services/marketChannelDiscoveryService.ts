import { ClobClient } from "@polymarket/clob-client";

import {
  DEFAULT_CLOB_API_URL,
  DEFAULT_CHAIN_ID,
  DEFAULT_MARKET_DISCOVERY_CONCURRENCY_LIMIT,
  DEFAULT_MARKET_FETCH_TIMEOUT_MS,
  DEFAULT_WS_CHUNK_SIZE,
  DEFAULT_WS_CONNECT_TIMEOUT_MS,
  type FetchMarketChannelsResult,
  type MarketDiscoveryConfig,
  type MarketLike,
  type MarketPayload,
  type ProbeMarketChannelsParams,
  type MarketChannel,
  type WsScanSummary,
  type MarketChannelRunResult,
} from "../types";
import {
  chunk,
  collectTokenChannel,
  extractAssetIdsFromWsPayload,
  isAssetIdCandidate,
  isString,
  normalizeWsUrl,
  parseMessageData,
  toStringOrUndefined,
} from "../utils";
import {
  mapClobRequestFailure,
  mapDiscoveryConcurrencyLimit,
  mapInvalidInput,
  mapWebsocketInvalidUrl,
  PolymarketDiscoveryError,
} from "../errors";

/**
 * Shared defaults and config parsing contract for the discovery run.
 */
export const DEFAULT_DISCOVERY_CONFIG = {
  clobApiUrl: DEFAULT_CLOB_API_URL,
  chainId: DEFAULT_CHAIN_ID,
  wsConnectTimeoutMs: DEFAULT_WS_CONNECT_TIMEOUT_MS,
  wsChunkSize: DEFAULT_WS_CHUNK_SIZE,
  marketFetchTimeoutMs: DEFAULT_MARKET_FETCH_TIMEOUT_MS,
} as const;

const inFlightDiscoveries = new Map<string, Promise<MarketChannelRunResult>>();
let activeDiscoveryCount = 0;

function getDiscoveryConcurrencyLimit(): number {
  const raw = process.env.MARKET_DISCOVERY_CONCURRENCY_LIMIT;

  const fromEnv = Number(raw);
  if (Number.isFinite(fromEnv) && fromEnv > 0 && Number.isInteger(fromEnv)) {
    return fromEnv;
  }

  return DEFAULT_MARKET_DISCOVERY_CONCURRENCY_LIMIT;
}

function discoveryRequestKey(config: MarketDiscoveryConfig): string {
  return JSON.stringify({
    clobApiUrl: config.clobApiUrl,
    chainId: config.chainId,
    wsUrl: config.wsUrl ?? null,
    wsConnectTimeoutMs: config.wsConnectTimeoutMs,
    wsChunkSize: config.wsChunkSize,
    marketFetchTimeoutMs: config.marketFetchTimeoutMs,
  });
}

async function withTimeout<T>(
  action: () => Promise<T>,
  timeoutMs: number,
  operation: string,
  context: Record<string, unknown> = {}
): Promise<T> {
  let timer: NodeJS.Timeout | undefined;

  const timeoutPromise = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(
        mapClobRequestFailure(new Error(`Operation ${operation} timed out after ${timeoutMs}ms`), {
          ...context,
          operation,
        })
      );
    }, timeoutMs);
  });

  try {
    return await Promise.race([action(), timeoutPromise]);
  } catch (error) {
    if (error instanceof PolymarketDiscoveryError) {
      throw error;
    }

    throw mapClobRequestFailure(error, { ...context, operation });
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
}

/**
 * Parse one market object and return all channel candidates.
 */
function collectChannelsFromMarket(market: unknown): MarketChannel[] {
  if (!market || typeof market !== "object") return [];

  const raw = market as MarketLike;
  const conditionId = toStringOrUndefined(raw.condition_id);
  const question = toStringOrUndefined(raw.question);
  const marketSlug = toStringOrUndefined(raw.market_slug);
  const channels: MarketChannel[] = [];

  if (Array.isArray(raw.tokens)) {
    for (const token of raw.tokens) {
      channels.push(
        ...collectTokenChannel(token, conditionId, question).map((channel) => ({
          ...channel,
          ...(marketSlug ? { marketSlug } : {}),
        }))
      );
    }
  }

  if (channels.length === 0 && isString((market as { asset_id?: unknown }).asset_id)) {
    channels.push({
      assetId: String((market as { asset_id?: unknown }).asset_id).trim(),
      ...(conditionId ? { conditionId } : {}),
      ...(question ? { question } : {}),
      ...(marketSlug ? { marketSlug } : {}),
    });
  }

  return channels;
}

/**
 * Fetch all pages from CLOB `/markets`, then extract and deduplicate asset IDs.
 */
async function fetchMarketChannels(
  clobClient: ClobClient,
  timeoutMs: number
): Promise<FetchMarketChannelsResult> {
  const channels: FetchMarketChannelsResult["channels"] = [];
  const seen = new Set<string>();
  let marketCount = 0;
  let nextCursor: string | undefined;
  let pageIndex = 0;

  while (true) {
    const payload = (await withTimeout(
      () => clobClient.getMarkets(nextCursor),
      timeoutMs,
      "clob.getMarkets",
      {
        nextCursor: nextCursor ?? null,
        pageIndex,
      }
    )) as MarketPayload;

    const markets = Array.isArray(payload?.data) ? payload.data : [];
    marketCount += markets.length;

    for (const market of markets) {
      for (const channel of collectChannelsFromMarket(market)) {
        if (!seen.has(channel.assetId)) {
          seen.add(channel.assetId);
          channels.push(channel);
        }
      }
    }

    const cursor = payload?.next_cursor;
    if (!cursor || cursor === "LTE=" || cursor === nextCursor) break;

    nextCursor = cursor;
    pageIndex += 1;

    if (markets.length === 0) break;
  }

  return {
    channels,
    marketCount,
  };
}

function buildSkippedWebsocketSummary(wsUrl: string, reason: string): WsScanSummary {
  return {
    wsUrl: normalizeWsUrl(wsUrl),
    connected: false,
    observedChannels: [],
    messageCount: 0,
    sampleEventCount: 0,
    errors: [reason],
  };
}

/**
 * Connects to market websocket and sends chunked channel subscriptions.
 */
async function probeMarketChannelsFromWebSocket(params: ProbeMarketChannelsParams): Promise<WsScanSummary> {
  const url = normalizeWsUrl(params.wsUrl);

  const observed = new Set<string>();
  const errors: string[] = [];
  let messageCount = 0;
  let sampleEventCount = 0;

  if (!url) {
    throw mapWebsocketInvalidUrl(`Invalid WS URL: ${String(params.wsUrl)}`);
  }

  if (params.assetIds.length === 0) {
    return buildSkippedWebsocketSummary(url, "No discovered channels; WS probe skipped.");
  }

  let ws: WebSocket;
  try {
    ws = new WebSocket(url);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return buildSkippedWebsocketSummary(url, `Unable to initialize websocket: ${message}`);
  }

  const summary: WsScanSummary = {
    wsUrl: url,
    connected: false,
    observedChannels: [],
    messageCount,
    sampleEventCount,
    errors,
  };

  await new Promise<void>((resolve) => {
    const assetChunks = chunk(params.assetIds, params.chunkSize);
    let finished = false;

    const finalize = () => {
      if (finished) return;
      finished = true;

      summary.observedChannels = [...observed].sort();
      summary.messageCount = messageCount;
      summary.sampleEventCount = sampleEventCount;

      if (ws.readyState === ws.OPEN || ws.readyState === ws.CONNECTING) {
        ws.close();
      }

      resolve();
    };

    ws.addEventListener("open", () => {
      summary.connected = true;

      for (const [index, assets] of assetChunks.entries()) {
        const message = {
          type: "market",
          markets: [] as string[],
          assets_ids: assets,
          ...(index === 0 ? { initial_dump: true } : {}),
        };

        ws.send(JSON.stringify(message));
      }

      const ping = setInterval(() => {
        if (ws.readyState === ws.OPEN) {
          ws.send("PING");
        }
      }, 30_000);

      ws.addEventListener("close", () => clearInterval(ping));
    });

    ws.addEventListener("message", (event: MessageEvent) => {
      messageCount += 1;

      const text = parseMessageData(event.data);
      if (!text) return;

      const trimmed = text.trim();
      if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) {
        return;
      }

      try {
        const json = JSON.parse(trimmed) as unknown;
        sampleEventCount += 1;
        extractAssetIdsFromWsPayload(json, observed);
      } catch (error) {
        errors.push(`Non-json WS payload (${String(error)})`);
      }
    });

    ws.addEventListener("error", () => {
      const message = "websocket error";
      if (!errors.includes(message)) {
        errors.push(message);
      }
      finalize();
    });

    ws.addEventListener("close", () => {
      finalize();
    });

    setTimeout(() => {
      if (!summary.connected) {
        errors.push(`Connection timeout / no open event after ${params.durationMs}ms`);
      }

      finalize();
    }, params.durationMs);
  });

  return summary;
}

/**
 * Orchestrates discovery + optional websocket probe.
 */
export async function discoverMarketChannels(config: MarketDiscoveryConfig): Promise<MarketChannelRunResult> {
  const requestKey = discoveryRequestKey(config);
  const existing = inFlightDiscoveries.get(requestKey);
  if (existing) {
    return existing;
  }

  const run = (async (): Promise<MarketChannelRunResult> => {
    assertDiscoveryConfig(config);

    const limit = getDiscoveryConcurrencyLimit();
    if (activeDiscoveryCount >= limit) {
      throw mapDiscoveryConcurrencyLimit(limit, {
        operation: "discoverMarketChannels",
      });
    }

    activeDiscoveryCount += 1;
    try {
      const clobClient = new ClobClient(config.clobApiUrl, config.chainId);

      const safeMarketFetchTimeoutMs =
        Number.isFinite(config.marketFetchTimeoutMs) && config.marketFetchTimeoutMs > 0
          ? Math.floor(config.marketFetchTimeoutMs)
          : DEFAULT_MARKET_FETCH_TIMEOUT_MS;

      const { channels, marketCount } = await fetchMarketChannels(clobClient, safeMarketFetchTimeoutMs);

      const result: MarketChannelRunResult = {
        source: {
          clobApiUrl: config.clobApiUrl,
          chainId: config.chainId,
          marketCount,
          marketChannelCount: channels.length,
        },
        channels: channels,
        wsScan: null,
      };

      if (config.wsUrl) {
        result.wsScan = await probeMarketChannelsFromWebSocket({
          wsUrl: config.wsUrl,
          assetIds: channels.map((channel) => channel.assetId),
          durationMs: config.wsConnectTimeoutMs,
          chunkSize: config.wsChunkSize,
        });
      }

      return result;
    } finally {
      activeDiscoveryCount = Math.max(activeDiscoveryCount - 1, 0);
    }
  })();

  inFlightDiscoveries.set(requestKey, run);

  try {
    return await run;
  } finally {
    inFlightDiscoveries.delete(requestKey);
  }
}

export function assertDiscoveryConfig(config: MarketDiscoveryConfig): void {
  if (!config.clobApiUrl) {
    throw mapInvalidInput("clobApiUrl is required", "clobApiUrl");
  }

  if (Number.isNaN(config.chainId) || config.chainId <= 0) {
    throw mapInvalidInput("chainId must be a positive number", "chainId");
  }

  if (Number.isNaN(config.wsConnectTimeoutMs) || config.wsConnectTimeoutMs <= 0) {
    throw mapInvalidInput("wsConnectTimeoutMs must be a positive number", "wsConnectTimeoutMs");
  }

  if (Number.isNaN(config.wsChunkSize) || config.wsChunkSize <= 0) {
    throw mapInvalidInput("wsChunkSize must be a positive number", "wsChunkSize");
  }

  if (Number.isNaN(config.marketFetchTimeoutMs) || config.marketFetchTimeoutMs <= 0) {
    throw mapInvalidInput("marketFetchTimeoutMs must be a positive number", "marketFetchTimeoutMs");
  }
}
