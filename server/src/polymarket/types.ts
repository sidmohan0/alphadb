export const DEFAULT_CLOB_API_URL = "https://clob.polymarket.com";
export const DEFAULT_CHAIN_ID = 137;
export const DEFAULT_WS_CONNECT_TIMEOUT_MS = 12_000;
export const DEFAULT_WS_CHUNK_SIZE = 500;
export const DEFAULT_MARKET_FETCH_TIMEOUT_MS = 15_000;
export const DEFAULT_MARKET_DISCOVERY_CONCURRENCY_LIMIT = 4;

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

export type MarketDiscoveryConfig = {
  clobApiUrl: string;
  chainId: number;
  wsUrl?: string;
  wsConnectTimeoutMs: number;
  wsChunkSize: number;
  marketFetchTimeoutMs: number;
};
