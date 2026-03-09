import { ClobClient } from "@polymarket/clob-client";

import {
  DEFAULT_CLOB_API_URL,
  DEFAULT_CHAIN_ID,
  DEFAULT_MARKET_FETCH_TIMEOUT_MS,
  DEFAULT_WS_CHUNK_SIZE,
  DEFAULT_WS_CONNECT_TIMEOUT_MS,
  type FetchMarketChannelsResult,
  type MarketDiscoveryConfig,
  type MarketLike,
  type MarketPayload,
  type ProbeMarketChannelsParams,
  type MarketChannel,
  type MarketChannelEstimateResult,
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
type MarketDiscoveryProgress = { marketCount: number; marketChannelCount: number };

function normalizeBooleanLike(value: unknown): boolean | undefined {
  if (typeof value === "boolean") {
    return value;
  }

  if (typeof value === "number") {
    if (value === 1) return true;
    if (value === 0) return false;
    return undefined;
  }

  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(normalized)) return true;
    if (["0", "false", "no", "off"].includes(normalized)) return false;
  }

  return undefined;
}

function normalizeTags(tags: string[] | undefined): string[] {
  if (!tags || tags.length === 0) {
    return [];
  }

  const normalized = tags
    .map((tag) => (typeof tag === "string" ? tag.trim().toLowerCase() : ""))
    .filter((tag) => tag.length > 0);

  const deduped = Array.from(new Set(normalized));
  deduped.sort((left, right) => left.localeCompare(right));
  return deduped;
}

function normalizeQuestionOrSlug(value: unknown): string {
  const normalized = toStringOrUndefined(value);
  return normalized?.trim().toLowerCase() ?? "";
}

function normalizeContains(value: unknown): string {
  const normalized = toStringOrUndefined(value);
  return normalized?.trim().toLowerCase() ?? "";
}

function normalizeIsoDate(value: unknown): number | undefined {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : undefined;
  }

  const normalized = toStringOrUndefined(value);
  if (!normalized) {
    return undefined;
  }

  const parsed = Date.parse(normalized);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function normalizeNumber(value: unknown): number | undefined {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : undefined;
  }

  const normalized = toStringOrUndefined(value);
  if (!normalized) {
    return undefined;
  }

  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseRewardsFields(raw: unknown): {
  hasRates: boolean;
  minSize?: number;
  maxSpread?: number;
} {
  if (raw === null || raw === undefined || typeof raw !== "object" || Array.isArray(raw)) {
    return { hasRates: false };
  }

  const hasRates = "rates" in raw && raw.rates != null;
  const minSize = normalizeNumber((raw as Record<string, unknown>).min_size);
  const maxSpread = normalizeNumber((raw as Record<string, unknown>).max_spread);

  return { hasRates, minSize, maxSpread };
}

function marketTagSet(market: MarketLike): Set<string> {
  const values = market.tags;
  const result = new Set<string>();

  if (!Array.isArray(values)) {
    return result;
  }

  for (const rawTag of values) {
    const tag = toStringOrUndefined(rawTag);
    if (!tag) {
      continue;
    }

    result.add(tag.trim().toLowerCase());
  }

  return result;
}

