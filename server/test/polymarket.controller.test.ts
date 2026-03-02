import { afterEach, describe, expect, it, vi } from "vitest";
import request from "supertest";

import { createApp } from "../src/app";
import {
  type DiscoveryRunReadModel,
  type DiscoveryRunSummary,
  type MarketChannelRunResult,
} from "../src/polymarket/types";
import * as discoveryRunService from "../src/polymarket/services/discoveryRunService";

describe("Polymarket discovery controller", () => {
  const app = createApp();

  const shell: DiscoveryRunSummary = {
    runId: "run-1",
    status: "queued",
    dedupeKey: '{"clobApiUrl":"https://clob.polymarket.com","chainId":137}',
    pollUrl: "/api/polymarket/market-channels/runs/run-1",
    requestId: "req-123",
  };

  const runReadModel: DiscoveryRunReadModel = {
    run: {
      id: "run-1",
      status: "succeeded",
      dedupeKey: shell.dedupeKey,
      requestedAt: "2026-01-01T00:00:00.000Z",
      source: {
        clobApiUrl: "https://clob.polymarket.com",
        chainId: 137,
        wsConnectTimeoutMs: 12000,
        wsChunkSize: 500,
        marketFetchTimeoutMs: 15000,
      },
      marketCount: 0,
      marketChannelCount: 0,
      requestId: "req-123",
    },
    channels: {
      items: [],
      page: {
        offset: 0,
        limit: 200,
        total: 0,
        hasMore: false,
      },
    },
    wsScan: null,
  };

  const runResult: MarketChannelRunResult = {
    source: {
      clobApiUrl: "https://clob.polymarket.com",
      chainId: 137,
      marketCount: 0,
      marketChannelCount: 0,
    },
    channels: [],
    wsScan: null,
  };

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a discovery run via POST /market-channels/runs", async () => {
    vi.spyOn(discoveryRunService.discoveryRunService, "createOrAttachRun").mockResolvedValue(shell);

    const response = await request(app).post("/api/polymarket/market-channels/runs").send({ chainId: 137 }).expect(202);

    expect(response.body).toMatchObject({
      status: "queued",
      runId: "run-1",
      pollUrl: "/api/polymarket/market-channels/runs/run-1",
      requestId: "req-123",
    });
  });

  it("reads a run with pagination", async () => {
    vi.spyOn(discoveryRunService.discoveryRunService, "getRun").mockResolvedValue(runReadModel);

    const response = await request(app)
      .get("/api/polymarket/market-channels/runs/run-1?offset=0&limit=2")
      .expect(200)
      .expect("Content-Type", /json/);

    expect(response.body).toMatchObject({
      run: {
        id: "run-1",
        status: "succeeded",
      },
      channels: {
        items: [],
        page: {
          offset: 0,
        },
      },
    });
  });

  it("reads latest run", async () => {
    vi.spyOn(discoveryRunService.discoveryRunService, "getLatestRun").mockResolvedValue(runReadModel);

    const response = await request(app).get("/api/polymarket/market-channels/runs/latest").expect(200);

    expect(response.body).toMatchObject({
      run: {
        id: "run-1",
      },
    });
  });

  it("returns async shell on legacy GET by default", async () => {
    vi.spyOn(discoveryRunService.discoveryRunService, "waitForRunIfAllowed").mockResolvedValue({
      status: "queued",
      runId: "run-1",
      pollUrl: "/api/polymarket/market-channels/runs/run-1",
      requestId: "req-123",
    });

    const response = await request(app).get("/api/polymarket/market-channels?chainId=137").expect(202);

    expect(response.body).toMatchObject({
      status: "queued",
      runId: "run-1",
      pollUrl: "/api/polymarket/market-channels/runs/run-1",
      requestId: "req-123",
    });
  });

  it("returns discovered payload on legacy GET when ready", async () => {
    vi.spyOn(discoveryRunService.discoveryRunService, "waitForRunIfAllowed").mockResolvedValue({
      status: "succeeded",
      runId: "run-1",
      pollUrl: "/api/polymarket/market-channels/runs/run-1",
      requestId: "req-123",
      payload: runResult,
    });

    const response = await request(app)
      .get("/api/polymarket/market-channels?chainId=137&waitMs=1000")
      .expect(200)
      .expect("Content-Type", /json/);

    expect(response.body).toMatchObject(runResult);
  });

  it("returns 400 for invalid input", async () => {
    const response = await request(app)
      .get("/api/polymarket/market-channels/runs/run-1?offset=abc")
      .expect(400)
      .expect("Content-Type", /json/);

    expect(response.body).toMatchObject({
      error: "Failed to discover market channels",
      code: "invalid_input",
      details: {
        component: "controller",
        field: "offset",
      },
    });
  });
});
