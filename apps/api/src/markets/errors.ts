import { randomUUID } from "crypto";

type ErrorCode = "invalid_input" | "upstream_failure" | "upstream_network" | "not_found" | "unexpected_error";

interface MarketErrorDetails {
  component?: "controller" | "service" | "provider";
  field?: string;
  provider?: string;
  [key: string]: unknown;
}

interface MarketHttpError {
  status: number;
  body: {
    error: string;
    code: ErrorCode;
    message: string;
    retryable: boolean;
    details: MarketErrorDetails;
    requestId: string;
  };
}

type ErrorRecord = Record<string, unknown>;

function isRecord(value: unknown): value is ErrorRecord {
  return Boolean(value && typeof value === "object");
}

function toRequestId(requestId?: string): string {
  return requestId || randomUUID();
}

export class MarketApiError extends Error {
  code: ErrorCode;
  status: number;
  retryable: boolean;
  details: MarketErrorDetails;

  constructor(
    message: string,
    code: ErrorCode,
    status: number,
    retryable: boolean,
    details: MarketErrorDetails = {},
  ) {
    super(message);
    this.name = "MarketApiError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
    this.details = details;
  }
}

function toHttpError(error: MarketApiError, requestId: string): MarketHttpError {
  return {
    status: error.status,
    body: {
      error: "Failed to load markets",
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      details: error.details,
      requestId,
    },
  };
}

export function mapInvalidInput(message: string, field: string): MarketApiError {
  return new MarketApiError(message, "invalid_input", 400, false, {
    component: "controller",
    field,
  });
}

export function mapNotFound(message: string, details: MarketErrorDetails = {}): MarketApiError {
  return new MarketApiError(message, "not_found", 404, false, {
    component: "service",
    ...details,
  });
}

export function toHttpErrorResponse(error: unknown, requestId?: string): MarketHttpError {
  const requestIdSafe = toRequestId(requestId);

  if (error instanceof MarketApiError) {
    return toHttpError(error, requestIdSafe);
  }

  const record = isRecord(error) ? error : {};
  const status = typeof record.status === "number" ? record.status : undefined;
  const code = typeof record.code === "string" ? record.code : undefined;
  const message = error instanceof Error ? error.message : "Unexpected failure";

  if (status === 400) {
    return toHttpError(
      new MarketApiError(message, "invalid_input", 400, false, { component: "controller" }),
      requestIdSafe,
    );
  }

  if (status === 404) {
    return toHttpError(
      new MarketApiError(message, "not_found", 404, false, { component: "service" }),
      requestIdSafe,
    );
  }

  if (typeof code === "string" && ["ETIMEDOUT", "ECONNRESET", "ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN"].includes(code)) {
    return toHttpError(
      new MarketApiError(`Upstream network failure (${code})`, "upstream_network", 502, true, {
        component: "provider",
        code,
      }),
      requestIdSafe,
    );
  }

  if (status && status >= 400) {
    return toHttpError(
      new MarketApiError(message, "upstream_failure", 502, true, {
        component: "provider",
        status,
      }),
      requestIdSafe,
    );
  }

  return toHttpError(
    new MarketApiError(message, "unexpected_error", 500, false, {
      component: "service",
    }),
    requestIdSafe,
  );
}
