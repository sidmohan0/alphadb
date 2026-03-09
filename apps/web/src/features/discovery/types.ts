export type DiscoveryRunStatus = "queued" | "running" | "partial" | "succeeded" | "failed";

export type DiscoveryPhase = "idle" | "submitting" | "polling" | "completed" | "failed" | "error";

export interface DiscoveryRunShell {
  status: DiscoveryRunStatus;
  runId: string;
  pollUrl: string;
  requestId: string;
}

export interface DiscoverySource {
  clobApiUrl: string;
  chainId: number;
  maxMarkets?: number;
  wsUrl?: string;
  wsConnectTimeoutMs: number;
  wsChunkSize: number;
  marketFetchTimeoutMs: number;
  acceptingOrders?: boolean;
  enableOrderBook?: boolean;
  minimumOrderSizeMin?: number;
  minimumOrderSizeMax?: number;
  minimumTickSizeMin?: number;
  minimumTickSizeMax?: number;
  makerBaseFeeMin?: number;
  makerBaseFeeMax?: number;
  takerBaseFeeMin?: number;
  takerBaseFeeMax?: number;
  notificationsEnabled?: boolean;
  negRisk?: boolean;
  fpmm?: string;
  secondsDelayMin?: number;
  secondsDelayMax?: number;
  acceptingOrderTimestampMin?: number;
  acceptingOrderTimestampMax?: number;
  questionIdContains?: string;
  rewardsHasRates?: boolean;
  rewardsMinSizeMin?: number;
  rewardsMinSizeMax?: number;
  rewardsMaxSpreadMin?: number;
  rewardsMaxSpreadMax?: number;
  iconContains?: string;
  imageContains?: string;
  descriptionContains?: string;
  conditionIdContains?: string;
  negRiskMarketIdContains?: string;
  negRiskRequestIdContains?: string;
  endDateIsoMin?: string;
  endDateIsoMax?: string;
  gameStartTimeMin?: string;
  gameStartTimeMax?: string;
  active?: boolean;
  closed?: boolean;
  archived?: boolean;
  isFiftyFiftyOutcome?: boolean;
  tags?: string[];
  questionContains?: string;
  marketSlugContains?: string;
}

export interface MarketChannelRecord {
  assetId: string;
  conditionId?: string;
  question?: string;
  outcome?: string;
  marketSlug?: string;
}

export interface DiscoveryRun {
  id: string;
  status: DiscoveryRunStatus;
  dedupeKey: string;
  requestedAt: string;
  startedAt?: string;
  completedAt?: string;
  source: DiscoverySource;
  marketCount: number;
  marketChannelCount: number;
  requestId: string;
}

export interface DiscoveryActiveRun {
  run: DiscoveryRun;
  pollUrl: string;
}

export interface DiscoveryActiveRunsResponse {
  runs: DiscoveryActiveRun[];
  total: number;
}

export interface DiscoveryChannelsPage {
  items: MarketChannelRecord[];
  page: {
    offset: number;
    limit: number;
    total: number;
    hasMore: boolean;
  };
}

export interface DiscoveryWsScan {
  wsUrl: string;
  connected: boolean;
  observedChannels: string[];
  messageCount: number;
  sampleEventCount: number;
  errors: unknown[];
}

export interface DiscoveryRunReadModel {
  run: DiscoveryRun;
  channels: DiscoveryChannelsPage;
  wsScan: DiscoveryWsScan | null;
}

export interface DiscoveryApiError {
  error: string;
  code: string;
  message: string;
  retryable: boolean;
  details?: Record<string, unknown> | null;
  requestId: string;
}

export interface StartDiscoveryRequest {
  clobApiUrl?: string;
  chainId: number;
  maxMarkets?: number;
  wsUrl?: string;
  wsConnectTimeoutMs?: number;
  wsChunkSize?: number;
  marketFetchTimeoutMs?: number;
  acceptingOrders?: boolean;
  enableOrderBook?: boolean;
  minimumOrderSizeMin?: number;
  minimumOrderSizeMax?: number;
  minimumTickSizeMin?: number;
  minimumTickSizeMax?: number;
  makerBaseFeeMin?: number;
  makerBaseFeeMax?: number;
  takerBaseFeeMin?: number;
  takerBaseFeeMax?: number;
  notificationsEnabled?: boolean;
  negRisk?: boolean;
  fpmm?: string;
  secondsDelayMin?: number;
  secondsDelayMax?: number;
  acceptingOrderTimestampMin?: number;
  acceptingOrderTimestampMax?: number;
  questionIdContains?: string;
  rewardsHasRates?: boolean;
  rewardsMinSizeMin?: number;
  rewardsMinSizeMax?: number;
  rewardsMaxSpreadMin?: number;
  rewardsMaxSpreadMax?: number;
  iconContains?: string;
  imageContains?: string;
  descriptionContains?: string;
  conditionIdContains?: string;
  negRiskMarketIdContains?: string;
  negRiskRequestIdContains?: string;
  endDateIsoMin?: string;
  endDateIsoMax?: string;
  gameStartTimeMin?: string;
  gameStartTimeMax?: string;
  active?: boolean;
  closed?: boolean;
  archived?: boolean;
  isFiftyFiftyOutcome?: boolean;
  tags?: string[];
  questionContains?: string;
  marketSlugContains?: string;
}

export interface StartDiscoveryEstimateRequest extends StartDiscoveryRequest {
  sampleLimit?: number;
}

export interface DiscoveryEstimateResult {
  requestId: string;
  sampleLimit: number;
  pagesScanned: number;
  stoppedByLimit: boolean;
  hasMore: boolean;
  source: {
    clobApiUrl: string;
    chainId: number;
    marketCount: number;
    marketChannelCount: number;
    sampleLimit: number;
    pagesScanned: number;
    stoppedByLimit: boolean;
    hasMore: boolean;
  };
  channels: MarketChannelRecord[];
}

export interface DiscoveryPollResultShell {
  kind: "shell";
  status: number;
  shell: DiscoveryRunShell;
}

export interface DiscoveryPollResultRun {
  kind: "run";
  status: number;
  run: DiscoveryRunReadModel;
}

export interface DiscoveryPollResultError {
  kind: "error";
  status: number;
  error: DiscoveryApiError;
}

export type DiscoveryPollResult = DiscoveryPollResultShell | DiscoveryPollResultRun | DiscoveryPollResultError;

export interface DiscoveryPersistedShell {
  runId: string;
  pollUrl: string;
  requestId: string;
  createdAt: string;
}

export interface DiscoveryHookState {
  phase: DiscoveryPhase;
  shell?: DiscoveryRunShell;
  run?: DiscoveryRunReadModel;
  offset: number;
  pollAttempt: number;
  error?: DiscoveryApiError;
}

export interface DiscoveryHookConfig {
  pageSize?: number;
  autoRestore?: boolean;
  storageKey?: string;
  pollIntervalMs?: number;
  pollIntervalMaxMs?: number;
  pollBackoffFactor?: number;
  maxPollAttempts?: number;
}