function matchesFilters(market: MarketLike, config: MarketDiscoveryConfig): boolean {
  if (config.active !== undefined && normalizeBooleanLike(market.active) !== config.active) {
    return false;
  }

  if (config.closed !== undefined && normalizeBooleanLike(market.closed) !== config.closed) {
    return false;
  }

  if (config.archived !== undefined && normalizeBooleanLike(market.archived) !== config.archived) {
    return false;
  }

  if (config.acceptingOrders !== undefined) {
    const accepting = normalizeBooleanLike(market.accepting_orders);
    if (accepting !== config.acceptingOrders) {
      return false;
    }
  }

  if (config.minimumOrderSizeMin !== undefined) {
    const minimumOrderSize = normalizeNumber(market.minimum_order_size);
    if (minimumOrderSize === undefined || minimumOrderSize < config.minimumOrderSizeMin) {
      return false;
    }
  }

  if (config.minimumOrderSizeMax !== undefined) {
    const minimumOrderSize = normalizeNumber(market.minimum_order_size);
    if (minimumOrderSize === undefined || minimumOrderSize > config.minimumOrderSizeMax) {
      return false;
    }
  }

  if (config.enableOrderBook !== undefined) {
    const enableOrderBook = normalizeBooleanLike(market.enable_order_book);
    if (enableOrderBook !== config.enableOrderBook) {
      return false;
    }
  }

  if (config.minimumTickSizeMin !== undefined) {
    const minimumTickSize = normalizeNumber(market.minimum_tick_size);
    if (minimumTickSize === undefined || minimumTickSize < config.minimumTickSizeMin) {
      return false;
    }
  }

  if (config.minimumTickSizeMax !== undefined) {
    const minimumTickSize = normalizeNumber(market.minimum_tick_size);
    if (minimumTickSize === undefined || minimumTickSize > config.minimumTickSizeMax) {
      return false;
    }
  }

  if (config.makerBaseFeeMin !== undefined) {
    const makerBaseFee = normalizeNumber(market.maker_base_fee);
    if (makerBaseFee === undefined || makerBaseFee < config.makerBaseFeeMin) {
      return false;
    }
  }

  if (config.makerBaseFeeMax !== undefined) {
    const makerBaseFee = normalizeNumber(market.maker_base_fee);
    if (makerBaseFee === undefined || makerBaseFee > config.makerBaseFeeMax) {
      return false;
    }
  }

  if (config.takerBaseFeeMin !== undefined) {
    const takerBaseFee = normalizeNumber(market.taker_base_fee);
    if (takerBaseFee === undefined || takerBaseFee < config.takerBaseFeeMin) {
      return false;
    }
  }

  if (config.takerBaseFeeMax !== undefined) {
    const takerBaseFee = normalizeNumber(market.taker_base_fee);
    if (takerBaseFee === undefined || takerBaseFee > config.takerBaseFeeMax) {
      return false;
    }
  }

  if (config.notificationsEnabled !== undefined) {
    const notificationsEnabled = normalizeBooleanLike(market.notifications_enabled);
    if (notificationsEnabled !== config.notificationsEnabled) {
      return false;
    }
  }

  if (config.negRisk !== undefined) {
    const negRisk = normalizeBooleanLike(market.neg_risk);
    if (negRisk !== config.negRisk) {
      return false;
    }
  }

  if (config.fpmm !== undefined) {
    const fpmm = normalizeContains(market.fpmm);
    if (!fpmm.includes(config.fpmm)) {
      return false;
    }
  }

  if (config.secondsDelayMin !== undefined) {
    const secondsDelay = normalizeNumber(market.seconds_delay);
    if (secondsDelay === undefined || secondsDelay < config.secondsDelayMin) {
      return false;
    }
  }

  if (config.secondsDelayMax !== undefined) {
    const secondsDelay = normalizeNumber(market.seconds_delay);
    if (secondsDelay === undefined || secondsDelay > config.secondsDelayMax) {
      return false;
    }
  }

  if (config.acceptingOrderTimestampMin !== undefined) {
    const acceptingOrderTimestamp = normalizeNumber(market.accepting_order_timestamp);
    if (
      acceptingOrderTimestamp === undefined ||
      acceptingOrderTimestamp < config.acceptingOrderTimestampMin
    ) {
      return false;
    }
  }

  if (config.acceptingOrderTimestampMax !== undefined) {
    const acceptingOrderTimestamp = normalizeNumber(market.accepting_order_timestamp);
    if (
      acceptingOrderTimestamp === undefined ||
      acceptingOrderTimestamp > config.acceptingOrderTimestampMax
    ) {
      return false;
    }
  }

  if (config.endDateIsoMin !== undefined) {
    const endDateIso = normalizeIsoDate(market.end_date_iso);
    const minEndDateIso = Date.parse(config.endDateIsoMin);
    if (endDateIso === undefined || endDateIso < minEndDateIso) {
      return false;
    }
  }

  if (config.endDateIsoMax !== undefined) {
    const endDateIso = normalizeIsoDate(market.end_date_iso);
    const maxEndDateIso = Date.parse(config.endDateIsoMax);
    if (endDateIso === undefined || endDateIso > maxEndDateIso) {
      return false;
    }
  }

  if (config.gameStartTimeMin !== undefined) {
    const gameStartTime = normalizeIsoDate(market.game_start_time);
    const minGameStartTime = Date.parse(config.gameStartTimeMin);
    if (gameStartTime === undefined || gameStartTime < minGameStartTime) {
      return false;
    }
  }

  if (config.gameStartTimeMax !== undefined) {
    const gameStartTime = normalizeIsoDate(market.game_start_time);
    const maxGameStartTime = Date.parse(config.gameStartTimeMax);
    if (gameStartTime === undefined || gameStartTime > maxGameStartTime) {
      return false;
    }
  }

  if (config.descriptionContains) {
    const description = normalizeContains(market.description);
    if (!description.includes(config.descriptionContains)) {
      return false;
    }
  }

  if (config.conditionIdContains) {
    const conditionId = normalizeContains(market.condition_id);
    if (!conditionId.includes(config.conditionIdContains)) {
      return false;
    }
  }

  if (config.negRiskMarketIdContains) {
    const negRiskMarketId = normalizeContains(market.neg_risk_market_id);
    if (!negRiskMarketId.includes(config.negRiskMarketIdContains)) {
      return false;
    }
  }

  if (config.negRiskRequestIdContains) {
    const negRiskRequestId = normalizeContains(market.neg_risk_request_id);
    if (!negRiskRequestId.includes(config.negRiskRequestIdContains)) {
      return false;
    }
  }

  if (config.questionIdContains) {
    const questionId = normalizeContains(market.question_id);
    if (!questionId.includes(config.questionIdContains)) {
      return false;
    }
  }

  const rewards = parseRewardsFields(market.rewards);
  if (config.rewardsHasRates !== undefined && rewards.hasRates !== config.rewardsHasRates) {
    return false;
  }

  if (config.rewardsMinSizeMin !== undefined) {
    if (rewards.minSize === undefined || rewards.minSize < config.rewardsMinSizeMin) {
      return false;
    }
  }

  if (config.rewardsMinSizeMax !== undefined) {
    if (rewards.minSize === undefined || rewards.minSize > config.rewardsMinSizeMax) {
      return false;
    }
  }

  if (config.rewardsMaxSpreadMin !== undefined) {
    if (rewards.maxSpread === undefined || rewards.maxSpread < config.rewardsMaxSpreadMin) {
      return false;
    }
  }

  if (config.rewardsMaxSpreadMax !== undefined) {
    if (rewards.maxSpread === undefined || rewards.maxSpread > config.rewardsMaxSpreadMax) {
      return false;
    }
  }

  if (config.iconContains) {
    const icon = normalizeContains(market.icon);
    if (!icon.includes(config.iconContains)) {
      return false;
    }
  }

  if (config.imageContains) {
    const image = normalizeContains(market.image);
    if (!image.includes(config.imageContains)) {
      return false;
    }
  }

  if (config.isFiftyFiftyOutcome !== undefined) {
    const is50 = normalizeBooleanLike(market.is_50_50_outcome);
    if (is50 !== config.isFiftyFiftyOutcome) {
      return false;
    }
  }

  if (config.questionContains) {
    const question = normalizeQuestionOrSlug(market.question);
    if (!question.includes(config.questionContains)) {
      return false;
    }
  }

  if (config.marketSlugContains) {
    const marketSlug = normalizeQuestionOrSlug(market.market_slug);
    if (!marketSlug.includes(config.marketSlugContains)) {
      return false;
    }
  }

  if (config.tags && config.tags.length > 0) {
    const marketTags = marketTagSet(market);
    const hasMatch = config.tags.some((tag) => marketTags.has(tag.toLowerCase()));
    if (!hasMatch) {
      return false;
    }
  }

  return true;
}

