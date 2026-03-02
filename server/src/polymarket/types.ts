export const DEFAULT_CLOB_API_URL = "https://clob.polymarket.com";
export const DEFAULT_CHAIN_ID = 137;
export const DEFAULT_WS_CONNECT_TIMEOUT_MS = 12_000;
export const DEFAULT_WS_CHUNK_SIZE = 500;
export const DEFAULT_MARKET_FETCH_TIMEOUT_MS = 15_000;
export const DEFAULT_MARKET_DISCOVERY_CONCURRENCY_LIMIT = 4;

/**
 * Legacy discovery config contract used by discovery worker and CLI.
 */
export type MarketDiscoveryConfig = {
  clobApiUrl: string;
  chainId: number;
  wsUrl?: string;
  wsConnectTimeoutMs: number;
  wsChunkSize: number;
  marketFetchTimeoutMs: number;
};

/**
 * Structured run lifecycle states.
 */
export type DiscoveryRunStatus = "queued" | "running" | "succeeded" | "partial" | "failed";

/**
 * Canonical request parsed by API/controller for run creation.
 */
export type DiscoveryRunRequest = MarketDiscoveryConfig & {
  /**
   * Optional compatibility wait window used only by the legacy GET wrapper.
   */
  waitMs?: number;
};

/**
 * Run summary returned by creation endpoints and polling helpers.
 */
export interface DiscoveryRunSummary {
  runId: string;
  status: DiscoveryRunStatus;
  dedupeKey: string;
  pollUrl: string;
  requestId: string;
}

/**
 * Minimal page contract for channels list.
 */
export interface PaginatedChannels {
  items: MarketChannel[];
  page: {
    offset: number;
    limit: number;
    total: number;
    hasMore: boolean;
  };
}

/**
 * Domain output for discovery run reads.
 */
export interface DiscoveryRunReadModel {
  run: {
    id: string;
    status: DiscoveryRunStatus;
    dedupeKey: string;
    requestedAt: string;
    startedAt?: string | null;
    completedAt?: string | null;
    source: {
      clobApiUrl: string;
      chainId: number;
      wsUrl?: string;
      wsConnectTimeoutMs: number;
      wsChunkSize: number;
      marketFetchTimeoutMs: number;
    };
    marketCount: number;
    marketChannelCount: number;
    errorCode?: string | null;
    errorMessage?: string | null;
    errorRetryable?: boolean | null;
    requestId: string;
  };
  channels: PaginatedChannels;
  wsScan: WsScanSummary | null;
}

/**
 * Response returned from create endpoints.
 */
export interface CreateRunResult {
  status: "queued" | "running" | "succeeded";
  runId: string;
  pollUrl: string;
  requestId: string;
}

/**
 * Response from compatibility wait path.
 */
export interface CompatibilityRunResult {
  status: "queued" | "running";
  runId: string;
  pollUrl: string;
  requestId: string;
  shell: DiscoveryRunSummary;
  payload?: MarketChannelRunResult;
}

/**
 * Broad JSON object shape used while traversing unknown payloads.
 */
export type JsonObject = Record<string, unknown>;

/**
 * Minimal shape of `/markets` responses used by the discovery script.
 *
 * `data` is the page payload and `next_cursor` controls pagination.
 */
export type MarketPayload = {
  /**
   * One page of market rows.
   */
  data?: unknown[];
  /**
   * Cursor for the next page. A terminal/missing value means paging ends.
   */
  next_cursor?: string | null;
};

/**
 * Minimal token shape read from CLOB market payloads.
 */
export type MarketToken = {
  token_id?: unknown;
  tokenId?: unknown;
  asset_id?: unknown;
  assetId?: unknown;
  outcome?: unknown;
};

/**
 * Minimal market payload object shape used by the service.
 */
export type MarketLike = {
  condition_id?: unknown;
  question?: unknown;
  tokens?: unknown;
  market_slug?: unknown;
};

/**
 * Canonical shape used by the discovery domain.
 */
export type MarketChannel = {
  assetId: string;
  conditionId?: string;
  question?: string;
  outcome?: string;
  marketSlug?: string;
};

export type WsScanSummary = {
  wsUrl: string;
  connected: boolean;
  observedChannels: string[];
  messageCount: number;
  sampleEventCount: number;
  errors: string[];
};

export type FetchMarketChannelsResult = {
  channels: MarketChannel[];
  marketCount: number;
};

export type ProbeMarketChannelsParams = {
  wsUrl: string;
  assetIds: string[];
  durationMs: number;
  chunkSize: number;
};

export type MarketChannelRunResult = {
  source: {
    clobApiUrl: string;
    chainId: number;
    marketCount: number;
    marketChannelCount: number;
  };
  channels: MarketChannel[];
  wsScan: WsScanSummary | null;
};
