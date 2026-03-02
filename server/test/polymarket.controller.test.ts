import { afterEach, describe, expect, it, vi } from "vitest";
import request from "supertest";

import { createApp } from "../src/app";
import type { MarketChannelRunResult } from "../src/polymarket/types";
import * as discoveryService from "../src/polymarket/services/marketChannelDiscoveryService";
import {
  DEFAULT_CLOB_API_URL,
  DEFAULT_CHAIN_ID,
  DEFAULT_MARKET_FETCH_TIMEOUT_MS,
  DEFAULT_WS_CHUNK_SIZE,
  DEFAULT_WS_CONNECT_TIMEOUT_MS,
} from "../src/polymarket/types";

const mockResult: MarketChannelRunResult = {
  source: {
    clobApiUrl: "https://clob.polymarket.com",
    chainId: 137,
    marketCount: 0,
    marketChannelCount: 0,
  },
  channels: [],
  wsScan: null,
};

describe("Polymarket controller", () => {
  const app = createApp();

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls discovery service and returns an empty-state payload", async () => {
    const spy = vi.spyOn(discoveryService, "discoverMarketChannels").mockResolvedValue(mockResult);

    const response = await request(app).get("/api/polymarket/market-channels").expect(200).expect("Content-Type", /json/);

    expect(response.body).toEqual({
      source: {
        clobApiUrl: "https://clob.polymarket.com",
        chainId: 137,
        marketCount: 0,
        marketChannelCount: 0,
      },
      channels: [],
      wsScan: null,
    });

    expect(spy).toHaveBeenCalledWith({
      clobApiUrl: DEFAULT_CLOB_API_URL,
      chainId: DEFAULT_CHAIN_ID,
      wsUrl: undefined,
      wsConnectTimeoutMs: DEFAULT_WS_CONNECT_TIMEOUT_MS,
      wsChunkSize: DEFAULT_WS_CHUNK_SIZE,
      marketFetchTimeoutMs: DEFAULT_MARKET_FETCH_TIMEOUT_MS,
    });
  });

  it("passes websocket query params to the service", async () => {
    const spy = vi
      .spyOn(discoveryService, "discoverMarketChannels")
      .mockResolvedValue(mockResult);

    await request(app)
      .get(
        "/api/polymarket/market-channels?wsUrl=wss://example.com/ws&wsConnectTimeoutMs=15000&wsChunkSize=42&marketFetchTimeoutMs=17000"
      )
      .expect(200);

    expect(spy).toHaveBeenCalledWith({
      clobApiUrl: DEFAULT_CLOB_API_URL,
      chainId: DEFAULT_CHAIN_ID,
      wsUrl: "wss://example.com/ws",
      wsConnectTimeoutMs: 15000,
      wsChunkSize: 42,
      marketFetchTimeoutMs: 17000,
    });
  });

  it("returns 400 for invalid integer input", async () => {
    const response = await request(app)
      .get("/api/polymarket/market-channels?chainId=abc")
      .expect(400)
      .expect("Content-Type", /json/);

    expect(response.body).toMatchObject({
      error: "Failed to discover market channels",
      code: "invalid_input",
      retryable: false,
      details: {
        component: "controller",
        field: "chainId",
      },
    });
  });

  it("returns a richer response on service failure", async () => {
    vi.spyOn(discoveryService, "discoverMarketChannels").mockRejectedValue(new Error("upstream failure"));

    const response = await request(app)
      .get("/api/polymarket/market-channels")
      .expect(500)
      .expect("Content-Type", /json/);

    expect(response.body).toMatchObject({
      error: "Failed to discover market channels",
      code: "unexpected_error",
      retryable: false,
      details: {
        component: "clob",
      },
      requestId: expect.any(String),
    });
  });
});
