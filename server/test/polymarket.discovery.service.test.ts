import { afterEach, describe, expect, it, vi } from "vitest";

import { ClobClient } from "@polymarket/clob-client";

import { discoverMarketChannels } from "../src/polymarket/services/marketChannelDiscoveryService";
import {
  DEFAULT_CLOB_API_URL,
  DEFAULT_CHAIN_ID,
  DEFAULT_MARKET_FETCH_TIMEOUT_MS,
  DEFAULT_WS_CHUNK_SIZE,
  DEFAULT_WS_CONNECT_TIMEOUT_MS,
} from "../src/polymarket/types";

function makeMarketResponse(nextCursor: string | null, data: unknown[] = []): { data: unknown[]; next_cursor: string | null } {
  return { data, next_cursor: nextCursor };
}

describe("Polymarket market discovery service", () => {
  let getMarketsSpy: ReturnType<typeof vi.spyOn>;

  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.MARKET_DISCOVERY_CONCURRENCY_LIMIT;
  });

  it("returns an explicit empty-state payload when no markets are returned", async () => {
    getMarketsSpy = vi.spyOn(ClobClient.prototype, "getMarkets" as never).mockResolvedValueOnce(
      makeMarketResponse(null, [] as unknown[])
    );

    const result = await discoverMarketChannels({
      clobApiUrl: DEFAULT_CLOB_API_URL,
      chainId: DEFAULT_CHAIN_ID,
      wsUrl: undefined,
      wsConnectTimeoutMs: DEFAULT_WS_CONNECT_TIMEOUT_MS,
      wsChunkSize: DEFAULT_WS_CHUNK_SIZE,
      marketFetchTimeoutMs: DEFAULT_MARKET_FETCH_TIMEOUT_MS,
    });

    expect(getMarketsSpy).toHaveBeenCalledTimes(1);
    expect(result).toEqual({
      source: {
        clobApiUrl: DEFAULT_CLOB_API_URL,
        chainId: DEFAULT_CHAIN_ID,
        marketCount: 0,
        marketChannelCount: 0,
      },
      channels: [],
      wsScan: null,
    });
  });

  it("coalesces identical concurrent discovery requests into one upstream fetch", async () => {
    const assetId = "0x" + "1".repeat(64);
    const payload = makeMarketResponse(null, [
      {
        market_slug: "market-empty",
        condition_id: "cond-1",
        question: "Will it happen?",
        asset_id: assetId,
      },
    ]);

    getMarketsSpy = vi.spyOn(ClobClient.prototype, "getMarkets" as never).mockResolvedValueOnce(payload as never);

    const cfg = {
      clobApiUrl: DEFAULT_CLOB_API_URL,
      chainId: DEFAULT_CHAIN_ID,
      wsUrl: undefined,
      wsConnectTimeoutMs: DEFAULT_WS_CONNECT_TIMEOUT_MS,
      wsChunkSize: DEFAULT_WS_CHUNK_SIZE,
      marketFetchTimeoutMs: DEFAULT_MARKET_FETCH_TIMEOUT_MS,
    };

    const [first, second] = await Promise.all([discoverMarketChannels(cfg), discoverMarketChannels(cfg)]);

    expect(getMarketsSpy).toHaveBeenCalledTimes(1);
    expect(first.channels).toEqual([
      { assetId, conditionId: "cond-1", question: "Will it happen?", marketSlug: "market-empty" },
    ]);
    expect(second.channels).toEqual(first.channels);
    expect(first.source.marketCount).toBe(1);
  });

  it("rejects unique concurrent requests once the in-flight concurrency limit is hit", async () => {
    process.env.MARKET_DISCOVERY_CONCURRENCY_LIMIT = "1";

    const payload = makeMarketResponse(null, []);
    let release: (value: { data: unknown[]; next_cursor: string | null }) => void;
    const block = new Promise<{ data: unknown[]; next_cursor: string | null }>((resolve) => {
      release = resolve;
    });

    getMarketsSpy = vi.spyOn(ClobClient.prototype, "getMarkets" as never).mockReturnValue(block as never);

    const fastConfig = {
      clobApiUrl: DEFAULT_CLOB_API_URL,
      chainId: 137,
      wsUrl: undefined,
      wsConnectTimeoutMs: DEFAULT_WS_CONNECT_TIMEOUT_MS,
      wsChunkSize: DEFAULT_WS_CHUNK_SIZE,
      marketFetchTimeoutMs: DEFAULT_MARKET_FETCH_TIMEOUT_MS,
    };

    const queuedConfig = {
      clobApiUrl: DEFAULT_CLOB_API_URL,
      chainId: 138,
      wsUrl: undefined,
      wsConnectTimeoutMs: DEFAULT_WS_CONNECT_TIMEOUT_MS,
      wsChunkSize: DEFAULT_WS_CHUNK_SIZE,
      marketFetchTimeoutMs: DEFAULT_MARKET_FETCH_TIMEOUT_MS,
    };

    const running = discoverMarketChannels(fastConfig);
    const throttled = discoverMarketChannels(queuedConfig);

    await expect(throttled).rejects.toMatchObject({
      code: "discovery_concurrency_limit",
      status: 429,
      details: {
        component: "service",
        limit: 1,
      },
    });

    release!(payload);

    const result = await running;
    expect(result).toEqual({
      source: {
        clobApiUrl: DEFAULT_CLOB_API_URL,
        chainId: 137,
        marketCount: 0,
        marketChannelCount: 0,
      },
      channels: [],
      wsScan: null,
    });
  });
});
