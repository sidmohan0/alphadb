import fs from "node:fs";

import type { Request } from "express";

import type { AuthMode, AuthStatus, AuthViewer } from "@alphadb/market-core";

import { MarketApiError } from "../markets/errors";

interface AuthTokenRecord {
  token: string;
  userId: string;
  tokenId: string | null;
  label: string | null;
}

function toSingleString(value: unknown): string | undefined {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length ? trimmed : undefined;
  }

  if (Array.isArray(value) && value.length > 0 && typeof value[0] === "string") {
    const trimmed = value[0].trim();
    return trimmed.length ? trimmed : undefined;
  }

  return undefined;
}

function invalidAuth(message: string): MarketApiError {
  return new MarketApiError(message, "unauthorized", 401, false, {
    component: "controller",
    field: "authorization",
  });
}

export function getAuthMode(): AuthMode {
  const configured = process.env.ALPHADB_AUTH_MODE?.trim().toLowerCase();
  if (!configured || configured === "disabled") {
    return "disabled";
  }

  if (configured === "pat") {
    return "pat";
  }

  throw new Error("ALPHADB_AUTH_MODE must be one of disabled or pat");
}

export function isAuthEnabled(): boolean {
  return getAuthMode() !== "disabled";
}

function readTokenSource(): unknown {
  if (process.env.ALPHADB_API_TOKENS_JSON?.trim()) {
    return JSON.parse(process.env.ALPHADB_API_TOKENS_JSON);
  }

  if (process.env.ALPHADB_API_TOKENS_PATH?.trim()) {
    const raw = fs.readFileSync(process.env.ALPHADB_API_TOKENS_PATH.trim(), "utf8");
    return JSON.parse(raw);
  }

  return [];
}

function loadConfiguredTokens(): AuthTokenRecord[] {
  const raw = readTokenSource();
  const entries = Array.isArray(raw)
    ? raw
    : raw && typeof raw === "object" && Array.isArray((raw as { tokens?: unknown[] }).tokens)
      ? (raw as { tokens: unknown[] }).tokens
      : [];

  return entries.flatMap((entry) => {
    if (!entry || typeof entry !== "object") {
      return [];
    }

    const rawEntry = entry as Record<string, unknown>;
    const token = toSingleString(rawEntry.token);
    const userId = toSingleString(rawEntry.userId);
    if (!token || !userId) {
      return [];
    }

    return [{
      token,
      userId,
      tokenId: toSingleString(rawEntry.tokenId) ?? null,
      label: toSingleString(rawEntry.label) ?? null,
    }];
  });
}

function viewerForDisabledMode(req: Request): AuthViewer {
  const explicitUserId = toSingleString(req.header("x-alphadb-user-id")) ?? toSingleString(req.query.userId);
  const configuredUserId = process.env.ALPHADB_DEFAULT_USER_ID?.trim() || "local-user";

  return {
    userId: explicitUserId ?? configuredUserId,
    authMode: "disabled",
    tokenId: null,
    label: null,
  };
}

function parseBearerToken(req: Request): string | null {
  const header = req.header("authorization");
  if (!header) {
    return null;
  }

  const [scheme, value] = header.split(/\s+/, 2);
  if (!scheme || scheme.toLowerCase() !== "bearer" || !value?.trim()) {
    throw invalidAuth("Authorization header must use Bearer token format");
  }

  return value.trim();
}

function viewerForToken(token: string): AuthViewer | null {
  const record = loadConfiguredTokens().find((entry) => entry.token === token);
  if (!record) {
    return null;
  }

  return {
    userId: record.userId,
    authMode: "pat",
    tokenId: record.tokenId,
    label: record.label,
  };
}

export function resolveViewer(req: Request, options: { required?: boolean } = {}): AuthViewer | null {
  const mode = getAuthMode();
  if (mode === "disabled") {
    return viewerForDisabledMode(req);
  }

  const token = parseBearerToken(req);
  if (!token) {
    if (options.required) {
      throw invalidAuth("Bearer token required");
    }

    return null;
  }

  const viewer = viewerForToken(token);
  if (!viewer) {
    throw invalidAuth("Invalid API token");
  }

  return viewer;
}

export function requireViewer(req: Request): AuthViewer {
  const viewer = resolveViewer(req, { required: true });
  if (!viewer) {
    throw invalidAuth("Bearer token required");
  }

  return viewer;
}

export function authStatusForRequest(req: Request): AuthStatus {
  const mode = getAuthMode();
  return {
    enabled: mode !== "disabled",
    mode,
    viewer: resolveViewer(req),
  };
}
