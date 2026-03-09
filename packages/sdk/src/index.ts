import type { MarketSummary, PersistentState, PricePoint, ProviderId, RangeKey } from "@alphadb/market-core";

export interface AlphaDBClientOptions {
  baseUrl?: string | null;
  userAgent?: string;
  userId?: string;
  fetchImpl?: typeof fetch;
}

export interface BackendMarketStreamOptions {
  onStatus: (message: string) => void;
  onTicker: (payload: Record<string, unknown>) => void;
}

function normalizeBaseUrl(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed.replace(/\/+$/, "") : null;
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
  private readonly onStatus: (message: string) => void;
  private readonly onTicker: (payload: Record<string, unknown>) => void;
  private readonly fetchImpl: typeof fetch;
  private readonly baseUrl: string | null;
  private readonly userId: string;
  private controller: AbortController | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelayMs = 1_000;
  private closed = false;
  private tickers: string[] = [];

  constructor(
    baseUrl: string | null,
    userId: string,
    options: BackendMarketStreamOptions,
    fetchImpl: typeof fetch,
  ) {
    this.baseUrl = baseUrl;
    this.userId = userId;
    this.onStatus = options.onStatus;
    this.onTicker = options.onTicker;
    this.fetchImpl = fetchImpl;
  }

  getStatusReason(): string | null {
    return this.baseUrl ? null : "set ALPHADB_API_BASE_URL to enable backend streaming";
  }

  replaceMarkets(nextTickers: string[]): void {
    const normalized = [...new Set(nextTickers.filter(Boolean))].sort();
    if (sameTickers(normalized, this.tickers)) {
      return;
    }

    this.tickers = normalized;
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
      this.onStatus("backend stream unavailable");
      return;
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    this.controller?.abort();
    this.controller = null;

    if (this.tickers.length === 0) {
      this.onStatus("backend stream idle");
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
      url.searchParams.set("tickers", this.tickers.join(","));

      const response = await this.fetchImpl(url.toString(), {
        headers: {
          Accept: "text/event-stream",
          "X-AlphaDB-User-Id": this.userId,
        },
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }

      this.onStatus(`backend stream connected (${this.tickers.length} markets)`);
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

      this.onStatus(
        error instanceof Error ? `backend stream reconnecting: ${error.message}` : "backend stream reconnecting",
      );
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
      if (event === "status" && typeof payload.message === "string") {
        this.onStatus(payload.message);
        return;
      }

      if (event === "ticker") {
        this.onTicker(payload);
      }
    } catch {
      this.onStatus("backend stream parse error");
    }
  }
}

export class AlphaDBClient {
  private readonly baseUrlValue: string | null;
  private readonly userIdValue: string;
  private readonly userAgentValue: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AlphaDBClientOptions = {}) {
    this.baseUrlValue = normalizeBaseUrl(options.baseUrl);
    this.userIdValue = options.userId?.trim() || "local-user";
    this.userAgentValue = options.userAgent?.trim() || "alphadb-sdk";
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  hasBaseUrl(): boolean {
    return Boolean(this.baseUrlValue);
  }

  baseUrl(): string | null {
    return this.baseUrlValue;
  }

  userId(): string {
    return this.userIdValue;
  }

  createMarketStream(options: BackendMarketStreamOptions): AlphaDBMarketStream {
    return new AlphaDBMarketStream(this.baseUrlValue, this.userIdValue, options, this.fetchImpl);
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
        "User-Agent": this.userAgentValue,
        "X-AlphaDB-User-Id": this.userIdValue,
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
