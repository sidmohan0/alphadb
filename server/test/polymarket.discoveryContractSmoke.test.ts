import { afterEach, describe, expect, it, vi } from "vitest";
import request from "supertest";

import { createApp } from "../src/app";
import { mapRunNotFound } from "../src/polymarket/errors";
import {
  type DiscoveryRunReadModel,
  type DiscoveryRunSummary,
} from "../src/polymarket/types";
import * as discoveryRunService from "../src/polymarket/services/discoveryRunService";

describe("Discovery polling contract smoke suite (client-style)", () => {
  const app = createApp();

  const runId = "smoke-run-1";
  const shell: DiscoveryRunSummary = {
    runId,
    status: "queued",
    dedupeKey: JSON.stringify({ clobApiUrl: "https://clob.polymarket.com", chainId: 137 }),
    pollUrl: `/api/polymarket/market-channels/runs/${runId}`,
    requestId: "req-smoke",
  };

  const queuedRun: DiscoveryRunReadModel = {
    run: {
      id: runId,
      status: "queued",
      dedupeKey: shell.dedupeKey,
      requestedAt: "2026-01-01T00:00:00.000Z",
      source: {
        clobApiUrl: "https://clob.polymarket.com",
        chainId: 137,
        wsConnectTimeoutMs: 12_000,
        wsChunkSize: 500,
        marketFetchTimeoutMs: 15_000,
      },
      marketCount: 0,
      marketChannelCount: 0,
      requestId: "req-smoke",
    },
    channels: {
      items: [],
      page: {
        offset: 0,
        limit: 2,
        total: 0,
        hasMore: false,
      },
    },
    wsScan: null,
  };

  const completedRun: DiscoveryRunReadModel = {
    run: {
      id: runId,
      status: "succeeded",
      dedupeKey: shell.dedupeKey,
      requestedAt: "2026-01-01T00:00:00.000Z",
      source: {
        clobApiUrl: "https://clob.polymarket.com",
        chainId: 137,
        wsConnectTimeoutMs: 12_000,
        wsChunkSize: 500,
        marketFetchTimeoutMs: 15_000,
      },
      marketCount: 2,
      marketChannelCount: 2,
      requestId: "req-smoke",
    },
    channels: {
      items: [
        {
          assetId: "asset-0",
          question: "Q0",
        },
        {
          assetId: "asset-1",
          question: "Q1",
        },
      ],
      page: {
        offset: 0,
        limit: 2,
        total: 2,
        hasMore: false,
      },
    },
    wsScan: {
      wsUrl: "wss://stream.example/ws",
      connected: true,
      observedChannels: ["asset-0", "asset-1"],
      messageCount: 3,
      sampleEventCount: 1,
      errors: [],
    },
  };

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("supports create + poll contract with shell then terminal payload", async () => {
    vi.spyOn(discoveryRunService.discoveryRunService, "createOrAttachRun").mockResolvedValue(shell);

    const createResponse = await request(app)
      .post("/api/polymarket/market-channels/runs")
      .send({ chainId: 137 })
      .expect(202)
      .expect("Content-Type", /json/);

    expect(createResponse.body).toEqual({
      status: "queued",
      runId,
      pollUrl: `/api/polymarket/market-channels/runs/${runId}`,
      requestId: "req-smoke",
    });

    let pollCount = 0;
    vi.spyOn(discoveryRunService.discoveryRunService, "getRun").mockImplementation(async (_runId, _offset, limit) => {
      pollCount += 1;
      if (pollCount === 1) {
        return queuedRun;
      }

      const pagedCompleted: typeof completedRun = {
        ...completedRun,
        channels: {
          ...completedRun.channels,
          items: completedRun.channels.items.slice(0, limit),
          page: {
            ...completedRun.channels.page,
            limit,
            hasMore: limit < completedRun.channels.total,
          },
        },
      };

      return pagedCompleted;
    });

    const firstPoll = await request(app)
      .get(`/api/polymarket/market-channels/runs/${runId}?offset=0&limit=2`)
      .expect(200)
      .expect("Content-Type", /json/);

    expect(firstPoll.body).toMatchObject({
      run: {
        id: runId,
        status: "queued",
      },
      channels: {
        items: [],
        page: {
          offset: 0,
          limit: 2,
          total: 0,
          hasMore: false,
        },
      },
    });

    const secondPoll = await request(app)
      .get(`/api/polymarket/market-channels/runs/${runId}?offset=0&limit=2`)
      .expect(200)
      .expect("Content-Type", /json/);

    expect(secondPoll.body).toMatchObject({
      run: {
        id: runId,
        status: "succeeded",
        source: {
          chainId: 137,
        },
      },
      channels: {
        items: [
          {
            assetId: "asset-0",
          },
          {
            assetId: "asset-1",
          },
        ],
        page: {
          offset: 0,
          limit: 2,
          total: 2,
          hasMore: false,
        },
      },
    });
  });

  it("supports compatibility waitMs=0 contract while run is queued", async () => {
    vi.spyOn(discoveryRunService.discoveryRunService, "waitForRunIfAllowed").mockResolvedValue({
      status: "queued",
      runId,
      pollUrl: `/api/polymarket/market-channels/runs/${runId}`,
      requestId: "req-smoke",
    });

    const response = await request(app).get(`/api/polymarket/market-channels?chainId=137&waitMs=0`).expect(202);

    expect(response.body).toMatchObject({
      status: "queued",
      runId,
      requestId: "req-smoke",
      pollUrl: `/api/polymarket/market-channels/runs/${runId}`,
    });
  });

  it("returns contract-shaped 404 for unknown runId", async () => {
    vi.spyOn(discoveryRunService.discoveryRunService, "getRun").mockRejectedValue(mapRunNotFound("missing"));

    const response = await request(app)
      .get(`/api/polymarket/market-channels/runs/does-not-exist`)
      .expect(404)
      .expect("Content-Type", /json/);

    expect(response.body).toMatchObject({
      error: "Failed to discover market channels",
      code: "run_not_found",
      requestId: expect.any(String),
      retryable: false,
    });
  });
});
