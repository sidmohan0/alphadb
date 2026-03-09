import { afterEach, describe, expect, it, vi } from "vitest";
import request from "supertest";

import { createApp } from "../src/app";
import { MarketSummary, PricePoint } from "../src/markets/types";
import { marketDataService } from "../src/markets/services/marketDataService";
import { clearMarketCache } from "../src/markets/services/marketCache";

describe("Markets controller", () => {
  const app = createApp();

  const market: MarketSummary = {
    id: "polymarket:123",
    provider: "polymarket",
    symbol: "fed-march",
    question: "Will the Fed hike in March?",
    conditionId: "cond-1",
    slug: "fed-march",
    endDate: "2026-03-17T00:00:00.000Z",
    liquidity: 1000,
    volume24hr: 5000,
    volumeTotal: 25000,
    bestBid: 0.44,
    bestAsk: 0.46,
    lastTradePrice: 0.45,
    oneDayPriceChange: 1.2,
    eventTitle: "Fed",
    seriesTitle: "Rates",
    image: null,
    outcomes: [{ name: "Yes", tokenId: "token-1", price: 0.45 }],
  };

  const points: PricePoint[] = [
    { timestamp: 1000, price: 0.4 },
    { timestamp: 2000, price: 0.45 },
  ];

  afterEach(() => {
    vi.restoreAllMocks();
    clearMarketCache();
  });

  it("returns provider trending markets", async () => {
    vi.spyOn(marketDataService, "getTrendingMarkets").mockResolvedValue([market]);

    const response = await request(app)
      .get("/api/markets/trending?provider=polymarket&limit=2")
      .expect(200)
      .expect("Content-Type", /json/);

    expect(response.body).toMatchObject({
      provider: "polymarket",
      markets: [market],
    });
  });

  it("returns search results", async () => {
    vi.spyOn(marketDataService, "searchMarkets").mockResolvedValue([market]);

    const response = await request(app)
      .get("/api/markets/search?provider=polymarket&q=fed&limit=5")
      .expect(200);

    expect(response.body).toMatchObject({
      provider: "polymarket",
      query: "fed",
      markets: [market],
    });
  });

  it("returns unified trending markets", async () => {
    vi.spyOn(marketDataService, "getUnifiedTrendingMarkets").mockResolvedValue({
      polymarket: [market],
      kalshi: [{ ...market, id: "kalshi:abc", provider: "kalshi", symbol: "KXABC" }],
    });

    const response = await request(app)
      .get("/api/markets/unified/trending?limit=5")
      .expect(200);

    expect(response.body).toMatchObject({
      markets: {
        polymarket: [market],
        kalshi: [{ id: "kalshi:abc", provider: "kalshi" }],
      },
    });
  });

  it("returns market history", async () => {
    vi.spyOn(marketDataService, "getMarketHistory").mockResolvedValue(points);

    const response = await request(app)
      .get("/api/markets/history?provider=polymarket&marketId=polymarket:123&outcomeTokenId=token-1&range=24h")
      .expect(200);

    expect(response.body).toMatchObject({
      provider: "polymarket",
      marketId: "polymarket:123",
      outcomeTokenId: "token-1",
      range: "24h",
      points,
    });
  });

  it("returns 400 for invalid provider", async () => {
    const response = await request(app)
      .get("/api/markets/trending?provider=unknown")
      .expect(400);

    expect(response.body).toMatchObject({
      error: "Failed to load markets",
      code: "invalid_input",
      details: {
        component: "controller",
        field: "provider",
      },
    });
  });

  it("returns 400 for missing search query", async () => {
    const response = await request(app)
      .get("/api/markets/search?provider=kalshi")
      .expect(400);

    expect(response.body).toMatchObject({
      error: "Failed to load markets",
      code: "invalid_input",
      details: {
        component: "controller",
        field: "q",
      },
    });
  });
});
