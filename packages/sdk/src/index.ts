import type {
  AuthStatus,
  MarketStreamStatus,
  MarketStreamSubscription,
  MarketStreamUpdate,
  MarketSummary,
  PersistentState,
  PricePoint,
  ProviderId,
  RangeKey,
} from "@alphadb/market-core";

export interface AlphaDBClientOptions {
  baseUrl?: string | null;
  userAgent?: string;
  apiToken?: string;
  userId?: string;
  fetchImpl?: typeof fetch;
}

export interface BackendMarketStreamOptions {
  onStatus: (status: MarketStreamStatus) => void;
  onUpdate: (payload: MarketStreamUpdate) => void;
}

function normalizeBaseUrl(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed.replace(/\/+$/, "") : null;
}

function resolveFetchImpl(fetchImpl?: typeof fetch): typeof fetch {
  if (fetchImpl) {
    return fetchImpl;
  }

  return globalThis.fetch.bind(globalThis);
}

function canSetUserAgentHeader(): boolean {
  return typeof window === "undefined";
}

function sameTickers(left: string[], right: string[]): boolean {
  if (left.length !== right.length) {
    return false;
  }

  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) {
      return false;
    }
  }

  return true;
}

export class AlphaDBMarketStream {
  private readonly onStatus: (status: MarketStreamStatus) => void;
  private readonly onUpdate: (payload: MarketStreamUpdate) => void;
  private readonly fetchImpl: typeof fetch;
  private readonly baseUrl: string | null;
  private readonly apiToken: string | null;
  private readonly userId: string | null;
  private controller: AbortController | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelayMs = 1_000;
  private closed = false;
  private subscriptions: MarketStreamSubscription[] = [];

  constructor(
    baseUrl: string | null,
    apiToken: string | null,
    userId: string | null,
    options: BackendMarketStreamOptions,
    fetchImpl: typeof fetch,
  ) {
    this.baseUrl = baseUrl;
    this.apiToken = apiToken;
    this.userId = userId;
    this.onStatus = options.onStatus;
    this.onUpdate = options.onUpdate;
    this.fetchImpl = fetchImpl;
  }

  getStatusReason(): string | null {
    return this.baseUrl ? null : "set ALPHADB_API_BASE_URL to enable backend streaming";
  }

  replaceSubscriptions(nextSubscriptions: MarketStreamSubscription[]): void {
    const normalized = [...nextSubscriptions]
      .map((entry) => ({
        provider: entry.provider,
        marketId: entry.marketId,
        symbol: entry.symbol,
        outcomeTokenIds: [...new Set(entry.outcomeTokenIds?.filter(Boolean) ?? [])].sort(),
      }))
      .sort((left, right) =>
        `${left.provider}:${left.marketId}:${left.symbol}`.localeCompare(`${right.provider}:${right.marketId}:${right.symbol}`),
      );

    const serialized = normalized.map((entry) => JSON.stringify(entry));
    const current = this.subscriptions.map((entry) => JSON.stringify(entry));
    if (sameTickers(serialized, current)) {
      return;
    }

    this.subscriptions = normalized;
    this.restart();
  }

  close(): void {
    this.closed = true;

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    this.controller?.abort();
    this.controller = null;
  }