function discoveryRequestKey(config: MarketDiscoveryConfig): string {
  const normalizedTags = normalizeTags(config.tags);

  return JSON.stringify({
    clobApiUrl: config.clobApiUrl,
    chainId: config.chainId,
    maxMarkets: config.maxMarkets,
    wsUrl: config.wsUrl ?? null,
    wsConnectTimeoutMs: config.wsConnectTimeoutMs,
    wsChunkSize: config.wsChunkSize,
    marketFetchTimeoutMs: config.marketFetchTimeoutMs,
    acceptingOrders: config.acceptingOrders,
    minimumOrderSizeMin: config.minimumOrderSizeMin,
    minimumOrderSizeMax: config.minimumOrderSizeMax,
    minimumTickSizeMin: config.minimumTickSizeMin,
    minimumTickSizeMax: config.minimumTickSizeMax,
    makerBaseFeeMin: config.makerBaseFeeMin,
    makerBaseFeeMax: config.makerBaseFeeMax,
    takerBaseFeeMin: config.takerBaseFeeMin,
    takerBaseFeeMax: config.takerBaseFeeMax,
    enableOrderBook: config.enableOrderBook,
    notificationsEnabled: config.notificationsEnabled,
    negRisk: config.negRisk,
    fpmm: config.fpmm,
    secondsDelayMin: config.secondsDelayMin,
    secondsDelayMax: config.secondsDelayMax,
    acceptingOrderTimestampMin: config.acceptingOrderTimestampMin,
    acceptingOrderTimestampMax: config.acceptingOrderTimestampMax,
    questionIdContains: config.questionIdContains,
    rewardsHasRates: config.rewardsHasRates,
    rewardsMinSizeMin: config.rewardsMinSizeMin,
    rewardsMinSizeMax: config.rewardsMinSizeMax,
    rewardsMaxSpreadMin: config.rewardsMaxSpreadMin,
    rewardsMaxSpreadMax: config.rewardsMaxSpreadMax,
    iconContains: config.iconContains,
    imageContains: config.imageContains,
    descriptionContains: config.descriptionContains,
    conditionIdContains: config.conditionIdContains,
    negRiskMarketIdContains: config.negRiskMarketIdContains,
    negRiskRequestIdContains: config.negRiskRequestIdContains,
    endDateIsoMin: config.endDateIsoMin,
    endDateIsoMax: config.endDateIsoMax,
    gameStartTimeMin: config.gameStartTimeMin,
    gameStartTimeMax: config.gameStartTimeMax,
    active: config.active,
    closed: config.closed,
    archived: config.archived,
    isFiftyFiftyOutcome: config.isFiftyFiftyOutcome,
    tags: normalizedTags,
    questionContains: config.questionContains,
    marketSlugContains: config.marketSlugContains,
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
  timeoutMs: number,
  config: MarketDiscoveryConfig,
  onProgress?: (progress: MarketDiscoveryProgress) => void | Promise<void>
): Promise<FetchMarketChannelsResult> {
  const channels: FetchMarketChannelsResult["channels"] = [];
  const seen = new Set<string>();
  let marketCount = 0;
  const hasMaxMarkets = config.maxMarkets !== undefined && Number.isInteger(config.maxMarkets) && config.maxMarkets > 0;
  let pagesScanned = 0;
  let stoppedByLimit = false;
  let hasMore = false;
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
    let reachedLimit = false;
    pagesScanned += 1;

    for (const market of markets as MarketLike[]) {
      if (!matchesFilters(market, config)) {
        continue;
      }
      marketCount += 1;

      for (const channel of collectChannelsFromMarket(market)) {
        if (!seen.has(channel.assetId)) {
          seen.add(channel.assetId);
          channels.push(channel);
        }
      }

      if (hasMaxMarkets && marketCount >= (config.maxMarkets as number)) {
        hasMore = true;
        stoppedByLimit = true;
        reachedLimit = true;
        break;
      }
    }

    const cursor = payload?.next_cursor;
    if (onProgress) {
      await onProgress({ marketCount, marketChannelCount: channels.length });
    }

    if (reachedLimit) {
      break;
    }

    if (!cursor || cursor === "LTE=" || cursor === nextCursor) {
      break;
    }

    nextCursor = cursor;
    pageIndex += 1;

    if (markets.length === 0) break;
  }

  return {
    channels,
    marketCount,
    pagesScanned,
    stoppedByLimit,
    hasMore,
  };
}

export async function estimateMarketChannels(
  config: MarketDiscoveryConfig,
  sampleLimit: number
): Promise<MarketChannelEstimateResult> {
  const safeSampleLimit =
    Number.isInteger(sampleLimit) && Number.isFinite(sampleLimit) && sampleLimit > 0
      ? sampleLimit
      : undefined;

  if (safeSampleLimit === undefined) {
    throw mapInvalidInput("sampleLimit must be a positive integer", "sampleLimit");
  }

  assertDiscoveryConfig(config);

  const normalizedConfig: MarketDiscoveryConfig = {
    ...config,
    maxMarkets: safeSampleLimit,
  };

  const clobClient = new ClobClient(normalizedConfig.clobApiUrl, normalizedConfig.chainId);

  const safeMarketFetchTimeoutMs =
    Number.isFinite(normalizedConfig.marketFetchTimeoutMs) && normalizedConfig.marketFetchTimeoutMs > 0
      ? Math.floor(normalizedConfig.marketFetchTimeoutMs)
      : DEFAULT_MARKET_FETCH_TIMEOUT_MS;

  const result = await fetchMarketChannels(clobClient, safeMarketFetchTimeoutMs, normalizedConfig);

  return {
    source: {
      clobApiUrl: normalizedConfig.clobApiUrl,
      chainId: normalizedConfig.chainId,
      marketCount: result.marketCount,
      marketChannelCount: result.channels.length,
      sampleLimit: safeSampleLimit,
      pagesScanned: result.pagesScanned,
      stoppedByLimit: result.stoppedByLimit,
      hasMore: result.hasMore,
    },
    channels: result.channels,
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
export async function discoverMarketChannels(
  config: MarketDiscoveryConfig,
  onProgress?: (progress: MarketDiscoveryProgress) => void | Promise<void>
): Promise<MarketChannelRunResult> {
  const requestKey = discoveryRequestKey(config);
  const existing = inFlightDiscoveries.get(requestKey);
  if (existing) {
    return existing;
  }

  const run = (async (): Promise<MarketChannelRunResult> => {
    assertDiscoveryConfig(config);

    const normalizedConfig: MarketDiscoveryConfig = {
      ...config,
      tags: normalizeTags(config.tags),
      questionContains: config.questionContains?.trim().toLowerCase(),
      marketSlugContains: config.marketSlugContains?.trim().toLowerCase(),
      descriptionContains: config.descriptionContains?.trim().toLowerCase(),
      questionIdContains: config.questionIdContains?.trim().toLowerCase(),
      iconContains: config.iconContains?.trim().toLowerCase(),
      imageContains: config.imageContains?.trim().toLowerCase(),
      conditionIdContains: config.conditionIdContains?.trim().toLowerCase(),
      fpmm: config.fpmm?.trim().toLowerCase(),
      negRiskMarketIdContains: config.negRiskMarketIdContains?.trim().toLowerCase(),
      negRiskRequestIdContains: config.negRiskRequestIdContains?.trim().toLowerCase(),
    };

    const clobClient = new ClobClient(normalizedConfig.clobApiUrl, normalizedConfig.chainId);

    const safeMarketFetchTimeoutMs =
      Number.isFinite(normalizedConfig.marketFetchTimeoutMs) && normalizedConfig.marketFetchTimeoutMs > 0
        ? Math.floor(normalizedConfig.marketFetchTimeoutMs)
        : DEFAULT_MARKET_FETCH_TIMEOUT_MS;

    const { channels, marketCount } = await fetchMarketChannels(
      clobClient,
      safeMarketFetchTimeoutMs,
      normalizedConfig,
      onProgress
    );

    const result: MarketChannelRunResult = {
      source: {
        clobApiUrl: normalizedConfig.clobApiUrl,
        chainId: normalizedConfig.chainId,
        marketCount,
        marketChannelCount: channels.length,
      },
      channels,
      wsScan: null,
    };

    if (normalizedConfig.wsUrl) {
      result.wsScan = await probeMarketChannelsFromWebSocket({
        wsUrl: normalizedConfig.wsUrl,
        assetIds: channels.map((channel) => channel.assetId),
        durationMs: normalizedConfig.wsConnectTimeoutMs,
        chunkSize: normalizedConfig.wsChunkSize,
      });
    }

    return result;
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

  if (
    config.maxMarkets !== undefined &&
    (!Number.isInteger(config.maxMarkets) || !Number.isFinite(config.maxMarkets) || config.maxMarkets <= 0)
  ) {
    throw mapInvalidInput("maxMarkets must be a positive integer", "maxMarkets");
  }

  if (config.questionContains !== undefined && typeof config.questionContains !== "string") {
    throw mapInvalidInput("questionContains must be a string", "questionContains");
  }

  if (config.marketSlugContains !== undefined && typeof config.marketSlugContains !== "string") {
    throw mapInvalidInput("marketSlugContains must be a string", "marketSlugContains");
  }

  if (config.questionIdContains !== undefined && typeof config.questionIdContains !== "string") {
    throw mapInvalidInput("questionIdContains must be a string", "questionIdContains");
  }

  if (config.tags !== undefined) {
    if (!Array.isArray(config.tags)) {
      throw mapInvalidInput("tags must be an array of strings", "tags");
    }

    const allStrings = config.tags.every((tag) => typeof tag === "string" && tag.trim().length > 0);
    if (!allStrings) {
      throw mapInvalidInput("tags must be non-empty strings", "tags");
    }
  }

  if (config.active !== undefined && typeof config.active !== "boolean") {
    throw mapInvalidInput("active must be a boolean", "active");
  }

  if (config.closed !== undefined && typeof config.closed !== "boolean") {
    throw mapInvalidInput("closed must be a boolean", "closed");
  }

  if (config.archived !== undefined && typeof config.archived !== "boolean") {
    throw mapInvalidInput("archived must be a boolean", "archived");
  }

  if (
    config.isFiftyFiftyOutcome !== undefined &&
    typeof config.isFiftyFiftyOutcome !== "boolean"
  ) {
    throw mapInvalidInput("isFiftyFiftyOutcome must be a boolean", "isFiftyFiftyOutcome");
  }

  if (config.acceptingOrders !== undefined && typeof config.acceptingOrders !== "boolean") {
    throw mapInvalidInput("acceptingOrders must be a boolean", "acceptingOrders");
  }

  if (
    config.minimumOrderSizeMin !== undefined &&
    (typeof config.minimumOrderSizeMin !== "number" ||
      Number.isNaN(config.minimumOrderSizeMin) ||
      config.minimumOrderSizeMin < 0)
  ) {
    throw mapInvalidInput("minimumOrderSizeMin must be a non-negative number", "minimumOrderSizeMin");
  }

  if (
    config.minimumOrderSizeMax !== undefined &&
    (typeof config.minimumOrderSizeMax !== "number" ||
      Number.isNaN(config.minimumOrderSizeMax) ||
      config.minimumOrderSizeMax < 0)
  ) {
    throw mapInvalidInput("minimumOrderSizeMax must be a non-negative number", "minimumOrderSizeMax");
  }

  if (
    config.minimumOrderSizeMin !== undefined &&
    config.minimumOrderSizeMax !== undefined &&
    config.minimumOrderSizeMax < config.minimumOrderSizeMin
  ) {
    throw mapInvalidInput("minimumOrderSizeMax must be >= minimumOrderSizeMin", "minimumOrderSizeMax");
  }

  if (config.minimumTickSizeMin !== undefined) {
    if (
      typeof config.minimumTickSizeMin !== "number" ||
      Number.isNaN(config.minimumTickSizeMin) ||
      config.minimumTickSizeMin < 0
    ) {
      throw mapInvalidInput("minimumTickSizeMin must be a non-negative number", "minimumTickSizeMin");
    }
  }

  if (config.minimumTickSizeMax !== undefined) {
    if (
      typeof config.minimumTickSizeMax !== "number" ||
      Number.isNaN(config.minimumTickSizeMax) ||
      config.minimumTickSizeMax < 0
    ) {
      throw mapInvalidInput("minimumTickSizeMax must be a non-negative number", "minimumTickSizeMax");
    }
  }

  if (
    config.minimumTickSizeMin !== undefined &&
    config.minimumTickSizeMax !== undefined &&
    config.minimumTickSizeMax < config.minimumTickSizeMin
  ) {
    throw mapInvalidInput(
      "minimumTickSizeMax must be >= minimumTickSizeMin",
      "minimumTickSizeMax"
    );
  }

  if (config.makerBaseFeeMin !== undefined) {
    if (
      typeof config.makerBaseFeeMin !== "number" ||
      Number.isNaN(config.makerBaseFeeMin) ||
      config.makerBaseFeeMin < 0
    ) {
      throw mapInvalidInput("makerBaseFeeMin must be a non-negative number", "makerBaseFeeMin");
    }
  }

  if (config.makerBaseFeeMax !== undefined) {
    if (
      typeof config.makerBaseFeeMax !== "number" ||
      Number.isNaN(config.makerBaseFeeMax) ||
      config.makerBaseFeeMax < 0
    ) {
      throw mapInvalidInput("makerBaseFeeMax must be a non-negative number", "makerBaseFeeMax");
    }
  }

  if (
    config.makerBaseFeeMin !== undefined &&
    config.makerBaseFeeMax !== undefined &&
    config.makerBaseFeeMax < config.makerBaseFeeMin
  ) {
    throw mapInvalidInput(
      "makerBaseFeeMax must be >= makerBaseFeeMin",
      "makerBaseFeeMax"
    );
  }

  if (config.takerBaseFeeMin !== undefined) {
    if (
      typeof config.takerBaseFeeMin !== "number" ||
      Number.isNaN(config.takerBaseFeeMin) ||
      config.takerBaseFeeMin < 0
    ) {
      throw mapInvalidInput("takerBaseFeeMin must be a non-negative number", "takerBaseFeeMin");
    }
  }

  if (config.takerBaseFeeMax !== undefined) {
    if (
      typeof config.takerBaseFeeMax !== "number" ||
      Number.isNaN(config.takerBaseFeeMax) ||
      config.takerBaseFeeMax < 0
    ) {
      throw mapInvalidInput("takerBaseFeeMax must be a non-negative number", "takerBaseFeeMax");
    }
  }

  if (
    config.takerBaseFeeMin !== undefined &&
    config.takerBaseFeeMax !== undefined &&
    config.takerBaseFeeMax < config.takerBaseFeeMin
  ) {
    throw mapInvalidInput(
      "takerBaseFeeMax must be >= takerBaseFeeMin",
      "takerBaseFeeMax"
    );
  }

  if (config.enableOrderBook !== undefined && typeof config.enableOrderBook !== "boolean") {
    throw mapInvalidInput("enableOrderBook must be a boolean", "enableOrderBook");
  }

  if (config.notificationsEnabled !== undefined && typeof config.notificationsEnabled !== "boolean") {
    throw mapInvalidInput("notificationsEnabled must be a boolean", "notificationsEnabled");
  }

  if (config.negRisk !== undefined && typeof config.negRisk !== "boolean") {
    throw mapInvalidInput("negRisk must be a boolean", "negRisk");
  }

  if (config.secondsDelayMin !== undefined) {
    if (
      typeof config.secondsDelayMin !== "number" ||
      Number.isNaN(config.secondsDelayMin) ||
      config.secondsDelayMin < 0
    ) {
      throw mapInvalidInput("secondsDelayMin must be a non-negative number", "secondsDelayMin");
    }
  }

  if (config.secondsDelayMax !== undefined) {
    if (
      typeof config.secondsDelayMax !== "number" ||
      Number.isNaN(config.secondsDelayMax) ||
      config.secondsDelayMax < 0
    ) {
      throw mapInvalidInput("secondsDelayMax must be a non-negative number", "secondsDelayMax");
    }
  }

  if (
    config.secondsDelayMin !== undefined &&
    config.secondsDelayMax !== undefined &&
    config.secondsDelayMax < config.secondsDelayMin
  ) {
    throw mapInvalidInput("secondsDelayMax must be >= secondsDelayMin", "secondsDelayMax");
  }

  if (
    config.acceptingOrderTimestampMin !== undefined &&
    (!Number.isFinite(config.acceptingOrderTimestampMin) || config.acceptingOrderTimestampMin < 0)
  ) {
    throw mapInvalidInput(
      "acceptingOrderTimestampMin must be a valid number",
      "acceptingOrderTimestampMin"
    );
  }

  if (
    config.acceptingOrderTimestampMax !== undefined &&
    (!Number.isFinite(config.acceptingOrderTimestampMax) || config.acceptingOrderTimestampMax < 0)
  ) {
    throw mapInvalidInput(
      "acceptingOrderTimestampMax must be a valid number",
      "acceptingOrderTimestampMax"
    );
  }

  if (
    config.acceptingOrderTimestampMin !== undefined &&
    config.acceptingOrderTimestampMax !== undefined &&
    config.acceptingOrderTimestampMax < config.acceptingOrderTimestampMin
  ) {
    throw mapInvalidInput(
      "acceptingOrderTimestampMax must be >= acceptingOrderTimestampMin",
      "acceptingOrderTimestampMax"
    );
  }

  if (config.endDateIsoMin !== undefined && Number.isNaN(Date.parse(config.endDateIsoMin))) {
    throw mapInvalidInput("endDateIsoMin must be a valid date", "endDateIsoMin");
  }

  if (config.endDateIsoMax !== undefined && Number.isNaN(Date.parse(config.endDateIsoMax))) {
    throw mapInvalidInput("endDateIsoMax must be a valid date", "endDateIsoMax");
  }

  if (
    config.endDateIsoMin !== undefined &&
    config.endDateIsoMax !== undefined &&
    Date.parse(config.endDateIsoMax) < Date.parse(config.endDateIsoMin)
  ) {
    throw mapInvalidInput("endDateIsoMax must be >= endDateIsoMin", "endDateIsoMax");
  }

  if (config.gameStartTimeMin !== undefined && Number.isNaN(Date.parse(config.gameStartTimeMin))) {
    throw mapInvalidInput("gameStartTimeMin must be a valid date", "gameStartTimeMin");
  }

  if (config.gameStartTimeMax !== undefined && Number.isNaN(Date.parse(config.gameStartTimeMax))) {
    throw mapInvalidInput("gameStartTimeMax must be a valid date", "gameStartTimeMax");
  }

  if (
    config.gameStartTimeMin !== undefined &&
    config.gameStartTimeMax !== undefined &&
    Date.parse(config.gameStartTimeMax) < Date.parse(config.gameStartTimeMin)
  ) {
    throw mapInvalidInput("gameStartTimeMax must be >= gameStartTimeMin", "gameStartTimeMax");
  }

  if (config.fpmm !== undefined && typeof config.fpmm !== "string") {
    throw mapInvalidInput("fpmm must be a string", "fpmm");
  }

  if (config.iconContains !== undefined && typeof config.iconContains !== "string") {
    throw mapInvalidInput("iconContains must be a string", "iconContains");
  }

  if (config.imageContains !== undefined && typeof config.imageContains !== "string") {
    throw mapInvalidInput("imageContains must be a string", "imageContains");
  }

  if (config.rewardsHasRates !== undefined && typeof config.rewardsHasRates !== "boolean") {
    throw mapInvalidInput("rewardsHasRates must be a boolean", "rewardsHasRates");
  }

  if (config.rewardsMinSizeMin !== undefined) {
    if (
      typeof config.rewardsMinSizeMin !== "number" ||
      Number.isNaN(config.rewardsMinSizeMin) ||
      config.rewardsMinSizeMin < 0
    ) {
      throw mapInvalidInput("rewardsMinSizeMin must be a non-negative number", "rewardsMinSizeMin");
    }
  }

  if (config.rewardsMinSizeMax !== undefined) {
    if (
      typeof config.rewardsMinSizeMax !== "number" ||
      Number.isNaN(config.rewardsMinSizeMax) ||
      config.rewardsMinSizeMax < 0
    ) {
      throw mapInvalidInput("rewardsMinSizeMax must be a non-negative number", "rewardsMinSizeMax");
    }
  }

  if (
    config.rewardsMinSizeMin !== undefined &&
    config.rewardsMinSizeMax !== undefined &&
    config.rewardsMinSizeMax < config.rewardsMinSizeMin
  ) {
    throw mapInvalidInput(
      "rewardsMinSizeMax must be >= rewardsMinSizeMin",
      "rewardsMinSizeMax"
    );
  }

  if (config.rewardsMaxSpreadMin !== undefined) {
    if (
      typeof config.rewardsMaxSpreadMin !== "number" ||
      Number.isNaN(config.rewardsMaxSpreadMin) ||
      config.rewardsMaxSpreadMin < 0
    ) {
      throw mapInvalidInput(
        "rewardsMaxSpreadMin must be a non-negative number",
        "rewardsMaxSpreadMin"
      );
    }
  }

  if (config.rewardsMaxSpreadMax !== undefined) {
    if (
      typeof config.rewardsMaxSpreadMax !== "number" ||
      Number.isNaN(config.rewardsMaxSpreadMax) ||
      config.rewardsMaxSpreadMax < 0
    ) {
      throw mapInvalidInput(
        "rewardsMaxSpreadMax must be a non-negative number",
        "rewardsMaxSpreadMax"
      );
    }
  }

  if (
    config.rewardsMaxSpreadMin !== undefined &&
    config.rewardsMaxSpreadMax !== undefined &&
    config.rewardsMaxSpreadMax < config.rewardsMaxSpreadMin
  ) {
    throw mapInvalidInput(
      "rewardsMaxSpreadMax must be >= rewardsMaxSpreadMin",
      "rewardsMaxSpreadMax"
    );
  }

  if (config.descriptionContains !== undefined && typeof config.descriptionContains !== "string") {
    throw mapInvalidInput("descriptionContains must be a string", "descriptionContains");
  }

  if (config.conditionIdContains !== undefined && typeof config.conditionIdContains !== "string") {
    throw mapInvalidInput("conditionIdContains must be a string", "conditionIdContains");
  }

  if (config.negRiskMarketIdContains !== undefined && typeof config.negRiskMarketIdContains !== "string") {
    throw mapInvalidInput("negRiskMarketIdContains must be a string", "negRiskMarketIdContains");
  }

  if (config.negRiskRequestIdContains !== undefined && typeof config.negRiskRequestIdContains !== "string") {
    throw mapInvalidInput("negRiskRequestIdContains must be a string", "negRiskRequestIdContains");
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

export { discoveryRequestKey };
