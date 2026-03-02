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
  wsUrl?: string;
  wsConnectTimeoutMs: number;
  wsChunkSize: number;
  marketFetchTimeoutMs: number;
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
  wsUrl?: string;
  wsConnectTimeoutMs?: number;
  wsChunkSize?: number;
  marketFetchTimeoutMs?: number;
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
