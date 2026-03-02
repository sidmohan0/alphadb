import { afterEach, describe, expect, it, vi } from "vitest";
import request from "supertest";

import { createApp } from "../src/app";
import type { MarketChannelRunResult } from "../src/polymarket/types";
import * as discoveryService from "../src/polymarket/services/marketChannelDiscoveryService";
import {
  DEFAULT_CLOB_API_URL,
  DEFAULT_CHAIN_ID,
  DEFAULT_WS_CHUNK_SIZE,
  DEFAULT_WS_CONNECT_TIMEOUT_MS,
} from "../src/polymarket/types";

const mockResult: MarketChannelRunResult = {
  source: {
    clobApiUrl: "https://clob.polymarket.com",
    chainId: 137,
    marketCount: 1,
    marketChannelCount: 2,
  },
  channels: [
    {
      assetId: "0x111111111111111111111111111111111111111111111111111111111111111111",
      question: "Will BTC be > 100k?",
    },
    {
      assetId: "0x222222222222222222222222222222222222222222222222222222222222222222",
      question: "Will BTC be < 100k?",
    },
  ],
  wsScan: null,
};

describe("Polymarket controller", () => {
  const app = createApp();

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls discovery service and returns channel result", async () => {
    const spy = vi
      .spyOn(discoveryService, "discoverMarketChannels")
      .mockResolvedValue(mockResult);

    const response = await request(app)
      .get("/api/polymarket/market-channels?chainId=137&clobApiUrl=https://clob.polymarket.com")
      .expect(200)
      .expect("Content-Type", /json/);

    expect(response.body).toMatchObject({
      source: {
        clobApiUrl: "https://clob.polymarket.com",
        chainId: 137,
      },
      channels: expect.arrayContaining([expect.objectContaining({ assetId: mockResult.channels[0].assetId })]),
    });

    expect(spy).toHaveBeenCalledOnce();
    expect(spy).toHaveBeenCalledWith({
      clobApiUrl: "https://clob.polymarket.com",
      chainId: 137,
      wsUrl: undefined,
      wsConnectTimeoutMs: DEFAULT_WS_CONNECT_TIMEOUT_MS,
      wsChunkSize: DEFAULT_WS_CHUNK_SIZE,
    });
  });

  it("passes websocket-related query params to the service", async () => {
    const spy = vi
      .spyOn(discoveryService, "discoverMarketChannels")
      .mockResolvedValue(mockResult);

    await request(app)
      .get(
        "/api/polymarket/market-channels?wsUrl=wss://example.com/ws&wsConnectTimeoutMs=15000&wsChunkSize=42"
      )
      .expect(200);

    expect(spy).toHaveBeenCalledWith({
      clobApiUrl: DEFAULT_CLOB_API_URL,
      chainId: DEFAULT_CHAIN_ID,
      wsUrl: "wss://example.com/ws",
      wsConnectTimeoutMs: 15000,
      wsChunkSize: 42,
    });
  });

  it("returns an error response when discovery fails", async () => {
    vi.spyOn(discoveryService, "discoverMarketChannels").mockRejectedValue(new Error("upstream failure"));

    const response = await request(app)
      .get("/api/polymarket/market-channels")
      .expect(502)
      .expect("Content-Type", /json/);

    expect(response.body).toMatchObject({
      error: "Failed to discover market channels",
      details: "upstream failure",
    });
  });
});