  private restart(): void {
    if (this.closed) {
      return;
    }

    if (!this.baseUrl) {
      this.onStatus({ provider: "polymarket", message: "backend stream unavailable" });
      return;
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    this.controller?.abort();
    this.controller = null;

    if (this.subscriptions.length === 0) {
      this.onStatus({ provider: "polymarket", message: "backend stream idle" });
      return;
    }

    const controller = new AbortController();
    this.controller = controller;
    void this.connect(controller);
  }

  private async connect(controller: AbortController): Promise<void> {
    if (!this.baseUrl) {
      return;
    }

    try {
      const url = new URL(`${this.baseUrl}/markets/stream`);
      url.searchParams.set("subscriptions", JSON.stringify(this.subscriptions));

      const response = await this.fetchImpl(url.toString(), {
        headers: this.requestHeaders({
          Accept: "text/event-stream",
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }

      this.onStatus({ provider: "polymarket", message: `backend stream connected (${this.subscriptions.length} subscriptions)` });
      this.reconnectDelayMs = 1_000;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!controller.signal.aborted) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          this.handleFrame(frame);
        }
      }
    } catch (error) {
      if (controller.signal.aborted || this.closed) {
        return;
      }

      this.onStatus({
        provider: "polymarket",
        message: error instanceof Error ? `backend stream reconnecting: ${error.message}` : "backend stream reconnecting",
      });
    }

    if (this.closed || controller.signal.aborted) {
      return;
    }

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.restart();
    }, this.reconnectDelayMs);
    this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 15_000);
  }

  private handleFrame(frame: string): void {
    const lines = frame.split("\n");
    let event = "message";
    const dataLines: string[] = [];

    for (const line of lines) {
      if (!line || line.startsWith(":")) {
        continue;
      }

      if (line.startsWith("event:")) {
        event = line.slice("event:".length).trim();
        continue;
      }

      if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trim());
      }
    }

    if (dataLines.length === 0) {
      return;
    }

    try {
      const payload = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
      if (
        event === "status" &&
        (payload.provider === "polymarket" || payload.provider === "kalshi") &&
        typeof payload.message === "string"
      ) {
        this.onStatus(payload as unknown as MarketStreamStatus);
        return;
      }

      if (
        event === "market_update" &&
        (payload.provider === "polymarket" || payload.provider === "kalshi") &&
        typeof payload.marketId === "string" &&
        typeof payload.symbol === "string" &&
        typeof payload.receivedAt === "number"
      ) {
        this.onUpdate(payload as unknown as MarketStreamUpdate);
      }
    } catch {
      this.onStatus({ provider: "polymarket", message: "backend stream parse error" });
    }
  }

  private requestHeaders(headers: Record<string, string>): Record<string, string> {
    return {
      ...headers,
      ...(this.apiToken ? { Authorization: `Bearer ${this.apiToken}` } : {}),
      ...(this.userId ? { "X-AlphaDB-User-Id": this.userId } : {}),
    };
  }
}

