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
export declare class AlphaDBMarketStream {
    private readonly onStatus;
    private readonly onTicker;
    private readonly fetchImpl;
    private readonly baseUrl;
    private readonly userId;
    private controller;
    private reconnectTimer;
    private reconnectDelayMs;
    private closed;
    private tickers;
    constructor(baseUrl: string | null, userId: string, options: BackendMarketStreamOptions, fetchImpl: typeof fetch);
    getStatusReason(): string | null;
    replaceMarkets(nextTickers: string[]): void;
    close(): void;
    private restart;
    private connect;
    private handleFrame;
}
export declare class AlphaDBClient {
    private readonly baseUrlValue;
    private readonly userIdValue;
    private readonly userAgentValue;
    private readonly fetchImpl;
    constructor(options?: AlphaDBClientOptions);
    hasBaseUrl(): boolean;
    baseUrl(): string | null;
    userId(): string;
    createMarketStream(options: BackendMarketStreamOptions): AlphaDBMarketStream;
    fetchUnifiedTrendingMarkets(limit: number): Promise<Record<ProviderId, MarketSummary[]>>;
    fetchTrendingMarkets(provider: ProviderId, limit: number): Promise<MarketSummary[]>;
    fetchSearchMarkets(provider: ProviderId, query: string, limit: number): Promise<MarketSummary[]>;
    fetchUnifiedSearchMarkets(query: string, limit: number): Promise<Record<ProviderId, MarketSummary[]>>;
    fetchMarketHistory(market: MarketSummary, range: RangeKey): Promise<PricePoint[]>;
    fetchPersistentState(): Promise<PersistentState>;
    saveMarket(market: MarketSummary): Promise<PersistentState>;
    removeSavedMarket(marketId: string): Promise<PersistentState>;
    touchRecentMarket(market: MarketSummary): Promise<PersistentState>;
    private urlFor;
    private fetchJson;
    private requireBaseUrl;
}
