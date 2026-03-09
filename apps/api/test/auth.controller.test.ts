import { afterEach, describe, expect, it } from "vitest";
import request from "supertest";

import { createApp } from "../src/app";

describe("Auth controller", () => {
  const app = createApp();
  const originalAuthMode = process.env.ALPHADB_AUTH_MODE;
  const originalTokens = process.env.ALPHADB_API_TOKENS_JSON;
  const originalDefaultUser = process.env.ALPHADB_DEFAULT_USER_ID;

  afterEach(() => {
    if (originalAuthMode === undefined) {
      delete process.env.ALPHADB_AUTH_MODE;
    } else {
      process.env.ALPHADB_AUTH_MODE = originalAuthMode;
    }
    if (originalTokens === undefined) {
      delete process.env.ALPHADB_API_TOKENS_JSON;
    } else {
      process.env.ALPHADB_API_TOKENS_JSON = originalTokens;
    }
    if (originalDefaultUser === undefined) {
      delete process.env.ALPHADB_DEFAULT_USER_ID;
    } else {
      process.env.ALPHADB_DEFAULT_USER_ID = originalDefaultUser;
    }
  });

  it("returns disabled auth status with default viewer", async () => {
    delete process.env.ALPHADB_AUTH_MODE;
    process.env.ALPHADB_DEFAULT_USER_ID = "dev-user";

    const response = await request(app)
      .get("/api/auth/me")
      .expect(200);

    expect(response.body).toMatchObject({
      enabled: false,
      mode: "disabled",
      viewer: {
        userId: "dev-user",
        authMode: "disabled",
      },
    });
  });

  it("returns viewer for valid bearer token", async () => {
    process.env.ALPHADB_AUTH_MODE = "pat";
    process.env.ALPHADB_API_TOKENS_JSON = JSON.stringify([
      { token: "token-1", userId: "sid", tokenId: "sid-dev", label: "Sid local" },
    ]);

    const response = await request(app)
      .get("/api/auth/me")
      .set("Authorization", "Bearer token-1")
      .expect(200);

    expect(response.body).toMatchObject({
      enabled: true,
      mode: "pat",
      viewer: {
        userId: "sid",
        authMode: "pat",
        tokenId: "sid-dev",
        label: "Sid local",
      },
    });
  });

  it("rejects invalid bearer token", async () => {
    process.env.ALPHADB_AUTH_MODE = "pat";
    process.env.ALPHADB_API_TOKENS_JSON = JSON.stringify([
      { token: "token-1", userId: "sid" },
    ]);

    const response = await request(app)
      .get("/api/auth/me")
      .set("Authorization", "Bearer no-match")
      .expect(401);

    expect(response.body).toMatchObject({
      error: "Unauthorized",
      code: "unauthorized",
    });
  });
});
