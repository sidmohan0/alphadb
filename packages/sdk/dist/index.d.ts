import type { AuthStatus, MarketStreamStatus, MarketStreamSubscription, MarketStreamUpdate, MarketSummary, PersistentState, PricePoint, ProviderId, RangeKey } from "@alphadb/market-core";
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
export declare class AlphaDBMarketStream {
    private readonly onStatus;
    private readonly onUpdate;
    private readonly fetchImpl;
    private readonly baseUrl;
    private readonly apiToken;
    private readonly userId;
    private controller;
    private reconnectTimer;
    private reconnectDelayMs;
    private closed;
    private subscriptions;
    constructor(baseUrl: string | null, apiToken: string | null, userId: string | null, options: BackendMarketStreamOptions, fetchImpl: typeof fetch);
    getStatusReason(): string | null;
    replaceSubscriptions(nextSubscriptions: MarketStreamSubscription[]): void;
    close(): void;
    private restart;
    private connect;
    private handleFrame;
    private requestHeaders;
}
export declare class AlphaDBClient {
    private readonly baseUrlValue;
    private readonly apiTokenValue;
    private readonly userIdValue;
    private readonly userAgentValue;
    private readonly fetchImpl;
    constructor(options?: AlphaDBClientOptions);
    hasBaseUrl(): boolean;
    baseUrl(): string | null;
    userId(): string | null;
    apiToken(): string | null;
    createMarketStream(options: BackendMarketStreamOptions): AlphaDBMarketStream;
    fetchAuthStatus(): Promise<AuthStatus>;
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