export class AlphaDBClient {
  private readonly baseUrlValue: string | null;
  private readonly apiTokenValue: string | null;
  private readonly userIdValue: string | null;
  private readonly userAgentValue: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AlphaDBClientOptions = {}) {
    this.baseUrlValue = normalizeBaseUrl(options.baseUrl);
    this.apiTokenValue = options.apiToken?.trim() || null;
    this.userIdValue = options.userId?.trim() || null;
    this.userAgentValue = options.userAgent?.trim() || "alphadb-sdk";
    this.fetchImpl = resolveFetchImpl(options.fetchImpl);
  }

  hasBaseUrl(): boolean {
    return Boolean(this.baseUrlValue);
  }

  baseUrl(): string | null {
    return this.baseUrlValue;
  }

  userId(): string | null {
    return this.userIdValue;
  }

  apiToken(): string | null {
    return this.apiTokenValue;
  }

  createMarketStream(options: BackendMarketStreamOptions): AlphaDBMarketStream {
    return new AlphaDBMarketStream(
      this.baseUrlValue,
      this.apiTokenValue,
      this.userIdValue,
      options,
      this.fetchImpl,
    );
  }

  async fetchAuthStatus(): Promise<AuthStatus> {
    return this.fetchJson<AuthStatus>(this.urlFor("/auth/me"));
  }

  async fetchUnifiedTrendingMarkets(limit: number): Promise<Record<ProviderId, MarketSummary[]>> {
    const payload = await this.fetchJson<{ markets?: Partial<Record<ProviderId, MarketSummary[]>> }>(
      this.urlFor("/markets/unified/trending", { limit: String(limit) }),
    );

    return {
      polymarket: payload.markets?.polymarket ?? [],
      kalshi: payload.markets?.kalshi ?? [],
    };
  }

  async fetchTrendingMarkets(provider: ProviderId, limit: number): Promise<MarketSummary[]> {
    const payload = await this.fetchJson<{ markets?: MarketSummary[] }>(
      this.urlFor("/markets/trending", { provider, limit: String(limit) }),
    );

    return payload.markets ?? [];
  }

  async fetchSearchMarkets(provider: ProviderId, query: string, limit: number): Promise<MarketSummary[]> {
    const payload = await this.fetchJson<{ markets?: MarketSummary[] }>(
      this.urlFor("/markets/search", { provider, q: query, limit: String(limit) }),
    );

    return payload.markets ?? [];
  }

  async fetchUnifiedSearchMarkets(query: string, limit: number): Promise<Record<ProviderId, MarketSummary[]>> {
    const payload = await this.fetchJson<{ markets?: Partial<Record<ProviderId, MarketSummary[]>> }>(
      this.urlFor("/markets/unified/search", { q: query, limit: String(limit) }),
    );

    return {
      polymarket: payload.markets?.polymarket ?? [],
      kalshi: payload.markets?.kalshi ?? [],
    };
  }

  async fetchMarketHistory(market: MarketSummary, range: RangeKey): Promise<PricePoint[]> {
    const params: Record<string, string> = {
      provider: market.provider,
      marketId: market.id,
      range,
    };

    const firstOutcomeTokenId = market.outcomes[0]?.tokenId;
    if (firstOutcomeTokenId) {
      params.outcomeTokenId = firstOutcomeTokenId;
    }

    const payload = await this.fetchJson<{ points?: PricePoint[] }>(this.urlFor("/markets/history", params));
    return payload.points ?? [];
  }

  async fetchPersistentState(): Promise<PersistentState> {
    const payload = await this.fetchJson<{ state?: PersistentState }>(this.urlFor("/markets/state"));
    return payload.state ?? { savedMarkets: [], recentMarkets: [] };
  }

  async saveMarket(market: MarketSummary): Promise<PersistentState> {
    const payload = await this.fetchJson<{ state?: PersistentState }>(this.urlFor("/markets/state/saved"), {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ market }),
    });

    return payload.state ?? { savedMarkets: [], recentMarkets: [] };
  }

  async removeSavedMarket(marketId: string): Promise<PersistentState> {
    const payload = await this.fetchJson<{ state?: PersistentState }>(
      this.urlFor("/markets/state/saved", { marketId }),
      { method: "DELETE" },
    );

    return payload.state ?? { savedMarkets: [], recentMarkets: [] };
  }

  async touchRecentMarket(market: MarketSummary): Promise<PersistentState> {
    const payload = await this.fetchJson<{ state?: PersistentState }>(this.urlFor("/markets/state/recent"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ market }),
    });

    return payload.state ?? { savedMarkets: [], recentMarkets: [] };
  }

  private urlFor(path: string, params?: Record<string, string>): string {
    const baseUrl = this.requireBaseUrl();
    const url = new URL(`${baseUrl}${path}`);

    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value) {
          url.searchParams.set(key, value);
        }
      }
    }

    return url.toString();
  }

  private async fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchImpl(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(canSetUserAgentHeader() ? { "User-Agent": this.userAgentValue } : {}),
        "X-AlphaDB-Client": this.userAgentValue,
        ...(this.apiTokenValue ? { Authorization: `Bearer ${this.apiTokenValue}` } : {}),
        ...(this.userIdValue ? { "X-AlphaDB-User-Id": this.userIdValue } : {}),
        ...(init?.headers ?? {}),
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status} for ${url}`);
    }

    return response.json() as Promise<T>;
  }

  private requireBaseUrl(): string {
    if (!this.baseUrlValue) {
      throw new Error("ALPHADB_API_BASE_URL is required for backend market access");
    }

    return this.baseUrlValue;
  }
}
