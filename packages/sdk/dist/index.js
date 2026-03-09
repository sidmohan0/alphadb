function normalizeBaseUrl(value) {
    const trimmed = value?.trim();
    return trimmed ? trimmed.replace(/\/+$/, "") : null;
}
function sameTickers(left, right) {
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
    onStatus;
    onTicker;
    fetchImpl;
    baseUrl;
    userId;
    controller = null;
    reconnectTimer = null;
    reconnectDelayMs = 1_000;
    closed = false;
    tickers = [];
    constructor(baseUrl, userId, options, fetchImpl) {
        this.baseUrl = baseUrl;
        this.userId = userId;
        this.onStatus = options.onStatus;
        this.onTicker = options.onTicker;
        this.fetchImpl = fetchImpl;
    }
    getStatusReason() {
        return this.baseUrl ? null : "set ALPHADB_API_BASE_URL to enable backend streaming";
    }
    replaceMarkets(nextTickers) {
        const normalized = [...new Set(nextTickers.filter(Boolean))].sort();
        if (sameTickers(normalized, this.tickers)) {
            return;
        }
        this.tickers = normalized;
        this.restart();
    }
    close() {
        this.closed = true;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        this.controller?.abort();
        this.controller = null;
    }
    restart() {
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
    async connect(controller) {
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
        }
        catch (error) {
            if (controller.signal.aborted || this.closed) {
                return;
            }
            this.onStatus(error instanceof Error ? `backend stream reconnecting: ${error.message}` : "backend stream reconnecting");
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
    handleFrame(frame) {
        const lines = frame.split("\n");
        let event = "message";
        const dataLines = [];
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
            const payload = JSON.parse(dataLines.join("\n"));
            if (event === "status" && typeof payload.message === "string") {
                this.onStatus(payload.message);
                return;
            }
            if (event === "ticker") {
                this.onTicker(payload);
            }
        }
        catch {
            this.onStatus("backend stream parse error");
        }
    }
}
export class AlphaDBClient {
    baseUrlValue;
    userIdValue;
    userAgentValue;
    fetchImpl;
    constructor(options = {}) {
        this.baseUrlValue = normalizeBaseUrl(options.baseUrl);
        this.userIdValue = options.userId?.trim() || "local-user";
        this.userAgentValue = options.userAgent?.trim() || "alphadb-sdk";
        this.fetchImpl = options.fetchImpl ?? fetch;
    }
    hasBaseUrl() {
        return Boolean(this.baseUrlValue);
    }
    baseUrl() {
        return this.baseUrlValue;
    }
    userId() {
        return this.userIdValue;
    }
    createMarketStream(options) {
        return new AlphaDBMarketStream(this.baseUrlValue, this.userIdValue, options, this.fetchImpl);
    }
    async fetchUnifiedTrendingMarkets(limit) {
        const payload = await this.fetchJson(this.urlFor("/markets/unified/trending", { limit: String(limit) }));
        return {
            polymarket: payload.markets?.polymarket ?? [],
            kalshi: payload.markets?.kalshi ?? [],
        };
    }
    async fetchTrendingMarkets(provider, limit) {
        const payload = await this.fetchJson(this.urlFor("/markets/trending", { provider, limit: String(limit) }));
        return payload.markets ?? [];
    }
    async fetchSearchMarkets(provider, query, limit) {
        const payload = await this.fetchJson(this.urlFor("/markets/search", { provider, q: query, limit: String(limit) }));
        return payload.markets ?? [];
    }
    async fetchUnifiedSearchMarkets(query, limit) {
        const payload = await this.fetchJson(this.urlFor("/markets/unified/search", { q: query, limit: String(limit) }));
        return {
            polymarket: payload.markets?.polymarket ?? [],
            kalshi: payload.markets?.kalshi ?? [],
        };
    }
    async fetchMarketHistory(market, range) {
        const params = {
            provider: market.provider,
            marketId: market.id,
            range,
        };
        const firstOutcomeTokenId = market.outcomes[0]?.tokenId;
        if (firstOutcomeTokenId) {
            params.outcomeTokenId = firstOutcomeTokenId;
        }
        const payload = await this.fetchJson(this.urlFor("/markets/history", params));
        return payload.points ?? [];
    }
    async fetchPersistentState() {
        const payload = await this.fetchJson(this.urlFor("/markets/state"));
        return payload.state ?? { savedMarkets: [], recentMarkets: [] };
    }
    async saveMarket(market) {
        const payload = await this.fetchJson(this.urlFor("/markets/state/saved"), {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ market }),
        });
        return payload.state ?? { savedMarkets: [], recentMarkets: [] };
    }
    async removeSavedMarket(marketId) {
        const payload = await this.fetchJson(this.urlFor("/markets/state/saved", { marketId }), { method: "DELETE" });
        return payload.state ?? { savedMarkets: [], recentMarkets: [] };
    }
    async touchRecentMarket(market) {
        const payload = await this.fetchJson(this.urlFor("/markets/state/recent"), {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ market }),
        });
        return payload.state ?? { savedMarkets: [], recentMarkets: [] };
    }
    urlFor(path, params) {
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
    async fetchJson(url, init) {
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
        return response.json();
    }
    requireBaseUrl() {
        if (!this.baseUrlValue) {
            throw new Error("ALPHADB_API_BASE_URL is required for backend market access");
        }
        return this.baseUrlValue;
    }
}
